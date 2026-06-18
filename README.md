# PEACHY ENGINE

Pre-market exposure + BBR briefing engine for SPY / QQQ.

It pulls option-chain and price data from Schwab, computes dealer exposures
(GEX / DEX / a light vanna proxy), finds your key levels (GEX walls stacked
with PMH/PML, PDH/PDL, 200 EMA), classifies the day's environment, picks the
high-probability BBR setup (Bounce / Break / Reject), grades it, and pushes a
short, actionable briefing to your phone.

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

---

## One-time setup

1. **Schwab developer app** — at https://developer.schwab.com create an app
   with *Market Data Production* + *Accounts and Trading Production*. Set the
   callback URL to `https://127.0.0.1:8182`. Copy the App Key + Secret.

2. **Pushover** — grab your User Key and create an app token at
   https://pushover.net.

3. **Install deps**
   ```bash
   pip install -r requirements.txt
   ```

4. **Local config** — copy `.env.example` to `.env` and fill in the
   credentials. (For Railway: paste them in the **Variables** tab instead.)

5. **First run on your laptop** (one browser login)
   ```bash
   python run.py
   ```
   schwabdev prints a Schwab login URL. Open it, log in, approve, paste the
   redirect URL back. The token caches to `schwab_token.json` and
   auto-refreshes (~weekly) after that.

---

## Deploying to Railway

Railway is headless, so the OAuth dance has to happen **on your laptop
once** — then we ship the resulting token to Railway and let `schwabdev`
auto-refresh it from there.

1. **Generate the token locally** by running `python run.py` once on your
   machine (step 5 above). This creates `schwab_token.json`.

2. **Create a Railway project** and connect this repo. Railway will detect
   `railway.json` / `nixpacks.toml` and build a Python service.

3. **Add a Volume** to the service mounted at `/data`. This is where the
   refreshed token persists — without it the container loses the token on
   every redeploy and you'd have to re-login.

4. **Set environment variables** in the Railway Variables tab (paste
   straight from your `.env`):
   ```
   SCHWAB_APP_KEY=...
   SCHWAB_APP_SECRET=...
   SCHWAB_CALLBACK_URL=https://127.0.0.1:8182
   SCHWAB_TOKEN_JSON=<paste the entire contents of your local schwab_token.json>
   PUSHOVER_USER_KEY=...
   PUSHOVER_APP_TOKEN=...
   TICKERS=SPY,QQQ
   RUN_TIME_ET=09:00
   TZ=America/New_York
   ```
   `SCHWAB_TOKEN_JSON` only seeds the file once — `schwabdev` then writes
   the refreshed token back to `/data/schwab_token.json` automatically.

5. **Deploy.** The service runs `python run.py --serve`, which sleeps until
   09:00 ET on weekdays, fires the analysis, pushes the briefing, and goes
   back to sleep. Watch logs to confirm the first wake-up.

   Prefer Railway's native cron instead? Switch the start command to
   `python run.py` and set a cron schedule of `0 13 * * 1-5` (13:00 UTC =
   09:00 ET; adjust for DST or just use Railway's TZ setting).

---

## Daily use (off Railway)

Cron it pre-market (9:00 AM ET, weekdays):
```
0 9 * * 1-5  cd /path/to/peachy_engine && /usr/bin/python3 run.py >> log.txt 2>&1
```
Or just run `python run.py` whenever you want a fresh read.

---

## Test it without Schwab

```bash
python selftest.py
```
Runs two synthetic scenarios and asserts the full pipeline produces the right
setup (BREAK long in negative gamma + bullish; REJECT short in positive gamma
+ bearish).

---

## How the read is built (priority order)

1. **Gamma** (net GEX) → *what kind of day*: positive = chop (bounce/reject),
   negative = expansion (break/continuation). Most important behavioral read.
2. **Delta** (net DEX) → *direction* (easier path). The most important
   directional read, confirmed by 200 EMA + pre-market structure.
3. **Vanna** → light continuation context only.
4. **Charm is intentionally omitted** — low value here and changes all day, a
   poor fit for a one-shot pre-market read.
5. **Levels** = GEX walls stacked with chart levels (PMH/PML, PDH/PDL).
   Confluence raises the grade.

Then the **BBR setup** is chosen from gamma × direction, the entry trigger is
the **5-min displacement candle close** rule (fixes the candle-close
fake-outs), and the day is graded A+ / A / B / C / NO-TRADE.

---

## Files

```
config/settings.py     <- env-var-driven config (defaults baked in)
core/schwab_client.py  <- auth + data pulls
core/exposures.py      <- GEX / DEX / vanna math
core/levels.py         <- chart structure + confluence
core/environment.py    <- gamma regime, direction, BBR pick, grading
core/briefing.py       <- builds the briefing text
output/pushover.py     <- phone notifications
run.py                 <- run this (--serve for long-running mode)
selftest.py            <- offline validation
railway.json           <- Railway deploy config
nixpacks.toml          <- Railway build config (pins Python 3.11)
Procfile               <- alternative start command (Heroku-style hosts)
.env.example           <- template for local .env
```

---

## What's next — the TradingView indicator (Pine Script v6)

Separate project (not in this repo yet). It lives on the chart during the
session and only fires a confirmation signal when the engine's chosen setup
hits its mechanical entry rules:

- 5-min candle CLOSE only (no wicks).
- Displacement: body ≥ 50% of range AND close in top/bottom 1/3.
- BREAK requires a clean retest hold/reject — not the initial break (this is
  the fix for the stop-out fake-outs).
- BOUNCE / REJECT confirm at the action level with the right candle shape.
- Optional gates: volume with the move, prime window 09:30-12:00 ET.

The engine = WHERE + WHAT TYPE. The indicator = WHEN.
