# MASTER CONTEXT PROMPT — PEACHY ENGINE + BBR INDICATOR
=============================================================================
PASTE THIS AT THE START OF ANY CLAUDE CODE SESSION working on this project.
It is the complete brain. A fresh Claude has NO memory of how this system
works — this document is how it knows. Read it fully before changing code.
=============================================================================

## WHO THIS IS FOR
Carlos — trades SPY and QQQ options (0DTE / 1DTE / 2DTE), plus futures
separately. The recurring problem this system solves: getting faked out by
price action and mistiming entries (especially stop-outs from volatility
right at candle close). The fix is a disciplined, exposure-aware, mechanical
read that removes in-the-moment human guesswork.

## WHAT THE WHOLE SYSTEM IS
Two pieces:

1. **The Engine** (this repo, Python). Runs pre-market. Pulls Schwab data,
   computes dealer exposures, finds key levels, classifies the environment,
   picks the BBR setup, grades it, and pushes a briefing to the phone. It says
   *what kind of day it is, which direction, where the levels are, what setup
   to look for, and what confirmation to wait for.*

2. **The Indicator** (TradingView, Pine Script v6 — built later). Lives on the
   chart during the session. Takes the engine's levels + chosen direction/
   setup as inputs, then watches live price action and only fires a
   confirmation signal when the mechanical entry rules are met. It is the
   *discipline enforcer* — it removes the "did it really confirm?" judgment.

The engine = WHERE and WHAT TYPE. The indicator = WHEN.

## THE TRADING STRATEGY (Wall St Sophia — source of truth)
Her core strategy is **BBR: Bounce, Break, Reject.** Stocks only do three
things at a level: bounce off support, reject resistance, or break through.

- **Bounce** — price taps support/demand and turns up. Enter long on a
  confirming candle. Stop just beyond the zone.
- **Reject** — price taps resistance/supply and turns down. Enter short on a
  confirming candle.
- **Break** — price closes through a level. DO NOT enter immediately. Wait for
  a clean break + retest, enter on the retest hold/rejection.

**Levels** = Support/Resistance (horizontal price memory) stacked with
Supply/Demand zones (imbalance areas with big candles). Confluence of S/R +
S/D = high probability. Mark PMH, PML, previous-day H/L every day.

**Trend filter:** 200 EMA. Above = bullish, below = bearish. (8/13/48 EMAs
also used by her but 200 is the macro filter we encode.)

**Entry confirmation (THE most important part, and the fix for the timing
problem):**
- Must be a **5-minute candle CLOSE**, never a wick.
- Must be a **displacement candle**: strong body (>= ~50% of range), closing
  in the **top 1/3** of its range (bullish) or **bottom 1/3** (bearish).
- Rejection strength scale: closed above prior candle's open AND within top
  1/3 of range = strong. (Mirror for bearish.)
- No close = no entry. This single rule is why Carlos was getting stopped out:
  he was acting on 1-min noise at candle close. Everything keys off the 5-min
  close.

**Management:**
- Stop = structure based (just beyond the level/zone), or -25% on the
  contract, whichever the trade structure dictates. She prefers structural
  stops over % for swings.
- Target = next clean level / next S-D zone, aim >= 2:1 R:R.
- Contract = ATM or 1 strike OTM, liquid, tight spread. 0DTE only on A+;
  otherwise 1-2 DTE for room (avoids theta/vol burn before the move).
- Don't trade through the middle of zones ("don't diddle in the middle") —
  chop zones are where you get chopped up.

## THE EXPOSURES LAYER (Peachy / QuantData framework — CONTEXT, not signals)
Exposures DON'T generate trades. They tell you which BBR setup is high
probability today and how to manage it. Four exposures, in priority order:

1. **GAMMA (net GEX) — most important behavioral read. "What kind of day?"**
   - Positive gamma → mean reversion, chop, pins, FAILED breakouts, smaller
     moves, price drawn to big levels. → Favor BOUNCE & REJECT. Take profits
     quick. Lower trend-day probability.
   - Negative gamma → expansion, momentum, larger moves, stronger
     follow-through, trend-day potential. → Favor BREAK & continuation. Hold
     runners.
   - Near zero → mixed; flows/news matter; A+ only or sit out.
   - Does NOT give direction.

2. **DELTA (net DEX) — most important DIRECTIONAL read. "Which way is easier?"**
   - Positive → bullish positioning, supports upside, long setups higher
     confidence.
   - Negative → bearish, supports downside, short setups higher confidence.
   - Supports the thesis; never the sole reason to enter.

3. **VANNA — light continuation context. "Will the move keep going?"**
   - Falling IV + positive vanna → supports upside continuation.
   - Rising IV + negative vanna → supports downside continuation.
   - Context only. Never an entry reason.

4. **CHARM — INTENTIONALLY OMITTED.** Sophia places little weight on it, and it
   changes throughout the day so it's a poor fit for a one-shot pre-market
   read. Do not add it back without a deliberate reason.

**Key levels from exposures:** the strikes with the largest absolute GEX are
"walls" — magnets / reaction points. When a GEX wall lines up with a chart
level (PMH/PML/PDH/PDL), that's confluence = highest probability zone.

**How to read price vs levels (from the QuantData guide):**
- Near a big exposure level → expect reaction / chop / pin.
- Between two big levels → expect range.
- Far from next big level → room to move.
- Levels stacked together → chop more likely. Spread out → cleaner moves.

## EXPOSURE PRIORITY SUMMARY (do not drift from this)
GEX (behavior) ≈ DELTA (direction) at the top, VANNA light context, CHARM
omitted. The engine weights are GAMMA 0.40 / DELTA 0.40 / VANNA 0.20. Don't
over-filter — too many required conditions = never trade. Core required
elements for a trade: clear gamma regime + clear direction + an actionable
level. Confluence/trend/runway are grade *bumps*, not gates.

## DEALER-POSITIONING MATH (the signs that make it all work)
Assume dealers are net SHORT calls and net LONG puts.
- **GEX per strike:** `sign * gamma * OI * 100 * spot^2 * 0.01`, where
  `sign = -1 for calls, +1 for puts`. Sum → net GEX. Net positive = positive
  gamma regime; net negative = negative gamma regime.
- **DEX (directional read):** sum `delta * OI * 100 * spot` using the option's
  own delta sign (calls +, puts -). Positive = bullish, negative = bearish.
  NOTE: this is the *directional/positioning* convention from the cheat sheet
  ("positive delta = bullish"), NOT the dealer-flip. Keep it this way.
- **Vanna proxy:** Schwab has no vanna; approximate with
  `leg_sign * moneyness_sign * vega * OI` summed. Coarse on purpose.
- Spot^2*0.01 converts gamma to "$ hedging per 1% move" (standard GEX
  normalization).

## SETUP SELECTION (gamma × direction → BBR)
- negative gamma + long  → **BREAK long** (buy break of nearest resistance
  wall above; target next wall above).
- negative gamma + short → **BREAK short** (short break of nearest support
  wall below; target next wall below).
- positive gamma + long  → **BOUNCE long** (buy bounce at nearest support
  below; target nearest level above).
- positive gamma + short → **REJECT short** (short reject at nearest
  resistance above; target nearest level below).
- neutral gamma OR neutral direction → **NO TRADE.**

## GRADING
Weighted score (gamma 0.40 + delta 0.40*conviction + vanna 0.20) plus bumps
(confluence +0.10, trend agreement +0.05, clean >=2:1 runway +0.05).
A+ >= 1.0, A >= 0.85, B >= 0.6, C >= 0.4, else NO-TRADE.

## DATA SOURCE — SCHWAB (schwabdev library)
- `client.quote(symbol)` → spot.
- `client.option_chains(symbol, contractType="ALL", strategy="SINGLE",
  includeUnderlyingQuote=True)` → chain. Nested under callExpDateMap /
  putExpDateMap; keys are "YYYY-MM-DD:DTE"; each contract has gamma, delta,
  vega, theta, openInterest, totalVolume, volatility(IV %).
- `client.price_history(symbol, periodType="day", period=10,
  frequencyType="minute", frequency=5, needExtendedHoursData=True)` → candles
  (epoch ms). Need extended hours for pre-market range.
- OAuth2: browser login once, token auto-refreshes (~weekly). Greeks come back
  as -999/NaN when missing — clean to 0.
- Vanna/charm not provided by Schwab. Vanna is proxied; charm omitted.
- Only keep nearest NUM_EXPIRATIONS expirations and strikes within
  STRIKE_RANGE_PCT of spot.

## DELIVERY
Pushover (same as FLOWSENSE), one notification per ticker, plus full terminal
log. Notifications must be useful and complete, never spammy.

## WHAT'S LEFT TO BUILD — THE INDICATOR (Pine Script v6)
Build on TradingView in **Pine Script v6** (`//@version=6`; current as of 2026;
booleans are strict true/false now, no implicit na-as-false).

Purpose: enforce the engine's entry rules live. It is NOT a predictor; it
confirms.

INPUTS (user types these in from the morning briefing):
- Direction for the day: Long / Short / Neutral (dropdown).
- Setup type: Break / Bounce / Reject (dropdown).
- Up to ~4 key levels (the action level + targets) as price inputs.
- The action level specifically (the one to watch for entry).
- Toggles: require confluence? require volume confirmation? prime-window only?
- Adjustable params: displacement body % min (default 0.50), close-location
  third (default 0.333), volume lookback + multiple for "volume with the move",
  follow-through candles required (default 1), prime window times.

CONFIRMATION LOGIC (only fire when the chosen setup's rules are met):
- 5-MIN candle close only (works on the 5-min, or use request.security to
  evaluate 5-min closes on lower TFs).
- Displacement: body >= body% of range AND close in top 1/3 (bullish) /
  bottom 1/3 (bearish).
- BREAK: a 5-min close beyond the action level, THEN a retest that holds
  (long) / rejects (short). Fire on the retest confirmation, not the initial
  break (this is what avoids the fakeout/stop-out).
- BOUNCE: price taps action level (support), confirming bullish displacement
  candle closes back up off it.
- REJECT: price taps action level (resistance), confirming bearish
  displacement candle closes back down off it.
- Optional gates: volume pushing WITH the move (vs lookback avg); price/volume
  divergence check to suppress likely-failed breaks in positive-gamma days;
  inside prime window (09:30–12:00 ET default).
- Output: a clear BUY/SELL marker + alertcondition() so it can push an alert.
  Show the entered levels as lines. Keep visuals minimal.

DESIGN MATCH TO STRATEGY:
- In a positive-gamma day the indicator should be biased to fade (bounce/
  reject) and treat breaks skeptically (more likely to fail). In negative
  gamma it should trust breaks. Since the engine already picked the setup, the
  indicator just needs to enforce that setup's confirmation — but the volume/
  divergence gate is what encodes the "failed breakout" caution.

## GROUND RULES FOR ANY FUTURE EDIT
- Don't reintroduce charm without a deliberate decision.
- Keep DELTA as the positive=bullish directional convention.
- Keep the 5-min-close displacement rule sacred — it's the timing fix.
- Don't over-filter the engine into never-trades.
- Exposures are context that support the BBR thesis; BBR + price action is the
  actual trade.
- Keep it simple. Carlos wants minimal UI, maximum correctness.
=============================================================================
