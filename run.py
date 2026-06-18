"""
PEACHY ENGINE — Main runner
=============================================================================
Run this. It does everything for each ticker:
    1. Pulls the option chain + price history from Schwab
    2. Computes GEX / DEX / vanna and the GEX walls
    3. Computes chart structure (200 EMA, PDH/PDL, PMH/PML) + confluence
    4. Classifies gamma regime + direction, picks the BBR setup, grades it
    5. Prints the full briefing and pushes the tight version to your phone

Single-shot mode (default — what Railway cron and local manual runs use):
    python run.py

Long-running service mode (for Railway "Service" deploys without cron):
    python run.py --serve
=============================================================================
"""

import os
import sys
import json
import time
import traceback
import datetime as dt
from zoneinfo import ZoneInfo

from config import settings
from core.schwab_client import SchwabData
from core import exposures, levels as levels_mod, environment, briefing
from output import pushover

ET = ZoneInfo("America/New_York")


def bootstrap_token_from_env():
    """If a SCHWAB_TOKEN_JSON env var is provided and the token file is
    missing, write it. Lets the headless container start without an
    interactive OAuth flow — generate the file once locally, then paste its
    contents into Railway's SCHWAB_TOKEN_JSON variable."""
    path = settings.SCHWAB_TOKEN_PATH
    payload = settings.SCHWAB_TOKEN_JSON
    if not payload:
        return
    if os.path.exists(path):
        return
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    except Exception:
        pass
    try:
        json.loads(payload)
    except Exception as e:
        print(f"[bootstrap] SCHWAB_TOKEN_JSON is not valid JSON: {e}")
        return
    with open(path, "w") as f:
        f.write(payload)
    print(f"[bootstrap] wrote Schwab token to {path}")


def analyze_ticker(data: SchwabData, ticker: str):
    chain = data.get_chain(ticker)
    spot = chain["spot"]
    candles = data.get_price_history(ticker)

    gex = exposures.compute_gex_by_strike(chain)
    net_dex = exposures.compute_net_dex(chain)
    vanna_proxy = exposures.compute_vanna_proxy(chain)
    gex_levels = exposures.top_gex_levels(gex)

    structure = levels_mod.compute_structure(candles, spot)
    unified_levels = levels_mod.find_confluence(
        gex_levels, structure["chart_levels"], spot
    )

    gamma = environment.classify_gamma(gex)
    direction = environment.classify_direction(
        net_dex, structure, spot, gex["max_abs_strike_gex"]
    )
    setup = environment.select_setup(gamma, direction, unified_levels, spot)
    grade = environment.grade_setup(
        gamma, direction, vanna_proxy, setup, spot
    )

    full = briefing.build_full(
        ticker, spot, gamma, direction, setup, grade,
        unified_levels, structure, vanna_proxy
    )
    push = briefing.build_push(ticker, spot, gamma, direction, setup, grade)

    return full, push, setup, grade


def run_once():
    now = dt.datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    header = f"\n########## PEACHY ENGINE — {now} ##########\n"
    if settings.PRINT_TO_TERMINAL:
        print(header)

    bootstrap_token_from_env()
    data = SchwabData()

    for ticker in settings.TICKERS:
        try:
            full, push, setup, grade = analyze_ticker(data, ticker)
        except Exception as e:  # noqa: BLE001
            err = f"{ticker}: ERROR during analysis: {e}"
            print(err)
            traceback.print_exc()
            pushover.send(f"Peachy {ticker} ERROR", str(e))
            continue

        if settings.PRINT_TO_TERMINAL:
            print(full)
            print()

        title = f"Peachy {ticker} — {grade['grade']}"
        pushover.send(title, push)


def serve_forever():
    """Long-running scheduler mode. Sleeps until the next RUN_TIME_ET on a
    weekday, fires run_once(), then waits for the next day. Use this on
    Railway if you'd rather run a single always-on service than configure
    a separate cron schedule."""
    hh, mm = settings.RUN_TIME_ET.split(":")
    target_h, target_m = int(hh), int(mm)
    print(f"[serve] will run weekdays at {target_h:02d}:{target_m:02d} ET "
          f"(tickers: {', '.join(settings.TICKERS)})")

    if settings.RUN_ON_START:
        print("[serve] RUN_ON_START is true — running once immediately.")
        try:
            run_once()
        except Exception:
            traceback.print_exc()

    while True:
        now = dt.datetime.now(ET)
        run_today = now.replace(hour=target_h, minute=target_m,
                                second=0, microsecond=0)
        if now >= run_today:
            run_today = run_today + dt.timedelta(days=1)
        while run_today.weekday() >= 5:  # skip Sat/Sun
            run_today = run_today + dt.timedelta(days=1)
        sleep_s = (run_today - now).total_seconds()
        print(f"[serve] sleeping {sleep_s/3600:.2f}h until "
              f"{run_today.strftime('%Y-%m-%d %H:%M ET')}")
        while sleep_s > 0:
            chunk = min(sleep_s, 3600)
            time.sleep(chunk)
            sleep_s -= chunk
        try:
            run_once()
        except Exception:
            traceback.print_exc()


def main():
    if "--serve" in sys.argv:
        serve_forever()
    else:
        run_once()


if __name__ == "__main__":
    main()
