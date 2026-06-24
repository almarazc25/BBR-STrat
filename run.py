"""
PEACHY ENGINE — Main runner
=============================================================================
Three modes:

    python run.py            # one-shot pre-market briefing (default)
    python run.py --serve    # UNIFIED daemon (the one Railway runs):
                             #   • morning briefing at RUN_TIME_ET
                             #   • intraday polling during market hours with
                             #     alerts on regime/DEX/wall shifts + proximity
                             #     to top GEX walls
                             #   • closing summary at LIVE_MODE_END
                             #   • sleeps overnight, idle on weekends
    python run.py --live     # ad-hoc intraday polling only (no morning/close)

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
# Per-ticker analysis (shared by all modes)
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
        "unified_levels": unified_levels,
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
# Shared helpers (used by both --serve unified mode and --live)
# --------------------------------------------------------------------------- #
def _parse_hhmm(s: str):
    h, m = s.split(":")
    return int(h), int(m)


def _top_wall_strike(gex_levels: list):
    if not gex_levels:
        return None
    biggest = max(gex_levels, key=lambda l: abs(l.get("gex", 0.0)))
    return biggest["strike"]


def _detect_shifts(baseline: dict, current: dict) -> list:
    """Regime flip / DEX swing / top-wall move alerts."""
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


def _detect_proximity(current: dict):
    """Alert when spot enters the proximity band of a top GEX wall.
    Returns list of (key, text) tuples."""
    spot = current["spot"]
    walls = current.get("gex_levels", [])[:3]   # top 3 most important
    band = spot * settings.PROXIMITY_PCT
    out = []
    for w in walls:
        strike = w.get("strike")
        if strike is None:
            continue
        if abs(spot - strike) <= band:
            polarity = w.get("polarity", "wall")
            side_word = "below" if spot < strike else "above"
            txt = (f"Near {polarity} wall {strike:.0f} — spot {spot:.2f} "
                   f"({side_word}, {abs(spot - strike):.2f} away)")
            key = f"prox:{strike:.0f}"
            out.append((key, txt))
    return out


def _in_market_hours(now: dt.datetime) -> bool:
    open_h, open_m = _parse_hhmm(settings.LIVE_MODE_START)
    close_h, close_m = _parse_hhmm(settings.LIVE_MODE_END)
    if now.weekday() >= 5:
        return False
    o = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    c = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
    return o <= now <= c


def _next_run_time(now: dt.datetime) -> dt.datetime:
    """Next morning briefing time, skipping weekends."""
    hh, mm = _parse_hhmm(settings.RUN_TIME_ET)
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now >= target:
        target = target + dt.timedelta(days=1)
    while target.weekday() >= 5:
        target = target + dt.timedelta(days=1)
    return target


# --------------------------------------------------------------------------- #
# Mode 2 — UNIFIED daemon (this is what Railway runs)
# --------------------------------------------------------------------------- #
def send_morning_briefing(data, state):
    print(f"\n########## MORNING BRIEFING — "
          f"{dt.datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')} ##########\n")
    for ticker in settings.TICKERS:
        try:
            r = analyze_ticker(data, ticker)
        except Exception as e:  # noqa: BLE001
            print(f"[morning] {ticker} ERROR: {e}")
            traceback.print_exc()
            pushover.send(f"Peachy {ticker} ERROR", str(e))
            continue
        state["baselines"][ticker] = r
        if settings.PRINT_TO_TERMINAL:
            print(r["full"])
            print()
        pushover.send(f"Peachy {ticker} — {r['grade']['grade']}", r["push"])


def poll_intraday(data, state, now: dt.datetime):
    ts = now.strftime("%H:%M ET")
    for ticker in settings.TICKERS:
        base = state["baselines"].get(ticker)
        try:
            curr = analyze_ticker(data, ticker)
        except Exception as e:  # noqa: BLE001
            print(f"[poll] {ticker} ERROR: {e}")
            continue

        if base is None:
            state["baselines"][ticker] = curr
            base = curr

        # 1) Material exposure shifts
        shifts = _detect_shifts(base, curr)
        for alert in shifts:
            if alert in state["fired_alerts"][ticker]:
                continue
            state["fired_alerts"][ticker].add(alert)
            msg = (f"{ticker} EXPOSURE SHIFT - {ts}\n{alert}\n"
                   f"Action: prior setup may be invalid. Reassess.")
            print(msg)
            pushover.send(f"Peachy {ticker} SHIFT", msg)

        # 2) Proximity to top walls
        prox = _detect_proximity(curr)
        for key, text in prox:
            if key in state["fired_proximity"][ticker]:
                continue
            state["fired_proximity"][ticker].add(key)
            msg = f"{ticker} NEAR LEVEL - {ts}\n{text}"
            print(msg)
            pushover.send(f"Peachy {ticker} NEAR", msg)

        if not shifts and not prox and settings.PRINT_TO_TERMINAL:
            print(f"[poll] {ts} {ticker}: no material change.")


def send_closing_summary(data, state):
    """Brief end-of-day recap per ticker."""
    print(f"\n########## CLOSING SUMMARY — "
          f"{dt.datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')} ##########\n")
    for ticker in settings.TICKERS:
        base = state["baselines"].get(ticker)
        try:
            curr = analyze_ticker(data, ticker)
        except Exception as e:  # noqa: BLE001
            pushover.send(f"Peachy {ticker} CLOSE ERROR", str(e))
            continue

        spot = curr["spot"]
        base_spot = base["spot"] if base else spot
        change = spot - base_spot
        pct = (change / base_spot * 100.0) if base_spot else 0.0

        lines = [
            f"{ticker} CLOSE {spot:.2f}  ({change:+.2f}, {pct:+.2f}%)",
            f"Gamma: was {base['gamma']['regime'] if base else '?'} "
            f"-> now {curr['gamma']['regime']}",
        ]
        if base:
            lines.append(
                f"Morning bias was {base['direction']['direction']} "
                f"({base['setup']['setup']}, Grade {base['grade']['grade']})"
            )
            action = base["setup"].get("action_level")
            target = base["setup"].get("target_level")
            side = base["setup"].get("side")
            if action and side:
                took = ((side == "long" and spot > action["price"]) or
                        (side == "short" and spot < action["price"]))
                lines.append(f"Action {action['price']:.2f}: "
                             f"{'taken' if took else 'NOT taken'}")
            if target and side:
                hit = ((side == "long" and spot >= target["price"]) or
                       (side == "short" and spot <= target["price"]))
                lines.append(f"Target {target['price']:.2f}: "
                             f"{'HIT' if hit else 'not reached'}")

        msg = "\n".join(lines)
        if settings.PRINT_TO_TERMINAL:
            print(msg)
            print()
        pushover.send(f"Peachy {ticker} CLOSE", msg)


def _reset_state_for_day(state, today):
    state["day"] = today
    state["morning_sent"] = False
    state["closing_sent"] = False
    state["baselines"] = {}
    state["fired_alerts"] = {t: set() for t in settings.TICKERS}
    state["fired_proximity"] = {t: set() for t in settings.TICKERS}


def serve_forever():
    """Unified daemon. Morning briefing → intraday polling → closing summary
    → sleep overnight → repeat. Idle on weekends."""
    print(f"[serve] unified mode — morning briefing at {settings.RUN_TIME_ET} ET, "
          f"polling every {settings.POLL_INTERVAL_MINUTES} min during "
          f"{settings.LIVE_MODE_START}-{settings.LIVE_MODE_END} ET "
          f"(tickers: {', '.join(settings.TICKERS)}, "
          f"source: {settings.DATA_SOURCE})")

    state = {}
    _reset_state_for_day(state, None)
    data = make_data_client()

    if settings.RUN_ON_START:
        print("[serve] RUN_ON_START is true — firing morning briefing immediately.")
        try:
            send_morning_briefing(data, state)
            state["morning_sent"] = True
            state["day"] = dt.datetime.now(ET).date()
        except Exception:
            traceback.print_exc()

    poll_s = settings.POLL_INTERVAL_MINUTES * 60

    while True:
        now = dt.datetime.now(ET)
        today = now.date()

        if state["day"] != today:
            _reset_state_for_day(state, today)

        # Weekends: long sleep, but check back hourly so DST/manual restarts
        # don't desync us.
        if now.weekday() >= 5:
            print(f"[serve] {now.strftime('%a %H:%M ET')} weekend — sleeping 1h.")
            time.sleep(3600)
            continue

        morning_h, morning_m = _parse_hhmm(settings.RUN_TIME_ET)
        close_h, close_m = _parse_hhmm(settings.LIVE_MODE_END)
        morning_t = now.replace(hour=morning_h, minute=morning_m,
                                second=0, microsecond=0)
        close_t = now.replace(hour=close_h, minute=close_m,
                              second=0, microsecond=0)

        # Phase 1: morning briefing
        if now >= morning_t and not state["morning_sent"]:
            try:
                send_morning_briefing(data, state)
            except Exception:
                traceback.print_exc()
            state["morning_sent"] = True

        # Phase 2: intraday polling
        if state["morning_sent"] and _in_market_hours(now):
            try:
                poll_intraday(data, state, now)
            except Exception:
                traceback.print_exc()
            time.sleep(poll_s)
            continue

        # Phase 3: closing summary
        if state["morning_sent"] and now >= close_t and not state["closing_sent"]:
            try:
                send_closing_summary(data, state)
            except Exception:
                traceback.print_exc()
            state["closing_sent"] = True

        # Phase 4: sleep until next event
        target = None
        if now < morning_t:
            target = morning_t
        elif not state["morning_sent"]:
            target = now + dt.timedelta(seconds=60)
        elif not _in_market_hours(now) and now < close_t:
            # between morning and market open
            open_h, open_m = _parse_hhmm(settings.LIVE_MODE_START)
            target = now.replace(hour=open_h, minute=open_m,
                                 second=0, microsecond=0)
            if target <= now:
                target = now + dt.timedelta(seconds=60)
        else:
            # after close — sleep to tomorrow's morning
            target = _next_run_time(now)

        sleep_s = max(60, (target - now).total_seconds())
        chunk = min(sleep_s, 3600)
        wake_at = (now + dt.timedelta(seconds=chunk)).strftime("%H:%M ET")
        print(f"[serve] {now.strftime('%H:%M ET')} — sleeping "
              f"{chunk/60:.0f} min until ~{wake_at} "
              f"(target: {target.strftime('%Y-%m-%d %H:%M ET')})")
        time.sleep(chunk)


# --------------------------------------------------------------------------- #
# Mode 3 — ad-hoc live polling only
# --------------------------------------------------------------------------- #
def run_live_mode():
    """Ad-hoc intraday polling. Same poll/alert logic as --serve, but no
    morning briefing or closing summary. Use this for one-off live runs."""
    print(f"[live] starting intraday polling every "
          f"{settings.POLL_INTERVAL_MINUTES} min "
          f"({settings.LIVE_MODE_START}-{settings.LIVE_MODE_END} ET, "
          f"tickers: {', '.join(settings.TICKERS)}, "
          f"source: {settings.DATA_SOURCE})")

    data = make_data_client()
    state = {}
    _reset_state_for_day(state, dt.datetime.now(ET).date())

    # Baseline = run analysis once at startup, push as "BASELINE" notification
    for ticker in settings.TICKERS:
        try:
            r = analyze_ticker(data, ticker)
            state["baselines"][ticker] = r
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
        try:
            poll_intraday(data, state, now)
        except Exception:
            traceback.print_exc()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description="Peachy Engine")
    parser.add_argument("--serve", action="store_true",
                        help="Unified daemon (morning + intraday + close).")
    parser.add_argument("--live", action="store_true",
                        help="Ad-hoc intraday polling only.")
    args = parser.parse_args()

    if args.serve:
        serve_forever()
    elif args.live:
        run_live_mode()
    else:
        run_once()


if __name__ == "__main__":
    main()
