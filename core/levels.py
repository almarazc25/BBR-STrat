"""
PEACHY ENGINE — Chart structure levels
=============================================================================
Computes the price-action levels Sophia marks every day, then stacks them
against the GEX walls to find CONFLUENCE (the highest-probability zones).

Levels produced:
    - 200 EMA on the structure timeframe -> macro trend filter
      (price above = bullish bias, below = bearish bias)
    - Previous day high / low (PDH / PDL)
    - Pre-market high / low (PMH / PML) for today
    - Confluence zones: GEX wall within CONFLUENCE_TOLERANCE of a chart level
=============================================================================
"""

import datetime as dt
from zoneinfo import ZoneInfo

from config import settings

ET = ZoneInfo("America/New_York")


def ema(values, length):
    """Standard EMA. Returns the final EMA value (most recent)."""
    if not values:
        return None
    if len(values) < length:
        length = len(values)
    k = 2.0 / (length + 1.0)
    ema_val = values[0]
    for v in values[1:]:
        ema_val = v * k + ema_val * (1.0 - k)
    return ema_val


def _parse_hhmm(s):
    h, m = s.split(":")
    return int(h), int(m)


def compute_structure(candles: list, spot: float) -> dict:
    """
    candles: list of 5-min candles (ET), oldest -> newest, with extended hours.

    Returns:
        {
          "ema200": float,
          "trend": "bullish" | "bearish",
          "pdh": float, "pdl": float,
          "pmh": float|None, "pml": float|None,
          "chart_levels": [ {name, price}, ... ]
        }
    """
    closes = [c["close"] for c in candles]
    ema200 = ema(closes, settings.TREND_EMA_LENGTH)
    trend = "bullish" if (ema200 is not None and spot >= ema200) else "bearish"

    # Group candles by ET calendar date.
    by_day = {}
    for c in candles:
        d = c["datetime"].date()
        by_day.setdefault(d, []).append(c)

    days_sorted = sorted(by_day.keys())
    today = days_sorted[-1] if days_sorted else None

    # ---- Previous day's REGULAR-session high/low ----
    pdh = pdl = None
    if len(days_sorted) >= 2:
        prev_day = days_sorted[-2]
        oh, om = _parse_hhmm(settings.SESSION_OPEN_ET)
        ch, cm = _parse_hhmm(settings.SESSION_CLOSE_ET)
        sess = [
            c for c in by_day[prev_day]
            if (c["datetime"].hour, c["datetime"].minute) >= (oh, om)
            and (c["datetime"].hour, c["datetime"].minute) < (ch, cm)
        ]
        if sess:
            pdh = max(c["high"] for c in sess)
            pdl = min(c["low"] for c in sess)

    # ---- Today's PRE-MARKET high/low (04:00 ET -> open) ----
    pmh = pml = None
    if today is not None:
        ph, pm = _parse_hhmm(settings.PREMARKET_OPEN_ET)
        oh, om = _parse_hhmm(settings.SESSION_OPEN_ET)
        pre = [
            c for c in by_day[today]
            if (c["datetime"].hour, c["datetime"].minute) >= (ph, pm)
            and (c["datetime"].hour, c["datetime"].minute) < (oh, om)
        ]
        if pre:
            pmh = max(c["high"] for c in pre)
            pml = min(c["low"] for c in pre)

    chart_levels = []
    if pmh is not None:
        chart_levels.append({"name": "PMH", "price": pmh})
    if pml is not None:
        chart_levels.append({"name": "PML", "price": pml})
    if pdh is not None:
        chart_levels.append({"name": "PDH", "price": pdh})
    if pdl is not None:
        chart_levels.append({"name": "PDL", "price": pdl})

    return {
        "ema200": ema200,
        "trend": trend,
        "pdh": pdh, "pdl": pdl,
        "pmh": pmh, "pml": pml,
        "chart_levels": chart_levels,
    }


def find_confluence(gex_levels: list, chart_levels: list, spot: float):
    """
    Match GEX walls to chart levels. When a GEX wall sits within
    CONFLUENCE_TOLERANCE dollars of a chart level, that's a stacked,
    high-probability zone.

    Returns a unified, de-duplicated level list, each annotated with:
        price, sources (list), is_confluent (bool), side (above/below spot),
        gex (if applicable), polarity (if applicable)
    Sorted by distance from spot (nearest first).
    """
    tol = settings.CONFLUENCE_TOLERANCE
    unified = []

    # Seed with GEX walls.
    for g in gex_levels:
        unified.append({
            "price": g["strike"],
            "sources": [f"GEX wall ({g['polarity']})"],
            "is_confluent": False,
            "side": g["side"],
            "gex": g["gex"],
            "polarity": g["polarity"],
        })

    # Fold in chart levels, merging when close to an existing GEX wall.
    for ch in chart_levels:
        merged = False
        for u in unified:
            if abs(u["price"] - ch["price"]) <= tol:
                u["sources"].append(ch["name"])
                u["is_confluent"] = True
                merged = True
                break
        if not merged:
            unified.append({
                "price": ch["price"],
                "sources": [ch["name"]],
                "is_confluent": False,
                "side": "above" if ch["price"] >= spot else "below",
                "gex": None,
                "polarity": None,
            })

    unified.sort(key=lambda x: abs(x["price"] - spot))
    return unified
