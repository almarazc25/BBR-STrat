"""
PEACHY ENGINE — Exposure calculations
=============================================================================
Turns a raw option chain into dealer exposure: GEX (gamma), DEX (delta), and
a vanna proxy. Everything is computed from the DEALER's perspective, because
that's whose hedging actually moves price.

DEALER POSITIONING MODEL
------------------------------------------------------------------------------
Standard convention (DEALERS_SHORT_CALLS = True):
    - Dealers are net SHORT calls  -> they are SHORT call gamma
    - Dealers are net LONG puts     -> they are LONG put gamma
Gamma is always positive per-contract, so to express *dealer* gamma:
    call contribution = -1 * gamma * OI * mult * spot^2 * 0.01
    put  contribution = +1 * gamma * OI * mult * spot^2 * 0.01
Net positive  -> "positive gamma" regime (dealers buy dips / sell rips
                 -> mean reversion, chop, pins, failed breakouts).
Net negative  -> "negative gamma" regime (dealers chase price
                 -> expansion, momentum, trend days, clean breaks).

The spot^2 * 0.01 term converts raw gamma into "$ of hedging per 1% move",
the standard way GEX is normalized so levels are comparable across strikes.

DELTA EXPOSURE (DEX)
------------------------------------------------------------------------------
Read as DIRECTIONAL positioning, matching the cheat sheet's stated meaning:
    positive DEX -> bullish positioning -> easier path HIGHER
    negative DEX -> bearish positioning -> easier path LOWER
Computed as OI-weighted option delta summed directly (calls push it positive,
puts push it negative). Per Sophia: delta is the single most important
DIRECTIONAL exposure.

VANNA (proxy)
------------------------------------------------------------------------------
Schwab doesn't return vanna directly, so we approximate it. Vanna ~ how delta
changes as IV changes, which is well-proxied by vega-weighted positioning
skewed by moneyness. We use a vega * (distance-from-spot sign) proxy. This is
deliberately LIGHT — vanna is only context in this strategy, never an entry
reason, and charm is omitted entirely by design.
=============================================================================
"""

from config import settings


def _dealer_sign(opt_type: str) -> int:
    """+1 or -1 multiplier applied to a long-holder greek to get dealer side."""
    if not settings.DEALERS_SHORT_CALLS:
        return 1
    # Dealer is short calls (-1 on call gamma) and long puts (+1 on put gamma).
    return -1 if opt_type == "C" else 1


def compute_gex_by_strike(chain: dict) -> dict:
    """
    Net dealer gamma exposure per strike (summed across the kept expirations).

    Returns:
        {
          "spot": float,
          "by_strike": { strike: net_gex_dollars, ... },
          "net_gex": float,                 # total across all strikes
          "max_abs_strike_gex": float,      # largest |GEX| at any single strike
        }
    """
    spot = chain["spot"]
    mult = settings.CONTRACT_MULTIPLIER
    by_strike = {}

    for c in chain["contracts"]:
        if c["gamma"] == 0 or c["oi"] == 0:
            continue
        sign = _dealer_sign(c["type"])
        # $ gamma per 1% move:
        gex = sign * c["gamma"] * c["oi"] * mult * (spot ** 2) * 0.01
        by_strike[c["strike"]] = by_strike.get(c["strike"], 0.0) + gex

    net_gex = sum(by_strike.values())
    max_abs = max((abs(v) for v in by_strike.values()), default=0.0)
    return {
        "spot": spot,
        "by_strike": by_strike,
        "net_gex": net_gex,
        "max_abs_strike_gex": max_abs,
    }


def compute_net_dex(chain: dict) -> float:
    """
    Net delta exposure as a DIRECTIONAL read, matching the framework's stated
    meaning:  positive DEX -> bullish positioning / easier path HIGHER;
              negative DEX -> bearish positioning / easier path LOWER.

    The cheat sheet defines it from the trader/positioning side, not the
    dealer-hedging side: "Positive Delta -> bullish dealer positioning ->
    supports upside." Heavy call positioning (positive option delta) should
    therefore read BULLISH, and heavy put positioning (negative option delta)
    should read BEARISH.

    So we sum the OI-weighted option delta directly (NOT dealer-flipped):
        call delta (+) * call OI  -> pushes DEX positive (bullish)
        put  delta (-) * put  OI  -> pushes DEX negative (bearish)
    """
    spot = chain["spot"]
    mult = settings.CONTRACT_MULTIPLIER
    total = 0.0
    for c in chain["contracts"]:
        if c["delta"] == 0 or c["oi"] == 0:
            continue
        total += c["delta"] * c["oi"] * mult * spot
    return total


def compute_vanna_proxy(chain: dict) -> float:
    """
    Light vanna proxy. Positive -> falling IV tends to support upside
    (bullish vanna); negative -> rising IV tends to support downside.

    Proxy: vega-weighted OI, signed by whether the strike sits above or below
    spot. Calls above spot + puts below spot dominate the vanna sign in the
    usual dealer book. This is intentionally coarse — context only.
    """
    spot = chain["spot"]
    total = 0.0
    for c in chain["contracts"]:
        if c["vega"] == 0 or c["oi"] == 0:
            continue
        moneyness_sign = 1 if c["strike"] >= spot else -1
        leg_sign = 1 if c["type"] == "C" else -1
        total += leg_sign * moneyness_sign * c["vega"] * c["oi"]
    return total


def top_gex_levels(gex_result: dict, n: int = None):
    """
    The n strikes with the largest ABSOLUTE gamma exposure. These are the
    'walls' — price magnets / reaction points. Returned sorted by proximity
    to spot so the nearest, most relevant ones lead.
    """
    if n is None:
        n = settings.TOP_N_GEX_LEVELS
    spot = gex_result["spot"]
    items = sorted(
        gex_result["by_strike"].items(),
        key=lambda kv: abs(kv[1]),
        reverse=True,
    )[:n]
    # Re-sort the chosen walls by distance from spot (nearest first).
    items.sort(key=lambda kv: abs(kv[0] - spot))
    return [
        {
            "strike": strike,
            "gex": gex,
            "side": "above" if strike >= spot else "below",
            "polarity": "positive" if gex >= 0 else "negative",
        }
        for strike, gex in items
    ]
