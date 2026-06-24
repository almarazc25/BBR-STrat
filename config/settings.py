"""
PEACHY ENGINE — Configuration
=============================================================================
Env-driven config. Locally: drop creds in a `.env` file (auto-loaded if
python-dotenv is installed). Railway: paste into the Variables tab.

Two data sources are supported, selected by `DATA_SOURCE`:
    "schwab" (default)  — real-time-ish, requires Schwab OAuth setup
    "yahoo"             — free fallback via yfinance, no auth, ~15 min delayed

Required env vars (Schwab mode):
    SCHWAB_APP_KEY
    SCHWAB_APP_SECRET
    SCHWAB_CALLBACK_URL
    SCHWAB_TOKEN_JSON  (Railway only — paste contents of a local
                       schwab_token.json from your one-time browser login)
    PUSHOVER_USER_KEY
    PUSHOVER_APP_TOKEN

Required env vars (Yahoo mode):
    PUSHOVER_USER_KEY
    PUSHOVER_APP_TOKEN
=============================================================================
"""

import os

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
# 1. DATA SOURCE
# ---------------------------------------------------------------------------
# "schwab" = real-time, requires OAuth; "yahoo" = no-auth fallback.
DATA_SOURCE = _env("DATA_SOURCE", "schwab").strip().lower()


# ---------------------------------------------------------------------------
# 2. SCHWAB API CREDENTIALS
# ---------------------------------------------------------------------------
SCHWAB_APP_KEY = _env("SCHWAB_APP_KEY", "PUT_YOUR_SCHWAB_APP_KEY_HERE")
SCHWAB_APP_SECRET = _env("SCHWAB_APP_SECRET", "PUT_YOUR_SCHWAB_APP_SECRET_HERE")
SCHWAB_CALLBACK_URL = _env("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182")

# On Railway, mount a Volume at /data so the refreshed token persists.
SCHWAB_TOKEN_PATH = _env(
    "SCHWAB_TOKEN_PATH",
    "/data/schwab_token.json" if os.path.isdir("/data") else "schwab_token.json",
)

# Bootstrap the token file from an env var (paste the JSON contents
# from a local schwab_token.json after your one-time browser login).
SCHWAB_TOKEN_JSON = _env("SCHWAB_TOKEN_JSON", "")


# ---------------------------------------------------------------------------
# 3. PUSHOVER
# ---------------------------------------------------------------------------
PUSHOVER_USER_KEY = _env("PUSHOVER_USER_KEY", "PUT_YOUR_PUSHOVER_USER_KEY_HERE")
PUSHOVER_APP_TOKEN = _env("PUSHOVER_APP_TOKEN", "PUT_YOUR_PUSHOVER_APP_TOKEN_HERE")
SEND_PUSHOVER = _env_bool("SEND_PUSHOVER", True)
PRINT_TO_TERMINAL = _env_bool("PRINT_TO_TERMINAL", True)


# ---------------------------------------------------------------------------
# 4. WHAT TO ANALYZE
# ---------------------------------------------------------------------------
_tickers_env = _env("TICKERS", "SPY,QQQ")
TICKERS = [t.strip().upper() for t in _tickers_env.split(",") if t.strip()]

NUM_EXPIRATIONS = _env_int("NUM_EXPIRATIONS", 3)
STRIKE_RANGE_PCT = _env_float("STRIKE_RANGE_PCT", 0.05)


# ---------------------------------------------------------------------------
# 5. EXPOSURE CALCULATION KNOBS
# ---------------------------------------------------------------------------
DEALERS_SHORT_CALLS = _env_bool("DEALERS_SHORT_CALLS", True)
CONTRACT_MULTIPLIER = _env_int("CONTRACT_MULTIPLIER", 100)
TOP_N_GEX_LEVELS = _env_int("TOP_N_GEX_LEVELS", 4)
CONFLUENCE_TOLERANCE = _env_float("CONFLUENCE_TOLERANCE", 1.0)

# Risk-free rate for BSM greeks (only used by Yahoo client — Schwab returns
# its own greeks). Bump occasionally to track Fed funds.
RISK_FREE_RATE = _env_float("RISK_FREE_RATE", 0.05)


# ---------------------------------------------------------------------------
# 6. ENVIRONMENT CLASSIFICATION THRESHOLDS
# ---------------------------------------------------------------------------
GEX_NEUTRAL_BAND = _env_float("GEX_NEUTRAL_BAND", 0.15)
DEX_NEUTRAL_BAND = _env_float("DEX_NEUTRAL_BAND", 0.15)


# ---------------------------------------------------------------------------
# 7. EXPOSURE PRIORITY WEIGHTS
# ---------------------------------------------------------------------------
WEIGHT_GAMMA = _env_float("WEIGHT_GAMMA", 0.40)   # what KIND of day
WEIGHT_DELTA = _env_float("WEIGHT_DELTA", 0.40)   # direction
WEIGHT_VANNA = _env_float("WEIGHT_VANNA", 0.20)   # light continuation
# (Charm omitted by design.)


# ---------------------------------------------------------------------------
# 8. CHART-LEVEL / STRUCTURE SETTINGS
# ---------------------------------------------------------------------------
TREND_EMA_LENGTH = _env_int("TREND_EMA_LENGTH", 200)
STRUCTURE_TIMEFRAME_MIN = _env_int("STRUCTURE_TIMEFRAME_MIN", 5)
SESSION_OPEN_ET = _env("SESSION_OPEN_ET", "09:30")
SESSION_CLOSE_ET = _env("SESSION_CLOSE_ET", "16:00")
PREMARKET_OPEN_ET = _env("PREMARKET_OPEN_ET", "04:00")


# ---------------------------------------------------------------------------
# 9. ENTRY MODEL CONSTANTS
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
# 10. SCHEDULER (long-running --serve mode)
# ---------------------------------------------------------------------------
RUN_TIME_ET = _env("RUN_TIME_ET", "09:00")
# Fires a briefing immediately on container start (= every Railway redeploy).
# Default True so you always get a fresh notification after pushing.
RUN_ON_START = _env_bool("RUN_ON_START", True)

# Notification prefix for Pushover titles. Default empty — the engine drops
# the old "Peachy" prefix unless you re-add it via env.
NOTIFICATION_PREFIX = _env("NOTIFICATION_PREFIX", "")

# Pick the highest-graded ticker and send ONE notification per phase instead
# of one per ticker. The runner-up is summarized in a single line below.
CONSOLIDATE_TICKERS = _env_bool("CONSOLIDATE_TICKERS", True)

# Schwab API call retry attempts (covers the 10s read timeouts during
# pre/post market when Schwab's gateway is slow).
SCHWAB_RETRY_ATTEMPTS = _env_int("SCHWAB_RETRY_ATTEMPTS", 3)


# ---------------------------------------------------------------------------
# 11. LIVE / INTRADAY POLLING MODE (--live)
# ---------------------------------------------------------------------------
POLL_INTERVAL_MINUTES = _env_int("POLL_INTERVAL_MINUTES", 5)
LIVE_MODE_START = _env("LIVE_MODE_START", "09:30")
LIVE_MODE_END = _env("LIVE_MODE_END", "16:00")
GEX_FLIP_ALERT = _env_bool("GEX_FLIP_ALERT", True)
DEX_SHIFT_PCT = _env_float("DEX_SHIFT_PCT", 0.25)
LEVEL_SHIFT_STRIKES = _env_int("LEVEL_SHIFT_STRIKES", 3)

# Proximity alert: fire when spot enters this % band of a top GEX wall.
# 0.0025 = 0.25% (about 1.50 from a 600-level wall on SPY).
PROXIMITY_PCT = _env_float("PROXIMITY_PCT", 0.0025)
