"""
PEACHY ENGINE — Yahoo Finance data client
=============================================================================
Drop-in replacement for the old Schwab client. No auth, no tokens, no OAuth.
Pulls the option chain + intraday price history from Yahoo via `yfinance`,
and synthesizes per-contract greeks (Yahoo doesn't return them) via Black-
Scholes-Merton so the downstream exposures/levels/environment modules see
exactly the same shape they always have.

DATA CONTRACT (must match what the rest of the engine expects):

    get_chain(ticker) ->
        {
          "spot": float,
          "contracts": [
            {
              "strike": float,
              "type": "C"|"P",
              "expiry": "YYYY-MM-DD",
              "dte": int,
              "oi": float,
              "volume": float,
              "gamma": float,    # per-contract, BSM-computed
              "delta": float,    # per-contract, BSM-computed
              "vega": float,
              "theta": float,
              "iv": float,       # as PERCENTAGE (25.0 = 25%) — engine convention
            }, ...
          ],
        }

    get_price_history(ticker) -> list of 5-min candles, oldest -> newest,
        each {datetime (ET), open, high, low, close, volume}.
        Pre/post-market candles are INCLUDED so levels.py can compute PMH/PML.

    get_spot(ticker) -> float

Caveats:
    - yfinance scrapes Yahoo's endpoints. It can break if Yahoo changes them.
    - Yahoo doesn't expose greeks. We compute them with BSM, which is the
      standard approach used by every public GEX dashboard.
    - Yahoo's IV is the only IV input we trust; we feed it straight into BSM.
=============================================================================
"""

import math
import datetime as dt
from zoneinfo import ZoneInfo

import yfinance as yf
from scipy.stats import norm

from config import settings

ET = ZoneInfo("America/New_York")


# --------------------------------------------------------------------------- #
# Black-Scholes-Merton greeks (per-contract)
# --------------------------------------------------------------------------- #
def bsm_greeks(spot: float, strike: float, tte_years: float,
               iv_decimal: float, r: float, opt_type: str) -> dict:
    """
    Return {delta, gamma, vega, theta} for a single option leg.

    Args:
        spot: underlying spot price.
        strike: option strike.
        tte_years: time to expiration in years (dte / 365.0).
        iv_decimal: implied vol as a DECIMAL (0.25 means 25%).
        r: risk-free rate as a decimal (e.g. 0.05).
        opt_type: "C" for call, "P" for put.

    Returns zeros for degenerate inputs (expired, invalid IV).
    Vega and theta are returned in conventional retail units:
        vega  = $ change in option price per 1% IV move
        theta = $ change in option price per 1 calendar day
    """
    if tte_years <= 0 or iv_decimal <= 0 or spot <= 0 or strike <= 0:
        return {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}

    sqrt_t = math.sqrt(tte_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv_decimal ** 2) * tte_years) \
        / (iv_decimal * sqrt_t)
    d2 = d1 - iv_decimal * sqrt_t

    pdf_d1 = norm.pdf(d1)

    gamma = pdf_d1 / (spot * iv_decimal * sqrt_t)
    vega = spot * pdf_d1 * sqrt_t / 100.0

    if opt_type == "C":
        delta = norm.cdf(d1)
        theta = (-(spot * pdf_d1 * iv_decimal) / (2.0 * sqrt_t)
                 - r * strike * math.exp(-r * tte_years) * norm.cdf(d2)) / 365.0
    else:
        delta = norm.cdf(d1) - 1.0
        theta = (-(spot * pdf_d1 * iv_decimal) / (2.0 * sqrt_t)
                 + r * strike * math.exp(-r * tte_years) * norm.cdf(-d2)) / 365.0

    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta}


# --------------------------------------------------------------------------- #
# Yahoo client
# --------------------------------------------------------------------------- #
class YahooData:
    """Thin shim around yfinance that returns engine-shaped data."""

    def __init__(self):
        self._cache = {}  # per-ticker yf.Ticker cache (cheap to re-create but
                          # cheaper to reuse during a polling session)

    def _ticker(self, symbol: str):
        t = self._cache.get(symbol)
        if t is None:
            t = yf.Ticker(symbol)
            self._cache[symbol] = t
        return t

    # ------------------------------------------------------------------ #
    # Spot
    # ------------------------------------------------------------------ #
    def get_spot(self, ticker: str) -> float:
        """Latest underlying price. Prefers fast_info (no scrape), falls
        back to .info if needed, and finally to the last 5-min close."""
        t = self._ticker(ticker)
        # fast_info is the cheapest path.
        try:
            fi = t.fast_info
            for key in ("last_price", "lastPrice", "regular_market_price",
                        "regularMarketPrice"):
                val = getattr(fi, key, None) if not isinstance(fi, dict) else fi.get(key)
                if val:
                    return float(val)
        except Exception:
            pass
        # .info is heavier but more complete.
        try:
            info = t.info
            for key in ("currentPrice", "regularMarketPrice", "preMarketPrice",
                        "postMarketPrice"):
                val = info.get(key)
                if val:
                    return float(val)
        except Exception:
            pass
        # Last-resort: pull a tiny history slice.
        hist = t.history(period="1d", interval="1m", prepost=True)
        if hist is not None and len(hist) > 0:
            return float(hist["Close"].iloc[-1])
        raise RuntimeError(f"Could not resolve spot price for {ticker}")

    # ------------------------------------------------------------------ #
    # Option chain
    # ------------------------------------------------------------------ #
    def get_chain(self, ticker: str) -> dict:
        """
        Pull the nearest NUM_EXPIRATIONS expirations, keep strikes within
        STRIKE_RANGE_PCT of spot, skip zero-OI contracts, and synthesize
        greeks via BSM. Returns the engine's standard chain dict.
        """
        t = self._ticker(ticker)
        spot = self.get_spot(ticker)
        lo = spot * (1.0 - settings.STRIKE_RANGE_PCT)
        hi = spot * (1.0 + settings.STRIKE_RANGE_PCT)
        r = settings.RISK_FREE_RATE

        expirations = list(t.options or ())
        expirations = expirations[: settings.NUM_EXPIRATIONS]

        today_et = dt.datetime.now(ET).date()
        contracts = []

        for exp_str in expirations:
            try:
                exp_date = dt.datetime.strptime(exp_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            dte = max((exp_date - today_et).days, 0)
            # Use a tiny floor so 0DTE still produces non-zero greeks.
            tte_years = max(dte, 0.5) / 365.0

            try:
                chain = t.option_chain(exp_str)
            except Exception as e:
                print(f"[yahoo] option_chain failed for {ticker} {exp_str}: {e}")
                continue

            for df, opt_type in ((chain.calls, "C"), (chain.puts, "P")):
                if df is None or len(df) == 0:
                    continue
                for _, row in df.iterrows():
                    strike = float(row.get("strike", 0.0) or 0.0)
                    if strike < lo or strike > hi:
                        continue
                    oi = float(row.get("openInterest") or 0.0)
                    if oi <= 0:
                        continue
                    iv_dec = float(row.get("impliedVolatility") or 0.0)
                    greeks = bsm_greeks(spot, strike, tte_years, iv_dec, r,
                                        opt_type)
                    contracts.append({
                        "strike": strike,
                        "type": opt_type,
                        "expiry": exp_str,
                        "dte": dte,
                        "oi": oi,
                        "volume": float(row.get("volume") or 0.0),
                        "gamma": greeks["gamma"],
                        "delta": greeks["delta"],
                        "vega": greeks["vega"],
                        "theta": greeks["theta"],
                        "iv": iv_dec * 100.0,   # engine wants percentage
                    })

        return {"spot": spot, "contracts": contracts}

    # ------------------------------------------------------------------ #
    # Intraday price history (5-min with pre/post-market)
    # ------------------------------------------------------------------ #
    def get_price_history(self, ticker: str) -> list:
        """
        ~60 days of 5-min candles INCLUDING pre/post-market data so
        levels.py can compute prev-day H/L and today's PMH/PML.

        Returns list of dicts (oldest -> newest):
            { "datetime" (ET tz-aware), "open", "high", "low",
              "close", "volume" }
        """
        t = self._ticker(ticker)
        # Yahoo caps 5-min intraday history at ~60 days — plenty for 200-period
        # EMA on the 5-min and for finding yesterday's session range.
        hist = t.history(
            period="60d",
            interval=f"{settings.STRUCTURE_TIMEFRAME_MIN}m",
            prepost=True,
            auto_adjust=False,
        )
        candles = []
        if hist is None or len(hist) == 0:
            return candles

        for idx, row in hist.iterrows():
            # idx is a pandas Timestamp; coerce to ET-aware datetime.
            ts = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=ET)
            else:
                ts = ts.astimezone(ET)
            candles.append({
                "datetime": ts,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row.get("Volume") or 0.0),
            })
        candles.sort(key=lambda x: x["datetime"])
        return candles
