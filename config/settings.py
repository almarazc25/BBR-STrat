"""
PEACHY ENGINE — Configuration
=============================================================================
Everything is env-driven so Railway (or any host) can inject credentials and
toggles without touching code. Locally you can either export them in your
shell, drop them in a `.env` file (auto-loaded if python-dotenv is installed),
or edit the defaults below for a quick test.

Required env vars on Railway:
    PUSHOVER_USER_KEY
    PUSHOVER_APP_TOKEN

Everything else has a sensible strategy-driven default. No Schwab auth, no
OAuth tokens — the Yahoo data layer needs nothing.
=============================================================================
"""

import os

# Optional: load a local .env if python-dotenv is present (dev convenience).
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# 1. PUSHOVER
# ---------------------------------------------------------------------------
PUSHOVER_USER_KEY = _env("PUSHOVER_USER_KEY", "PUT_YOUR_PUSHOVER_USER_KEY_HERE")
PUSHOVER_APP_TOKEN = _env("PUSHOVER_APP_TOKEN", "PUT_YOUR_PUSHOVER_APP_TOKEN_HERE")
SEND_PUSHOVER = _env_bool("SEND_PUSHOVER", True)
PRINT_TO_TERMINAL = _env_bool("PRINT_TO_TERMINAL", True)


# ---------------------------------------------------------------------------
# 2. WHAT TO ANALYZE
# ---------------------------------------------------------------------------
_tickers_env = _env("TICKERS", "SPY,QQQ")
TICKERS = [t.strip().upper() for t in _tickers_env.split(",") if t.strip()]

NUM_EXPIRATIONS = _env_int("NUM_EXPIRATIONS", 6)
STRIKE_RANGE_PCT = _env_float("STRIKE_RANGE_PCT", 0.05)


# ---------------------------------------------------------------------------
# 3. EXPOSURE CALCULATION KNOBS
# ---------------------------------------------------------------------------
DEALERS_SHORT_CALLS = _env_bool("DEALERS_SHORT_CALLS", True)
CONTRACT_MULTIPLIER = _env_int("CONTRACT_MULTIPLIER", 100)
TOP_N_GEX_LEVELS = _env_int("TOP_N_GEX_LEVELS", 4)
CONFLUENCE_TOLERANCE = _env_float("CONFLUENCE_TOLERANCE", 1.0)

# Risk-free rate for BSM greeks. Bump occasionally to match Fed funds.
RISK_FREE_RATE = _env_float("RISK_FREE_RATE", 0.05)


# ---------------------------------------------------------------------------
# 4. ENVIRONMENT CLASSIFICATION THRESHOLDS
# ---------------------------------------------------------------------------
GEX_NEUTRAL_BAND = _env_float("GEX_NEUTRAL_BAND", 0.15)
DEX_NEUTRAL_BAND = _env_float("DEX_NEUTRAL_BAND", 0.15)


# ---------------------------------------------------------------------------
# 5. EXPOSURE PRIORITY WEIGHTS
# ---------------------------------------------------------------------------
WEIGHT_GAMMA = _env_float("WEIGHT_GAMMA", 0.40)   # what KIND of day
WEIGHT_DELTA = _env_float("WEIGHT_DELTA", 0.40)   # direction
WEIGHT_VANNA = _env_float("WEIGHT_VANNA", 0.20)   # light continuation
# (Charm omitted by design.)


# ---------------------------------------------------------------------------
# 6. CHART-LEVEL / STRUCTURE SETTINGS
# ---------------------------------------------------------------------------
TREND_EMA_LENGTH = _env_int("TREND_EMA_LENGTH", 200)
STRUCTURE_TIMEFRAME_MIN = _env_int("STRUCTURE_TIMEFRAME_MIN", 5)
SESSION_OPEN_ET = _env("SESSION_OPEN_ET", "09:30")
SESSION_CLOSE_ET = _env("SESSION_CLOSE_ET", "16:00")
PREMARKET_OPEN_ET = _env("PREMARKET_OPEN_ET", "04:00")


# ---------------------------------------------------------------------------
# 7. ENTRY MODEL CONSTANTS
# ---------------------------------------------------------------------------
CONFIRMATION_TIMEFRAME_MIN = _env_int("CONFIRMATION_TIMEFRAME_MIN", 5)
DISPLACEMENT_BODY_MIN_PCT = _env_float("DISPLACEMENT_BODY_MIN_PCT", 0.50)
CLOSE_LOCATION_THIRD = _env_float("CLOSE_LOCATION_THIRD", 1.0 / 3.0)
DEFAULT_STOP_PCT = _env_float("DEFAULT_STOP_PCT", -0.25)
MIN_REWARD_RISK = _env_float("MIN_REWARD_RISK", 2.0)

PRIME_WINDOW_ET = (
    _env("PRIME_WINDOW_START_ET", "09:30"),
    _env("PRIME_WINDOW_END_ET", "12:00"),
)


# ---------------------------------------------------------------------------
# 8. SCHEDULER (long-running --serve mode)
# ---------------------------------------------------------------------------
RUN_TIME_ET = _env("RUN_TIME_ET", "09:00")
RUN_ON_START = _env_bool("RUN_ON_START", False)


# ---------------------------------------------------------------------------
# 9. LIVE / INTRADAY POLLING MODE (--live)
# ---------------------------------------------------------------------------
# How often to re-pull the chain and recompute exposures during market hours.
# Yahoo doesn't rate-limit hard at 5 min. Don't go below 2.
POLL_INTERVAL_MINUTES = _env_int("POLL_INTERVAL_MINUTES", 5)

# Market hours window for live mode (ET). Outside this window, the live loop
# sleeps until the next open.
LIVE_MODE_START = _env("LIVE_MODE_START", "09:30")
LIVE_MODE_END = _env("LIVE_MODE_END", "16:00")

# Alert toggles + thresholds.
GEX_FLIP_ALERT = _env_bool("GEX_FLIP_ALERT", True)     # net GEX sign flipped
DEX_SHIFT_PCT = _env_float("DEX_SHIFT_PCT", 0.25)      # |dDEX| / |baseline DEX|
LEVEL_SHIFT_STRIKES = _env_int("LEVEL_SHIFT_STRIKES", 3)  # #1 wall moved Nx strikes
