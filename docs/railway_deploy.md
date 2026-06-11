# Railway deployment — unattended daily trading

The daily flow (`run_daily_pipeline` → `paper_trade_factor_picks --execute`)
runs as a Railway cron service. Paper keys only until the forward-paper
review (~2026-08-27) passes; go-live is an env flip (see "Go-live"), not a
deploy.

## Topology

- **One cron service** built from the repo `Dockerfile`.
  Cron schedule: `30 12 * * 1-5` (UTC). 12:30 UTC = 8:30 EDT / 7:30 EST —
  always pre-open; `scripts/daily_cron.py` checks the Alpaca calendar
  (holidays/weekends exit silently) and waits for open + 5 min before
  submitting, which absorbs the DST drift of the fixed UTC schedule.
- **Managed Postgres plugin** — holds the EDGAR PIT fundamentals (the
  irreplaceable data; everything else regenerates).
- **One volume** mounted at `/persist` (Railway allows one per service).
  `docker-entrypoint.sh` seeds the repo's checked-in `data/` files into it
  on boot (`cp -rn`, never overwrites) and symlinks `data/`, `reports/`,
  `logs/` to it.
- **No Redis** — the daily pipeline caches via SQLite (`data/cache.db` on
  the volume); Redis only serves the FastAPI web app, which stays local.

## Environment variables (paper phase)

| Var | Notes |
| --- | --- |
| `POLYGON_API_KEY` | OHLCV + news |
| `STOCKNEW_EDGAR_USER_AGENT` | SEC requires a UA |
| `ALPACA_API_KEY` / `ALPACA_API_SECRET` | **paper** keys |
| `ANTHROPIC_API_KEY` | pre-trade LLM sanity gate |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | alerts + daily heartbeat |
| `STOCKNEW_DATABASE_URL` | Railway PG URL, **scheme rewritten** (below) |
| `STOCKNEW_EXECUTION_MODE` | unset / `paper` (default). `live` only on funding day |

**DSN scheme:** Railway hands out `postgres://user:pass@host:port/db`. The
app uses SQLAlchemy async + asyncpg (`src/db/session.py`), so set:

```
STOCKNEW_DATABASE_URL=postgresql+asyncpg://user:pass@host:port/db
```

## One-time data migration (local → Railway)

1. **Postgres** (EDGAR PIT tables — the edge data):

   ```bash
   pg_dump -Fc "postgresql://stocknew:stocknew_dev@127.0.0.1:5432/stocknew" -f stocknew.dump
   pg_restore -d "$RAILWAY_PG_URL" --no-owner --no-privileges stocknew.dump
   uv run alembic upgrade head   # with STOCKNEW_DATABASE_URL pointed at Railway — confirms schema parity
   ```

2. **Volume seed** (`railway ssh` / a one-off shell into the service, or a
   temporary file transfer). Copy from the local machine into `/persist`:

   | Path | Why |
   | --- | --- |
   | `data/daily_picks/` (≥30 days of files) | drift-detector baseline window — without history the gate can't compare against a trailing baseline |
   | `data/live_strategy_state.json` | **kill-switch window continuity** — missing file restarts the 60-trading-day `warming_up` window, leaving the α gate inactive for ~3 months |
   | `data/earnings_history/` | PEAD earnings cache (regenerable but slow) |
   | `data/edgar_cache/ticker_cik.json` | ticker→CIK map (regenerable) |
   | `reports/kill_switch.json` | last gate report (continuity of the daily check) |

   Checked-in files (`data/universe/sp500_*.csv`,
   `reports/momval_dispersion_reference.json`) are seeded automatically by
   the entrypoint — don't copy them.

3. First deploy: trigger a manual run with `--dry-run`, confirm the
   Telegram heartbeat arrives and `data/daily_picks/<today>.json` lands on
   the volume.

## Parallel-run validation (5 trading days)

Keep the local (Windows) daily run alongside Railway for 5 trading days:

- **Railway runs `--execute`; local runs dry-run only** — both point at the
  same paper account, and only one side may submit (deterministic
  client_order_ids would collide as duplicates, but don't lean on that).
- Diff `data/daily_picks/<date>.json` daily (`scripts/check_picks_drift.py`
  helps). yfinance-sourced fields legitimately drift; the ranked ticker
  lists should match.
- After 5 matching days: remove the local Windows tasks
  (`scripts/uninstall_schedule.ps1`) and stop the local runs.

## Go-live (after the 2026-08-27 verdict — not before)

Pre-funding checklist (every box, in order):

1. Forward-paper review passed (~2026-08-27) — the pre-committed gate.
2. 10+ consecutive green Railway heartbeats (no missed days, no failed
   steps, no gate refusals left uninvestigated).
3. `reports/kill_switch.json` reviewed: status `ok`, window full.
4. Fresh, dedicated Alpaca **live** account (Alpaca fills are the cost
   basis — `STOCKNEW_USE_REAL_COST_BASIS` stays off). Wire $25–75k.
5. First two weeks at half size: temporarily halve
   `trading.live.circuit_breakers.max_order_value_usd` in
   `config/settings.yaml`.

Then flip the env on the Railway service — no code deploy:

```
ALPACA_LIVE_API_KEY=...            # distinct from the paper keys
ALPACA_LIVE_API_SECRET=...
ALPACA_LIVE_TRADING_CONFIRMED=1    # explicit consent toggle
STOCKNEW_EXECUTION_MODE=live
```

`daily_cron.py` then routes execution through
`scripts/live_trade_factor_picks.py`: same plan/gates, LIVE endpoint,
`trading.live` circuit-breaker overlay, and **no** `--override-*` /
`--skip-sanity` accepted. Until the flip, the live path is exercised every
Monday as a no-order dry-run smoke (skipped with a log line when live keys
aren't present).

Rollback = unset `STOCKNEW_EXECUTION_MODE` (or set `paper`); the live keys
can stay (nothing reads them in paper mode except the Monday smoke).

## Failure modes → what you'll see on Telegram

| Failure | Alert |
| --- | --- |
| Postgres unreachable | `❌ daily pipeline ...: Postgres unreachable (DB pre-flight failed)` — nothing runs |
| Pipeline step failed / hung > `pipeline.step_timeout_minutes` | `❌ daily pipeline ...: N step(s) FAILED: ...` |
| No picks file produced | `🛑 daily_cron ...: daily_factor_picks produced no picks file` — no trade |
| Drift / kill-switch / sanity refusal | `🛑 trading REFUSED — <gate>: <reason>` |
| Execution step nonzero exit | `🛑 daily_cron ... execution step failed` + output tail |
| Everything fine | one `✅ daily run ...` heartbeat — **silence on a trading day means the cron itself died: investigate** |
