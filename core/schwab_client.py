"""
PEACHY ENGINE — Schwab API client
=============================================================================
Pulls option chain + intraday price history from the Schwab Trader API via
the `schwabdev` library, which handles OAuth2 auth and auto-refreshes the
token after the first browser login.

First-run login:
    schwabdev prints a Schwab OAuth URL. Open it, log in, approve, paste the
    redirect URL back. After that the token is cached at SCHWAB_TOKEN_PATH
    and auto-refreshes — Schwab refresh tokens last ~7 days.

DATA CONTRACT (must match what the rest of the engine expects):

    get_chain(ticker) ->
        {
          "spot": float,
          "contracts": [
            {"strike", "type" ("C"|"P"), "expiry", "dte", "oi", "volume",
             "gamma", "delta", "vega", "theta", "iv" (as percentage)},
            ...
          ],
        }

    get_price_history(ticker) -> list of 5-min candles oldest -> newest,
        each {datetime (ET), open, high, low, close, volume}.

    get_spot(ticker) -> float
=============================================================================
"""

import time
import datetime as dt
from zoneinfo import ZoneInfo

import schwabdev

from config import settings

ET = ZoneInfo("America/New_York")


def _retry(fn, label: str):
    """Retry a Schwab API call with exponential backoff. Schwab's gateway
    is flaky on the 10s default timeout, especially during pre/post market."""
    attempts = max(1, settings.SCHWAB_RETRY_ATTEMPTS)
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < attempts - 1:
                wait = 2.0 * (2 ** i)
                print(f"[schwab] {label} retry {i+1}/{attempts} after "
                      f"{wait:.0f}s — {type(e).__name__}: {e}")
                time.sleep(wait)
    raise last


class SchwabData:
    def __init__(self):
        self.client = schwabdev.Client(
            settings.SCHWAB_APP_KEY,
            settings.SCHWAB_APP_SECRET,
            settings.SCHWAB_CALLBACK_URL,
            tokens_file=settings.SCHWAB_TOKEN_PATH,
        )
        # Bump the underlying requests session timeout if schwabdev exposes it.
        try:
            sess = getattr(self.client, "_session", None) or getattr(self.client, "session", None)
            if sess is not None:
                # requests doesn't have a session-level timeout; patch the
                # default via a transport adapter wrapper if supported.
                # Most schwabdev versions accept a per-call timeout argument.
                # We rely on _retry to cover transient failures.
                pass
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Spot
    # ------------------------------------------------------------------ #
    def get_spot(self, ticker: str) -> float:
        resp = _retry(lambda: self.client.quote(ticker), f"quote({ticker})")
        data = resp.json()
        q = data[ticker]["quote"]
        return float(q.get("lastPrice") or q.get("mark"))

    # ------------------------------------------------------------------ #
    # Option chain
    # ------------------------------------------------------------------ #
    def get_chain(self, ticker: str):
        resp = _retry(
            lambda: self.client.option_chains(
                symbol=ticker,
                contractType="ALL",
                includeUnderlyingQuote=True,
                strategy="SINGLE",
            ),
            f"option_chains({ticker})",
        )
        data = resp.json()

        spot = float(data.get("underlyingPrice") or self.get_spot(ticker))
        lo = spot * (1.0 - settings.STRIKE_RANGE_PCT)
        hi = spot * (1.0 + settings.STRIKE_RANGE_PCT)

        # Schwab nests maps as callExpDateMap / putExpDateMap:
        #   { "2026-06-18:0": { "585.0": [ {contract...} ], ... }, ... }
        contracts = []
        for side_key, opt_type in (("callExpDateMap", "C"), ("putExpDateMap", "P")):
            exp_map = data.get(side_key, {})
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
                            "iv": _safe_greek(c.get("volatility")),
                        })

        return {"spot": spot, "contracts": contracts}

    # ------------------------------------------------------------------ #
    # Price history (5-min candles, prepost included)
    # ------------------------------------------------------------------ #
    def get_price_history(self, ticker: str):
        resp = _retry(
            lambda: self.client.price_history(
                symbol=ticker,
                periodType="day",
                period=10,
                frequencyType="minute",
                frequency=settings.STRUCTURE_TIMEFRAME_MIN,
                needExtendedHoursData=True,
            ),
            f"price_history({ticker})",
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
    """Schwab uses -999 / NaN sentinels for missing greeks. Clean to 0."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if v <= -998 or v != v:
        return 0.0
    return v
