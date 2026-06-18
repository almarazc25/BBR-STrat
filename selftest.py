"""
PEACHY ENGINE — Offline self-test
=============================================================================
Validates the math and the full decision pipeline WITHOUT needing Schwab.
It builds two synthetic option chains:

  Scenario A: NEGATIVE gamma + bullish delta  -> should yield a BREAK LONG
  Scenario B: POSITIVE gamma + bearish delta  -> should yield a REJECT SHORT

Run:  python selftest.py
=============================================================================
"""

import datetime as dt
from zoneinfo import ZoneInfo

from core import exposures, levels as levels_mod, environment, briefing

ET = ZoneInfo("America/New_York")


def make_chain(spot, gamma_sign_bias, delta_bias):
    """
    Build a synthetic chain around `spot`.
    gamma_sign_bias: 'neg' loads call gamma (dealers short calls -> net neg GEX)
                     'pos' loads put gamma  (dealers long puts  -> net pos GEX)
    delta_bias:      'long' or 'short' tilts net DEX.
    """
    contracts = []
    strikes = [round(spot + s, 0) for s in range(-8, 9, 2)]  # 9 strikes, $2 apart
    for k in strikes:
        # Base greeks (toy values; magnitudes are what matter for signs).
        gamma = 0.03
        vega = 0.10
        # Call delta positive, put delta negative.
        call_delta = 0.45
        put_delta = -0.45

        # OI distribution: pile OI to create walls + the desired gamma sign.
        if gamma_sign_bias == "neg":
            call_oi = 9000 if k == spot + 4 else 2500   # big call wall above
            put_oi = 1500
        else:  # pos gamma -> heavy puts
            call_oi = 1500
            put_oi = 9000 if k == spot - 4 else 2500    # big put wall below

        # Direction tilt via extra delta-weighted OI.
        if delta_bias == "long":
            call_oi += 1500
        else:
            put_oi += 1500

        contracts.append({"strike": k, "type": "C", "expiry": "2026-06-18",
                          "dte": 0, "oi": call_oi, "volume": 100,
                          "gamma": gamma, "delta": call_delta, "vega": vega,
                          "theta": -0.1, "iv": 18.0})
        contracts.append({"strike": k, "type": "P", "expiry": "2026-06-18",
                          "dte": 0, "oi": put_oi, "volume": 100,
                          "gamma": gamma, "delta": put_delta, "vega": vega,
                          "theta": -0.1, "iv": 18.0})
    return {"spot": spot, "contracts": contracts}


def make_candles(spot, trend):
    """
    Synthetic 5-min candles ending near `spot`, with a 200-EMA that sits
    BELOW spot for a bullish trend (price above EMA) and ABOVE spot for a
    bearish trend (price below EMA). Also lays down a clean prev-day session
    and a pre-market range so PDH/PDL/PMH/PML resolve.
    """
    candles = []
    t = dt.datetime(2026, 6, 16, 4, 0, tzinfo=ET)

    # Build a gentle ramp that ends at ~spot. Bullish ramps UP into spot
    # (so the trailing average is below); bearish ramps DOWN into spot.
    n = 460
    if trend == "bullish":
        start = spot - 12.0
    else:
        start = spot + 12.0
    span = spot - start
    for i in range(n):
        frac = i / (n - 1)
        price = start + span * frac
        o = price - (span / n) * 0.5
        h = max(o, price) + 0.15
        lo = min(o, price) - 0.15
        candles.append({"datetime": t, "open": o, "high": h, "low": lo,
                        "close": price, "volume": 1000})
        # advance 5 min; jump to next day's pre-market after ~the prior close
        t = t + dt.timedelta(minutes=5)

    # Re-stamp the last ~60 candles as "today" starting at pre-market 04:00,
    # so compute_structure sees a distinct current day with a PM range + open.
    today_start = dt.datetime(2026, 6, 17, 4, 0, tzinfo=ET)
    tail = candles[-60:]
    tt = today_start
    for c in tail:
        c["datetime"] = tt
        tt = tt + dt.timedelta(minutes=5)

    return candles


def run_scenario(name, spot, gamma_bias, delta_bias, trend):
    print("\n" + "#" * 64)
    print(f"# SCENARIO {name}: gamma={gamma_bias}, delta={delta_bias}, trend={trend}")
    print("#" * 64)

    chain = make_chain(spot, gamma_bias, delta_bias)
    candles = make_candles(spot, trend)

    gex = exposures.compute_gex_by_strike(chain)
    net_dex = exposures.compute_net_dex(chain)
    vanna_proxy = exposures.compute_vanna_proxy(chain)
    gex_levels = exposures.top_gex_levels(gex)

    structure = levels_mod.compute_structure(candles, spot)
    unified = levels_mod.find_confluence(gex_levels, structure["chart_levels"], spot)

    gamma = environment.classify_gamma(gex)
    direction = environment.classify_direction(
        net_dex, structure, spot, gex["max_abs_strike_gex"])
    setup = environment.select_setup(gamma, direction, unified, spot)
    grade = environment.grade_setup(gamma, direction, vanna_proxy, setup, spot)

    print(f"net_gex={gex['net_gex']:.0f}  net_dex={net_dex:.0f}  "
          f"vanna={vanna_proxy:.0f}")
    print(f"gamma regime: {gamma['regime']}")
    print(f"direction: {direction['direction']} "
          f"(conviction {direction['conviction']:.2f})")
    print(f"setup: {setup['setup']} {setup['side']}")
    print(f"grade: {grade['grade']}")
    print()
    print(briefing.build_full(f"TEST{name}", spot, gamma, direction, setup,
                              grade, unified, structure, vanna_proxy))
    print("\n--- PHONE PUSH VERSION ---")
    print(briefing.build_push(f"TEST{name}", spot, gamma, direction, setup, grade))

    return gamma, direction, setup, grade


if __name__ == "__main__":
    # Scenario A: negative gamma + bullish -> expect BREAK LONG
    gA, dA, sA, grA = run_scenario("A", 600.0, "neg", "long", "bullish")
    # Scenario B: positive gamma + bearish -> expect REJECT SHORT
    gB, dB, sB, grB = run_scenario("B", 600.0, "pos", "short", "bearish")

    print("\n" + "=" * 64)
    print("ASSERTIONS")
    print("=" * 64)
    ok = True

    def check(label, cond):
        global ok
        status = "PASS" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{status}] {label}")

    check("A: gamma regime negative", gA["regime"] == "negative")
    check("A: direction long", dA["direction"] == "long")
    check("A: setup is BREAK long", sA["setup"] == "BREAK" and sA["side"] == "long")
    check("A: action level is above spot", sA["action_level"]["price"] > 600.0)

    check("B: gamma regime positive", gB["regime"] == "positive")
    check("B: direction short", dB["direction"] == "short")
    check("B: setup is REJECT short", sB["setup"] == "REJECT" and sB["side"] == "short")
    check("B: action level is above spot (resistance to short)",
          sB["action_level"]["price"] > 600.0)

    print("\nRESULT:", "ALL PASS" if ok else "SOME FAILED")
