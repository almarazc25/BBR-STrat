"""
PEACHY ENGINE — Configuration
=============================================================================
On Railway (or any host) credentials and toggles are read from environment
variables. Locally you can either export them in your shell, drop them in a
`.env` file (auto-loaded if python-dotenv is installed), or edit the defaults
below for a quick test.

Required env vars on Railway:
    SCHWAB_APP_KEY
    SCHWAB_APP_SECRET
    SCHWAB_CALLBACK_URL        (must match the Schwab app config)
    PUSHOVER_USER_KEY
    PUSHOVER_APP_TOKEN
    SCHWAB_TOKEN_JSON          (the contents of schwab_token.json from your
                                first local login — bootstraps the headless
                                container so no interactive OAuth is needed)
    SCHWAB_TOKEN_PATH          (optional, defaults to /data/schwab_token.json
                                — mount a Railway Volume at /data so refreshed
                                tokens persist across deploys/restarts)

Everything else has a sensible strategy-driven default and rarely needs touching.
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
# 1. SCHWAB API CREDENTIALS
# ---------------------------------------------------------------------------
SCHWAB_APP_KEY = _env("SCHWAB_APP_KEY", "PUT_YOUR_SCHWAB_APP_KEY_HERE")
SCHWAB_APP_SECRET = _env("SCHWAB_APP_SECRET", "PUT_YOUR_SCHWAB_APP_SECRET_HERE")
SCHWAB_CALLBACK_URL = _env("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182")

# On Railway, mount a Volume at /data and the refreshed token persists.
# Locally it falls back to the project directory.
SCHWAB_TOKEN_PATH = _env(
    "SCHWAB_TOKEN_PATH",
    "/data/schwab_token.json" if os.path.isdir("/data") else "schwab_token.json",
)

# Optional: bootstrap the token file from an env var (paste the JSON contents
# from a local schwab_token.json after your one-time browser login).
SCHWAB_TOKEN_JSON = _env("SCHWAB_TOKEN_JSON", "")


# ---------------------------------------------------------------------------
# 2. PUSHOVER
# ---------------------------------------------------------------------------
PUSHOVER_USER_KEY = _env("PUSHOVER_USER_KEY", "PUT_YOUR_PUSHOVER_USER_KEY_HERE")
PUSHOVER_APP_TOKEN = _env("PUSHOVER_APP_TOKEN", "PUT_YOUR_PUSHOVER_APP_TOKEN_HERE")
SEND_PUSHOVER = _env_bool("SEND_PUSHOVER", True)
PRINT_TO_TERMINAL = _env_bool("PRINT_TO_TERMINAL", True)


# ---------------------------------------------------------------------------
# 3. WHAT TO ANALYZE
# ---------------------------------------------------------------------------
_tickers_env = _env("TICKERS", "SPY,QQQ")
TICKERS = [t.strip().upper() for t in _tickers_env.split(",") if t.strip()]

NUM_EXPIRATIONS = _env_int("NUM_EXPIRATIONS", 3)
STRIKE_RANGE_PCT = _env_float("STRIKE_RANGE_PCT", 0.05)


# ---------------------------------------------------------------------------
# 4. EXPOSURE CALCULATION KNOBS
# ---------------------------------------------------------------------------
DEALERS_SHORT_CALLS = _env_bool("DEALERS_SHORT_CALLS", True)
CONTRACT_MULTIPLIER = _env_int("CONTRACT_MULTIPLIER", 100)
TOP_N_GEX_LEVELS = _env_int("TOP_N_GEX_LEVELS", 4)
CONFLUENCE_TOLERANCE = _env_float("CONFLUENCE_TOLERANCE", 1.0)


# ---------------------------------------------------------------------------
# 5. ENVIRONMENT CLASSIFICATION THRESHOLDS
# ---------------------------------------------------------------------------
GEX_NEUTRAL_BAND = _env_float("GEX_NEUTRAL_BAND", 0.15)
DEX_NEUTRAL_BAND = _env_float("DEX_NEUTRAL_BAND", 0.15)


# ---------------------------------------------------------------------------
# 6. EXPOSURE PRIORITY WEIGHTS
# ---------------------------------------------------------------------------
WEIGHT_GAMMA = _env_float("WEIGHT_GAMMA", 0.40)   # what KIND of day
WEIGHT_DELTA = _env_float("WEIGHT_DELTA", 0.40)   # direction
WEIGHT_VANNA = _env_float("WEIGHT_VANNA", 0.20)   # light continuation
# (Charm omitted by design.)


# ---------------------------------------------------------------------------
# 7. CHART-LEVEL / STRUCTURE SETTINGS
# ---------------------------------------------------------------------------
TREND_EMA_LENGTH = _env_int("TREND_EMA_LENGTH", 200)
STRUCTURE_TIMEFRAME_MIN = _env_int("STRUCTURE_TIMEFRAME_MIN", 5)
SESSION_OPEN_ET = _env("SESSION_OPEN_ET", "09:30")
SESSION_CLOSE_ET = _env("SESSION_CLOSE_ET", "16:00")
PREMARKET_OPEN_ET = _env("PREMARKET_OPEN_ET", "04:00")


# ---------------------------------------------------------------------------
# 8. ENTRY MODEL CONSTANTS
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
# 9. SCHEDULER (for the long-running Railway service mode)
# ---------------------------------------------------------------------------
# When deployed as a long-running service (not a Railway cron job), runner.py
# wakes up at this ET time on weekdays and fires one analysis pass.
RUN_TIME_ET = _env("RUN_TIME_ET", "09:00")
RUN_ON_START = _env_bool("RUN_ON_START", False)  # also run once at boot
