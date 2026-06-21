# PEACHY ENGINE

Pre-market exposure + BBR briefing engine for SPY / QQQ.

It pulls option-chain and price data from **Yahoo Finance** (no API keys, no
OAuth), computes dealer exposures (GEX / DEX / a light vanna proxy), finds
your key levels (GEX walls stacked with PMH/PML, PDH/PDL, 200 EMA),
classifies the day's environment, picks the high-probability BBR setup
(Bounce / Break / Reject), grades it, and pushes a short, actionable
briefing to your phone.

It does the analysis. **You still execute** with your eyes + the indicator
(built separately): the engine tells you *how you're looking to go in, where,
and what to watch for to confirm.*

---

## What you get per ticker

```
SPY — LONG BREAK DAY (Grade: A+)
Spot 600.00 | negative gamma
Action: 600.15 [CONF]  Target: 604.00
Enter: 5-min displacement candle CLOSE above 600.15 (strong body, top 1/3),
       then a clean retest that holds.
Manage: stop beyond 600.15, hold runners.
```

Plus, in `--live` mode, intraday alerts when exposures shift materially:

```
SPY EXPOSURE SHIFT - 11:35 ET
GEX FLIPPED: +Gamma -> -Gamma (trending regime now)
DEX: was bullish -> now neutral
Top wall: 595 -> 600
Action: prior setup may be invalid. Reassess.
```

---

## Three modes

```
python run.py            # one-shot pre-market briefing (default)
python run.py --serve    # long-running daemon, fires at 9am ET weekdays
python run.py --live     # intraday polling, alerts on exposure shifts
```

---

## One-time setup

1. **Pushover** — grab your User Key and create an app token at
   https://pushover.net.

2. **Install deps**
   ```bash
   pip install -r requirements.txt
   ```

3. **Local config** — copy `.env.example` to `.env` and paste your Pushover
   keys.

4. **Run it**
   ```bash
   python run.py
   ```

That's it. No Schwab, no OAuth, no tokens.

---

## Deploying to Railway

1. **Create a Railway project** and connect this repo. Railway detects
   `railway.json` / `nixpacks.toml` and builds a Python service.

2. **Set environment variables** in Railway's Variables tab:
   ```
   PUSHOVER_USER_KEY=...
   PUSHOVER_APP_TOKEN=...
   TICKERS=SPY,QQQ
   RUN_TIME_ET=09:00
   TZ=America/New_York
   ```

3. **Deploy.** The service runs `python run.py --serve`, which sleeps until
   09:00 ET on weekdays, fires the analysis, pushes the briefing, and goes
   back to sleep.

4. **(Optional) intraday mode.** Spin up a second Railway service from the
   same repo and override the start command to `python run.py --live`. It
   sends a baseline at the start of the session and then alerts when GEX
   flips, DEX shifts, or the top wall moves.

---

## Daily use (off Railway)

Cron it pre-market (9:00 AM ET, weekdays):
```
0 9 * * 1-5  cd /path/to/peachy_engine && /usr/bin/python3 run.py >> log.txt 2>&1
```
Or just run `python run.py` whenever you want a fresh read.

---

## Test it without external data

```bash
python selftest.py
```
Runs two synthetic scenarios end-to-end and asserts the pipeline produces
the right setup (BREAK long in negative gamma + bullish; REJECT short in
positive gamma + bearish).

---

## How the read is built (priority order)

1. **Gamma** (net GEX) → *what kind of day*: positive = chop (bounce/reject),
   negative = expansion (break/continuation). Most important behavioral read.
2. **Delta** (net DEX) → *direction* (easier path). The most important
   directional read, confirmed by 200 EMA + pre-market structure.
3. **Vanna** → light continuation context only.
4. **Charm is intentionally omitted** — low value and changes all day.
5. **Levels** = GEX walls stacked with chart levels (PMH/PML, PDH/PDL).
   Confluence raises the grade.

Then the **BBR setup** is chosen from gamma × direction, the entry trigger is
the **5-min displacement candle close** rule (fixes the candle-close
fake-outs), and the day is graded A+ / A / B / C / NO-TRADE.

## Greeks (Yahoo doesn't return them)

Yahoo's option chain has open interest, volume, and IV — but no greeks. We
compute delta / gamma / vega / theta locally via Black-Scholes-Merton in
`core/yahoo_client.py`. Risk-free rate is `RISK_FREE_RATE` in settings
(default 5%) — bump it occasionally to track Fed funds.

---

## Files

```
config/settings.py     <- env-var-driven config (defaults baked in)
core/yahoo_client.py   <- Yahoo data + BSM greeks (replaces old Schwab client)
core/exposures.py      <- GEX / DEX / vanna math
core/levels.py         <- chart structure + confluence
core/environment.py    <- gamma regime, direction, BBR pick, grading
core/briefing.py       <- builds the briefing text
output/pushover.py     <- phone notifications
run.py                 <- run this (--serve / --live for the other modes)
selftest.py            <- offline validation
railway.json           <- Railway deploy config
nixpacks.toml          <- Railway build config (pins Python 3.11)
Procfile               <- alternative start command (Heroku-style hosts)
.env.example           <- template for local .env
```

---

## What's next — the TradingView indicator (Pine Script v6)

Separate project, not in this repo yet. It lives on the chart during the
session and only fires a confirmation signal when the engine's chosen setup
hits its mechanical entry rules:

- 5-min candle CLOSE only (no wicks).
- Displacement: body ≥ 50% of range AND close in top/bottom 1/3.
- BREAK requires a clean retest hold/reject — not the initial break.
- BOUNCE / REJECT confirm at the action level with the right candle shape.
- Optional gates: volume with the move, prime window 09:30-12:00 ET.

The engine = WHERE + WHAT TYPE. The indicator = WHEN.
