"""
PEACHY ENGINE — Schwab API client
=============================================================================
Handles authentication and all data pulls from Schwab.

We use the `schwabdev` library (a clean, maintained wrapper around the official
Schwab Trader API) so we don't have to hand-roll the OAuth2 dance. It manages
the access/refresh token automatically once you've logged in the first time.

First-run login:
    The very first time you run the engine, schwabdev will print a Schwab
    login URL. Open it, log in, approve, and paste the redirect URL back into
    the terminal. After that the token is cached and auto-refreshed — you do
    NOT have to do this every day. (Schwab refresh tokens last ~7 days, so in
    practice you re-login about once a week. The engine warns you when it's
    close.)

What we pull per ticker:
    1. Option chain (calls + puts) with greeks + open interest + IV
       -> drives all exposure math.
    2. Underlying quote (spot price).
    3. Recent 5-min price history -> 200 EMA + prev-day H/L + pre-market H/L.
=============================================================================
"""

import datetime as dt
from zoneinfo import ZoneInfo

import schwabdev

from config import settings

ET = ZoneInfo("America/New_York")


class SchwabData:
    def __init__(self):
        self.client = schwabdev.Client(
            settings.SCHWAB_APP_KEY,
            settings.SCHWAB_APP_SECRET,
            settings.SCHWAB_CALLBACK_URL,
            tokens_file=settings.SCHWAB_TOKEN_PATH,
        )

    # ------------------------------------------------------------------ #
    # Spot price
    # ------------------------------------------------------------------ #
    def get_spot(self, ticker: str) -> float:
        """Latest underlying price."""
        resp = self.client.quote(ticker)
        data = resp.json()
        q = data[ticker]["quote"]
        # 'lastPrice' is the trade price; fall back to mark if needed.
        return float(q.get("lastPrice") or q.get("mark"))

    # ------------------------------------------------------------------ #
    # Option chain
    # ------------------------------------------------------------------ #
    def get_chain(self, ticker: str):
        """
        Pull the full option chain. We ask Schwab to include greeks. We then
        keep only the nearest NUM_EXPIRATIONS expirations and strikes within
        STRIKE_RANGE_PCT of spot.

        Returns a dict:
            {
              "spot": float,
              "contracts": [ {strike, type, oi, gamma, delta, vega, iv,
                              dte, expiry}, ... ]
            }
        """
        resp = self.client.option_chains(
            symbol=ticker,
            contractType="ALL",
            includeUnderlyingQuote=True,
            strategy="SINGLE",
        )
        data = resp.json()

        spot = float(data.get("underlyingPrice") or self.get_spot(ticker))
        lo = spot * (1.0 - settings.STRIKE_RANGE_PCT)
        hi = spot * (1.0 + settings.STRIKE_RANGE_PCT)

        # Schwab nests maps as callExpDateMap / putExpDateMap:
        #   { "2026-06-18:0": { "585.0": [ {contract...} ], ... }, ... }
        # The key before ':' is the expiry date; after ':' is DTE.
        contracts = []
        for side_key, opt_type in (("callExpDateMap", "C"), ("putExpDateMap", "P")):
            exp_map = data.get(side_key, {})
            # Sort expirations chronologically and keep the nearest N.
            exp_keys = sorted(exp_map.keys(), key=lambda k: k.split(":")[0])
            for exp_key in exp_keys[: settings.NUM_EXPIRATIONS]:
                expiry_str, dte_str = exp_key.split(":")
                dte = int(dte_str)
                strike_map = exp_map[exp_key]
                for strike_str, contract_list in strike_map.items():
                    strike = float(strike_str)
                    if strike < lo or strike > hi:
                        continue
                    for c in contract_list:
                        contracts.append({
                            "strike": strike,
                            "type": opt_type,
                            "expiry": expiry_str,
                            "dte": dte,
                            "oi": float(c.get("openInterest") or 0.0),
                            "volume": float(c.get("totalVolume") or 0.0),
                            "gamma": _safe_greek(c.get("gamma")),
                            "delta": _safe_greek(c.get("delta")),
                            "vega": _safe_greek(c.get("vega")),
                            "theta": _safe_greek(c.get("theta")),
                            "iv": _safe_greek(c.get("volatility")),  # in %, e.g. 18.5
                        })

        return {"spot": spot, "contracts": contracts}

    # ------------------------------------------------------------------ #
    # Price history (for EMA + structure levels)
    # ------------------------------------------------------------------ #
    def get_price_history(self, ticker: str):
        """
        Pull enough 5-min candles to compute a 200 EMA and to read
        previous-day and pre-market highs/lows.

        We grab ~10 days of 5-min candles (plenty for a 200-period EMA on the
        5-min and for finding yesterday's session range).

        Returns a list of candles:
            [ {datetime (ET), open, high, low, close, volume}, ... ]
        ordered oldest -> newest.
        """
        resp = self.client.price_history(
            symbol=ticker,
            periodType="day",
            period=10,
            frequencyType="minute",
            frequency=settings.STRUCTURE_TIMEFRAME_MIN,
            needExtendedHoursData=True,   # we need pre-market candles
        )
        data = resp.json()
        candles = []
        for c in data.get("candles", []):
            ts = dt.datetime.fromtimestamp(c["datetime"] / 1000, tz=ET)
            candles.append({
                "datetime": ts,
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": float(c["volume"]),
            })
        candles.sort(key=lambda x: x["datetime"])
        return candles


def _safe_greek(value):
    """Schwab uses -999 / NaN sentinels for missing greeks. Clean them to 0."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if v <= -998 or v != v:  # sentinel or NaN
        return 0.0
    return v
