"""
PEACHY ENGINE — Briefing assembler
=============================================================================
Turns the analysis into the exact notification you wanted: short, actionable,
tells you HOW you're looking to go in, WHERE, what to WATCH FOR to confirm,
and how to MANAGE it. One briefing per ticker.

Two formats:
    build_full(...)   -> the complete terminal/log version
    build_push(...)   -> a tighter version sized for a phone notification
=============================================================================
"""

from config import settings


def _fmt_level(level):
    if not level:
        return "—"
    src = ", ".join(level["sources"]) if level.get("sources") else ""
    conf = "  [CONFLUENCE]" if level.get("is_confluent") else ""
    if src:
        return f"{level['price']:.2f} ({src}){conf}"
    return f"{level['price']:.2f}{conf}"


def _direction_word(side):
    return {"long": "LONG / calls", "short": "SHORT / puts"}.get(side, "—")


def build_full(ticker, spot, gamma, direction, setup, grade, levels,
               structure, vanna_proxy):
    L = []
    L.append("=" * 60)
    if setup["setup"] == "NONE":
        L.append(f"{ticker} — NO TRADE  (Grade: {grade['grade']})")
    else:
        L.append(f"{ticker} — {direction['direction'].upper()} "
                 f"{setup['setup']} DAY  (Grade: {grade['grade']})")
    L.append("=" * 60)
    L.append(f"Spot: {spot:.2f}")
    L.append("")

    # Environment
    L.append("ENVIRONMENT")
    L.append(f"  {gamma['description']}")
    L.append("")

    if setup["setup"] == "NONE":
        L.append("READ")
        L.append("  No clean exposure + direction alignment. Best trade is no "
                 "trade. Wait for structure to clear or for an A+ to form.")
        L.append("=" * 60)
        return "\n".join(L)

    # Bias
    L.append("BIAS")
    L.append(f"  Direction: {_direction_word(setup['side'])}")
    L.append(f"  Why: delta {direction['dex_bias']}, "
             f"trend {direction['trend']} (200 EMA), "
             f"pre-market {direction['pm_bias']}.")
    L.append("")

    # The play
    L.append("THE PLAY")
    L.append(f"  Setup type: {setup['setup']}")
    L.append(f"  Action level: {_fmt_level(setup['action_level'])}")
    L.append(f"  Target: {_fmt_level(setup['target_level'])}")
    L.append(f"  {setup['narrative']}")
    L.append("")

    # Entry confirmation
    L.append("ENTRY CONFIRMATION (what to watch for)")
    L.append(f"  {setup['trigger']}")
    L.append(f"  Rule: must be a {settings.CONFIRMATION_TIMEFRAME_MIN}-min "
             f"candle CLOSE (not a wick). No close = no entry.")
    L.append("")

    # Management
    L.append("MANAGEMENT")
    if setup["action_level"]:
        if setup["side"] == "long":
            stop_note = f"below {setup['action_level']['price']:.2f}"
        else:
            stop_note = f"above {setup['action_level']['price']:.2f}"
    else:
        stop_note = "beyond the action level"
    L.append(f"  Stop: structure {stop_note} "
             f"(or {int(settings.DEFAULT_STOP_PCT*100)}% on the contract).")
    if gamma["regime"] == "positive":
        L.append("  Positive gamma -> scale out fast, smaller targets, don't "
                 "expect a trend day.")
    else:
        L.append("  Negative gamma -> let runners work, larger targets, "
                 "don't take profits too early.")
    # Contract recommendation — DTE picked from setup/regime/grade.
    from core.environment import recommend_contract
    contract = recommend_contract(setup, gamma, grade)
    if contract:
        L.append(f"  Contract: {contract['strike']}")
        L.append(f"  DTE: {contract['dte_preferred']}  "
                 f"(range {contract['dte_range']})")
        L.append(f"  Why this DTE: {contract['rationale']}")
    else:
        L.append("  Contract: ATM or 1 strike OTM, 1-3 DTE, liquid + tight spread.")
    L.append("")

    # Grade reasons
    L.append(f"GRADE: {grade['grade']}  (score {grade['score']:.2f})")
    for r in grade["reasons"]:
        L.append(f"  - {r}")
    L.append("")

    # Level map
    L.append("KEY LEVELS (nearest first)")
    for lv in levels[:6]:
        tag = "  [CONFLUENCE]" if lv["is_confluent"] else ""
        gx = ""
        if lv.get("gex") is not None:
            gx = f"  GEX {lv['gex']/1e6:+.1f}M"
        L.append(f"  {lv['side']:>5}  {lv['price']:.2f}  "
                 f"{', '.join(lv['sources'])}{gx}{tag}")
    L.append("=" * 60)
    return "\n".join(L)


def build_push(ticker, spot, gamma, direction, setup, grade):
    """Tighter version for the phone. Still has everything you act on."""
    if setup["setup"] == "NONE":
        return (f"{ticker}: NO TRADE ({grade['grade']})\n"
                f"{gamma['regime']} gamma, no clean direction. Sit out.")

    al = setup["action_level"]
    tl = setup["target_level"]
    al_s = f"{al['price']:.2f}" if al else "—"
    tl_s = f"{tl['price']:.2f}" if tl else "—"
    conf = " [CONF]" if (al and al.get("is_confluent")) else ""

    side = "LONG/calls" if setup["side"] == "long" else "SHORT/puts"
    manage = ("scale out fast" if gamma["regime"] == "positive"
              else "hold runners")

    from core.environment import recommend_contract
    contract = recommend_contract(setup, gamma, grade)
    contract_line = (f"Use {contract['dte_preferred']} · {contract['strike']}"
                     if contract else
                     "ATM or 1 strike OTM, 1-3 DTE")
    lines = [
        f"{ticker} — {setup['setup']} {side} (Grade {grade['grade']})",
        f"Spot {spot:.2f} | {gamma['regime']} gamma",
        f"Action: {al_s}{conf}  Target: {tl_s}",
        f"Enter: {setup['trigger']}",
        f"Manage: stop beyond {al_s}, {manage}.",
        contract_line,
    ]
    return "\n".join(lines)
