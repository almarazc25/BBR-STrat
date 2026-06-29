"""
PEACHY ENGINE — Environment classification + BBR setup selection + grading
=============================================================================
This is where exposures meet the actual strategy (Wall St Sophia's BBR:
Bounce / Break / Reject). The exposures DON'T replace BBR — they tell you
which of the three is high-probability today and which direction to favor.

LOGIC CHAIN
------------------------------------------------------------------------------
1. GAMMA regime (from net GEX) -> what KIND of day:
     positive gamma -> chop / mean reversion -> favor BOUNCE & REJECT,
                       expect failed breakouts, take profits quick
     negative gamma -> expansion / momentum  -> favor BREAK & continuation,
                       hold runners, breaks more likely to run
     near-zero      -> mixed -> A+ only / sit out

2. DIRECTION (from net DEX, confirmed by 200 EMA + pre-market structure):
     positive DEX + above 200 EMA + above PMH -> LONG bias
     negative DEX + below 200 EMA + below PML -> SHORT bias
     conflicting -> no clean direction

3. SETUP TYPE = gamma regime x direction:
     neg gamma + long  -> BREAK long (look to buy break of resistance wall)
     neg gamma + short -> BREAK short (look to short break of support wall)
     pos gamma + long  -> BOUNCE long (buy the bounce at support/demand)
     pos gamma + short -> REJECT short (short the reject at resistance/supply)

4. GRADE = weighted alignment of gamma + delta + vanna, then bumped by:
     + confluence at the actionable level (GEX wall + chart level)
     + trend agreement (200 EMA agrees with delta)
     + clean runway to the next level (>= MIN_REWARD_RISK)
   Grades: A+  (everything stacks)  /  A  /  B  /  C / NO-TRADE
=============================================================================
"""

from config import settings


# --------------------------------------------------------------------------- #
# Step 1 — gamma regime
# --------------------------------------------------------------------------- #
def classify_gamma(gex_result: dict) -> dict:
    net = gex_result["net_gex"]
    max_abs = gex_result["max_abs_strike_gex"] or 1.0
    band = settings.GEX_NEUTRAL_BAND * max_abs

    if abs(net) <= band:
        regime = "neutral"
    elif net > 0:
        regime = "positive"
    else:
        regime = "negative"

    descriptions = {
        "positive": "Positive gamma — chop / mean reversion. Expect failed "
                    "breakouts, rotation between levels, smaller moves. "
                    "Favor bounces & rejects, take profits quick.",
        "negative": "Negative gamma — expansion / momentum. Breaks more likely "
                    "to run, larger directional moves, trend-day potential. "
                    "Favor breaks & continuation, hold runners.",
        "neutral": "Neutral gamma — no clear behavioral edge. Market freer, "
                   "flows/news matter more. A+ only or sit out.",
    }
    return {"regime": regime, "net_gex": net, "description": descriptions[regime]}


# --------------------------------------------------------------------------- #
# Step 2 — direction
# --------------------------------------------------------------------------- #
def classify_direction(net_dex: float, structure: dict, spot: float,
                       max_abs_strike_gex: float) -> dict:
    """
    Combine the single most important directional read (delta) with the macro
    trend (200 EMA) and pre-market structure (PMH/PML) per the strategy docs.
    """
    # Scale the DEX neutral band off the same magnitude reference as GEX so we
    # don't need a separate hand-set dollar threshold.
    band = settings.DEX_NEUTRAL_BAND * (max_abs_strike_gex or 1.0)

    if abs(net_dex) <= band:
        dex_bias = "neutral"
    elif net_dex > 0:
        dex_bias = "long"
    else:
        dex_bias = "short"

    trend = structure["trend"]  # bullish / bearish (200 EMA vs spot)

    # Pre-market structure confirmation (Sophia: above PMH = continuation up).
    pm_bias = "neutral"
    if structure["pmh"] is not None and spot > structure["pmh"]:
        pm_bias = "long"
    elif structure["pml"] is not None and spot < structure["pml"]:
        pm_bias = "short"

    # Tally votes. Delta is weighted most heavily (it's the key directional read).
    votes = {"long": 0.0, "short": 0.0}
    if dex_bias == "long":
        votes["long"] += 2.0
    elif dex_bias == "short":
        votes["short"] += 2.0
    if trend == "bullish":
        votes["long"] += 1.0
    elif trend == "bearish":
        votes["short"] += 1.0
    if pm_bias == "long":
        votes["long"] += 1.0
    elif pm_bias == "short":
        votes["short"] += 1.0

    if votes["long"] == votes["short"]:
        direction = "neutral"
    else:
        direction = "long" if votes["long"] > votes["short"] else "short"

    # Conviction = how lopsided the vote was (0..1).
    total = votes["long"] + votes["short"]
    spread = abs(votes["long"] - votes["short"])
    conviction = (spread / total) if total > 0 else 0.0

    return {
        "direction": direction,
        "dex_bias": dex_bias,
        "trend": trend,
        "pm_bias": pm_bias,
        "conviction": conviction,
        "net_dex": net_dex,
    }


# --------------------------------------------------------------------------- #
# Step 3 — pick the BBR setup
# --------------------------------------------------------------------------- #
def select_setup(gamma: dict, direction: dict, levels: list, spot: float) -> dict:
    """
    Choose the BBR setup type and the actionable level + target.

    Returns:
        {
          "setup": "BREAK"|"BOUNCE"|"REJECT"|"NONE",
          "side": "long"|"short"|None,
          "action_level": {...} | None,
          "target_level": {...} | None,
          "trigger": str,        # the exact confirmation to watch for
          "narrative": str,
        }
    """
    regime = gamma["regime"]
    dir_ = direction["direction"]

    if regime == "neutral" or dir_ == "neutral":
        return {
            "setup": "NONE", "side": None,
            "action_level": None, "target_level": None,
            "trigger": "No clean setup. Stay flat until structure clears.",
            "narrative": "Mixed / unclear environment — no edge.",
        }

    # Split levels into those above and below spot.
    above = [l for l in levels if l["price"] > spot]
    below = [l for l in levels if l["price"] < spot]
    nearest_above = above[0] if above else None
    nearest_below = below[0] if below else None

    setup = side = action_level = target_level = None
    trigger = narrative = ""

    if regime == "negative":
        # Expansion day -> BREAK / continuation.
        setup = "BREAK"
        side = dir_
        if dir_ == "long":
            action_level = nearest_above   # break resistance wall upward
            target_level = above[1] if len(above) > 1 else None
            trigger = (f"5-min displacement candle CLOSE above "
                       f"{_p(action_level)} (strong body, close in top 1/3), "
                       f"then a clean retest that holds. Enter on the retest hold.")
        else:
            action_level = nearest_below   # break support wall downward
            target_level = below[1] if len(below) > 1 else None
            trigger = (f"5-min displacement candle CLOSE below "
                       f"{_p(action_level)} (strong body, close in bottom 1/3), "
                       f"then a clean retest that rejects. Enter on the retest.")
        narrative = ("Negative gamma supports follow-through, so a confirmed "
                     "break is the high-probability play. Hold runners; don't "
                     "take profits too early.")

    else:  # positive gamma -> BOUNCE / REJECT (fade extremes at levels)
        if dir_ == "long":
            setup = "BOUNCE"
            side = "long"
            action_level = nearest_below   # buy the bounce at support/demand
            target_level = nearest_above
            trigger = (f"Price taps {_p(action_level)} and forms a "
                       f"confirming 5-min candle (strong rejection wick down + "
                       f"close back up, body in top 1/3). Enter on that close.")
            narrative = ("Positive gamma favors mean reversion, so buying the "
                         "bounce at support is the high-probability play. "
                         "Take profits quick at the next level — expect "
                         "failed breakouts beyond it.")
        else:
            setup = "REJECT"
            side = "short"
            action_level = nearest_above   # short the reject at resistance/supply
            target_level = nearest_below
            trigger = (f"Price taps {_p(action_level)} and forms a "
                       f"confirming 5-min candle (sharp rejection wick up + "
                       f"close back down, body in bottom 1/3). Enter on that close.")
            narrative = ("Positive gamma favors mean reversion, so shorting the "
                         "reject at resistance is the high-probability play. "
                         "Take profits quick — expect failed breakdowns below.")

    return {
        "setup": setup, "side": side,
        "action_level": action_level, "target_level": target_level,
        "trigger": trigger, "narrative": narrative,
    }


# --------------------------------------------------------------------------- #
# Step 4 — grade the day
# --------------------------------------------------------------------------- #
def grade_setup(gamma: dict, direction: dict, vanna_proxy: float,
                setup: dict, spot: float) -> dict:
    """
    Weighted alignment score -> letter grade, with structure bumps.
    """
    if setup["setup"] == "NONE":
        return {"grade": "NO-TRADE", "score": 0.0,
                "reasons": ["Mixed / unclear environment."]}

    score = 0.0
    reasons = []

    # --- Gamma component: does the regime clearly support the chosen setup? ---
    if gamma["regime"] in ("positive", "negative"):
        score += settings.WEIGHT_GAMMA
        reasons.append(f"Gamma regime clear ({gamma['regime']}).")

    # --- Delta component: scaled by directional conviction. ---
    score += settings.WEIGHT_DELTA * direction["conviction"]
    if direction["conviction"] >= 0.6:
        reasons.append("Strong directional conviction (delta + trend + PM agree).")
    elif direction["conviction"] > 0:
        reasons.append("Some directional conviction.")

    # --- Vanna component: light. Agrees with direction? ---
    vanna_dir = "long" if vanna_proxy >= 0 else "short"
    if vanna_dir == direction["direction"]:
        score += settings.WEIGHT_VANNA
        reasons.append("Vanna context agrees with direction.")

    # --- Structure bumps (each nudges the grade up) ---
    bumps = 0.0

    al = setup["action_level"]
    if al and al.get("is_confluent"):
        bumps += 0.10
        reasons.append(f"Confluence at action level ({', '.join(al['sources'])}).")

    if direction["trend"] == ("bullish" if direction["direction"] == "long"
                              else "bearish"):
        bumps += 0.05
        reasons.append("200 EMA trend agrees with direction.")

    # Clean runway: action -> target distance >= MIN_REWARD_RISK * (a unit).
    tl = setup["target_level"]
    if al and tl:
        runway = abs(tl["price"] - al["price"])
        # Use distance from spot to action level as the rough risk unit.
        risk_unit = max(abs(spot - al["price"]), 0.25)
        rr = runway / risk_unit
        if rr >= settings.MIN_REWARD_RISK:
            bumps += 0.05
            reasons.append(f"Clean runway to target (~{rr:.1f}:1 R:R).")
        else:
            reasons.append(f"Tight runway to target (~{rr:.1f}:1) — watch R:R.")
    else:
        reasons.append("No clear next target — manage actively / scale out.")

    score = min(score + bumps, 1.10)

    # --- Map score -> letter ---
    if score >= 1.0:
        grade = "A+"
    elif score >= 0.85:
        grade = "A"
    elif score >= 0.6:
        grade = "B"
    elif score >= 0.4:
        grade = "C"
    else:
        grade = "NO-TRADE"

    return {"grade": grade, "score": score, "reasons": reasons}


def recommend_contract(setup: dict, gamma: dict, grade: dict) -> dict:
    """Pick a DTE range + strike preference based on setup, gamma regime,
    and grade.

    The single most common loss pattern in this strategy is being on 0-1
    DTE during a BREAK setup — the move needs time to play out (initial
    break, retracement, retest, hold, push) and theta eats you alive
    during the retest wait. The fix is to give BREAKs more time.

    BOUNCE / REJECT are mean-reversion plays — moves happen fast, theta
    matters less, so 0-2 DTE is fine and lets you keep more leverage.

    Grade tiers within each setup family:
        A+   → can be aggressive on DTE (move is most likely to work)
        A    → standard DTE range
        B    → conservative DTE (give yourself room to be wrong on timing)
    """
    if setup.get("setup") == "NONE":
        return None

    setup_type = setup["setup"]
    grade_letter = grade.get("grade", "B")

    if setup_type == "BREAK":
        if grade_letter == "A+":
            dte_range, dte_pref = "1-3 DTE", "2 DTE"
        elif grade_letter == "A":
            dte_range, dte_pref = "2-4 DTE", "2-3 DTE"
        else:
            dte_range, dte_pref = "3-5 DTE", "3-4 DTE"
        rationale = ("Breaks need TIME. Theta on 0-1 DTE eats you during "
                     "the retest wait — you stop out before the move plays.")
    elif setup_type in ("BOUNCE", "REJECT"):
        if grade_letter == "A+":
            dte_range, dte_pref = "0-2 DTE", "0-1 DTE"
        elif grade_letter == "A":
            dte_range, dte_pref = "1-3 DTE", "1-2 DTE"
        else:
            dte_range, dte_pref = "2-4 DTE", "2-3 DTE"
        rationale = ("Reversion plays move fast. 0-2 DTE captures the snap "
                     "without paying for time you don't need.")
    else:
        return None

    # Strike selection — Sophia's standard. OTM gives more leverage on
    # BREAKs (where price is expected to keep running). ATM is safer on
    # BOUNCE/REJECT where the move can be smaller.
    if setup_type == "BREAK":
        strike_pref = "ATM or 1 strike OTM (OTM for more leverage on runners)"
    else:
        strike_pref = "ATM (cleaner delta on a smaller move)"

    return {
        "dte_range": dte_range,
        "dte_preferred": dte_pref,
        "strike": strike_pref,
        "rationale": rationale,
    }


def _p(level):
    if not level:
        return "—"
    return f"{level['price']:.2f}"
