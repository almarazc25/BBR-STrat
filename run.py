"""
PEACHY ENGINE — Main runner
=============================================================================
Three modes:

    python run.py            # one-shot pre-market briefing (default)
    python run.py --serve    # long-running daemon, fires at RUN_TIME_ET daily
    python run.py --live     # intraday polling, alerts on exposure shifts

Data source is picked by settings.DATA_SOURCE:
    "schwab"  -> real-time Schwab API (default)
    "yahoo"   -> free yfinance fallback (~15 min delayed)
=============================================================================
"""

import os
import sys
import json
import time
import argparse
import traceback
import datetime as dt
from zoneinfo import ZoneInfo

from config import settings
from core import exposures, levels as levels_mod, environment, briefing
from output import pushover

ET = ZoneInfo("America/New_York")


# --------------------------------------------------------------------------- #
# Data source selection
# --------------------------------------------------------------------------- #
def make_data_client():
    """Pick the data backend based on settings.DATA_SOURCE."""
    src = settings.DATA_SOURCE
    if src == "yahoo":
        from core.yahoo_client import YahooData
        return YahooData()
    if src == "schwab":
        bootstrap_token_from_env()
        from core.schwab_client import SchwabData
        return SchwabData()
    raise ValueError(f"Unknown DATA_SOURCE: {src!r} (use 'schwab' or 'yahoo')")


def bootstrap_token_from_env():
    """If SCHWAB_TOKEN_JSON env var is provided and the token file is
    missing, write it. Lets a headless container start without an
    interactive OAuth flow — generate the file once locally, then paste
    its contents into Railway's SCHWAB_TOKEN_JSON variable."""
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


# --------------------------------------------------------------------------- #
# Per-ticker analysis (shared by all three modes)
# --------------------------------------------------------------------------- #
def analyze_ticker(data, ticker: str):
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

    return {
        "spot": spot,
        "gex": gex,
        "net_dex": net_dex,
        "vanna": vanna_proxy,
        "gex_levels": gex_levels,
        "gamma": gamma,
        "direction": direction,
        "setup": setup,
        "grade": grade,
        "full": full,
        "push": push,
    }


# --------------------------------------------------------------------------- #
# Mode 1 — one-shot
# --------------------------------------------------------------------------- #
def run_once():
    now = dt.datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    header = f"\n########## PEACHY ENGINE — {now} ##########\n"
    if settings.PRINT_TO_TERMINAL:
        print(header)
        print(f"(data source: {settings.DATA_SOURCE})\n")

    data = make_data_client()

    for ticker in settings.TICKERS:
        try:
            r = analyze_ticker(data, ticker)
        except Exception as e:  # noqa: BLE001
            err = f"{ticker}: ERROR during analysis: {e}"
            print(err)
            traceback.print_exc()
            pushover.send(f"Peachy {ticker} ERROR", str(e))
            continue

        if settings.PRINT_TO_TERMINAL:
            print(r["full"])
            print()

        title = f"Peachy {ticker} — {r['grade']['grade']}"
        pushover.send(title, r["push"])


# --------------------------------------------------------------------------- #
# Mode 2 — long-running scheduler
# --------------------------------------------------------------------------- #
def serve_forever():
    hh, mm = settings.RUN_TIME_ET.split(":")
    target_h, target_m = int(hh), int(mm)
    print(f"[serve] will run weekdays at {target_h:02d}:{target_m:02d} ET "
          f"(tickers: {', '.join(settings.TICKERS)}, "
          f"source: {settings.DATA_SOURCE})")

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
        while run_today.weekday() >= 5:
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


# --------------------------------------------------------------------------- #
# Mode 3 — live intraday polling
# --------------------------------------------------------------------------- #
def _parse_hhmm(s: str):
    h, m = s.split(":")
    return int(h), int(m)


def _top_wall_strike(gex_levels: list):
    if not gex_levels:
        return None
    biggest = max(gex_levels, key=lambda l: abs(l.get("gex", 0.0)))
    return biggest["strike"]


def _detect_shifts(ticker: str, baseline: dict, current: dict) -> list:
    """Return list of alert lines describing material changes from the
    morning baseline. Empty list = nothing worth alerting on."""
    alerts = []

    base_gex = baseline["gex"]["net_gex"]
    curr_gex = current["gex"]["net_gex"]

    if settings.GEX_FLIP_ALERT:
        base_sign = 1 if base_gex >= 0 else -1
        curr_sign = 1 if curr_gex >= 0 else -1
        if base_sign != curr_sign:
            base_label = "+Gamma" if base_sign > 0 else "-Gamma"
            curr_label = "+Gamma" if curr_sign > 0 else "-Gamma"
            regime_word = "trending" if curr_sign < 0 else "mean-reverting"
            alerts.append(f"GEX FLIPPED: {base_label} -> {curr_label} "
                          f"({regime_word} regime now)")

    base_dex = baseline["net_dex"]
    curr_dex = current["net_dex"]
    denom = max(abs(base_dex), 1.0)
    if abs(curr_dex - base_dex) / denom >= settings.DEX_SHIFT_PCT:
        def _bias(v, gex_abs):
            band = settings.DEX_NEUTRAL_BAND * (gex_abs or 1.0)
            if abs(v) <= band:
                return "neutral"
            return "bullish" if v > 0 else "bearish"
        base_b = _bias(base_dex, baseline["gex"]["max_abs_strike_gex"])
        curr_b = _bias(curr_dex, current["gex"]["max_abs_strike_gex"])
        if base_b != curr_b:
            alerts.append(f"DEX: was {base_b} -> now {curr_b}")
        else:
            pct = (curr_dex - base_dex) / denom * 100.0
            alerts.append(f"DEX shifted {pct:+.0f}% vs baseline ({curr_b})")

    base_top = _top_wall_strike(baseline["gex_levels"])
    curr_top = _top_wall_strike(current["gex_levels"])
    if base_top is not None and curr_top is not None:
        if abs(curr_top - base_top) >= settings.LEVEL_SHIFT_STRIKES:
            alerts.append(f"Top wall: {base_top:.0f} -> {curr_top:.0f}")

    return alerts


def _in_market_hours(now: dt.datetime) -> bool:
    open_h, open_m = _parse_hhmm(settings.LIVE_MODE_START)
    close_h, close_m = _parse_hhmm(settings.LIVE_MODE_END)
    if now.weekday() >= 5:
        return False
    o = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    c = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
    return o <= now <= c


def run_live_mode():
    """Pull baseline, then poll every POLL_INTERVAL_MINUTES until close,
    alerting on regime flips / DEX swings / wall shifts."""
    print(f"[live] starting intraday polling every "
          f"{settings.POLL_INTERVAL_MINUTES} min "
          f"({settings.LIVE_MODE_START}-{settings.LIVE_MODE_END} ET, "
          f"tickers: {', '.join(settings.TICKERS)}, "
          f"source: {settings.DATA_SOURCE})")

    data = make_data_client()
    baselines = {}
    fired_alerts = {t: set() for t in settings.TICKERS}

    for ticker in settings.TICKERS:
        try:
            r = analyze_ticker(data, ticker)
            baselines[ticker] = r
            if settings.PRINT_TO_TERMINAL:
                print(r["full"])
                print()
            pushover.send(f"Peachy {ticker} BASELINE — {r['grade']['grade']}",
                          r["push"])
        except Exception as e:  # noqa: BLE001
            print(f"[live] baseline {ticker} ERROR: {e}")
            traceback.print_exc()

    poll_s = settings.POLL_INTERVAL_MINUTES * 60

    while True:
        now = dt.datetime.now(ET)
        if not _in_market_hours(now):
            close_h, close_m = _parse_hhmm(settings.LIVE_MODE_END)
            close_t = now.replace(hour=close_h, minute=close_m,
                                  second=0, microsecond=0)
            if now > close_t and now.weekday() < 5:
                print(f"[live] {now.strftime('%H:%M ET')} past close — exiting.")
                return
            time.sleep(poll_s)
            continue

        time.sleep(poll_s)

        now = dt.datetime.now(ET)
        ts = now.strftime("%H:%M ET")

        for ticker in settings.TICKERS:
            base = baselines.get(ticker)
            if base is None:
                try:
                    base = analyze_ticker(data, ticker)
                    baselines[ticker] = base
                except Exception:
                    continue

            try:
                curr = analyze_ticker(data, ticker)
            except Exception as e:  # noqa: BLE001
                print(f"[live] poll {ticker} ERROR: {e}")
                continue

            alerts = _detect_shifts(ticker, base, curr)
            if not alerts:
                if settings.PRINT_TO_TERMINAL:
                    print(f"[live] {ts} {ticker}: no material change.")
                continue

            key = "|".join(alerts)
            if key in fired_alerts[ticker]:
                continue
            fired_alerts[ticker].add(key)

            head = f"{ticker} EXPOSURE SHIFT"
            body_lines = [f"{head} - {ts}"] + alerts
            body_lines.append("Action: prior setup may be invalid. Reassess.")
            message = "\n".join(body_lines)

            print(message)
            pushover.send(f"Peachy {ticker} SHIFT", message)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description="Peachy Engine")
    parser.add_argument("--serve", action="store_true",
                        help="Long-running scheduler mode.")
    parser.add_argument("--live", action="store_true",
                        help="Intraday polling mode.")
    args = parser.parse_args()

    if args.serve:
        serve_forever()
    elif args.live:
        run_live_mode()
    else:
        run_once()


if __name__ == "__main__":
    main()
