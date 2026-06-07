# CLAUDE.md - Project Context for Claude Code

## Project Overview

Stock Market Scanner — a US-equity quant system built on a **cross-sectional factor composite**: Jegadeesh-Titman 12-1 momentum + EDGAR point-in-time fundamentals (quality / value) + PEAD, gated by a SPY-trend / VIX regime filter. It ranks the PIT S&P 500, holds the top names, and paper-trades them via Alpaca. Surfaced through a Next.js + FastAPI web app plus a set of daily scripts.

> Historical note: the original 5-engine 0-100 analyzer stack (`src/scoring`, `src/analysis`) and the `src.main` CLI were removed (git history / memory `project_5_engine_removed`). The live system runs only on `src/factors/*`. Ignore older references to "5 analysis engines" or `python -m src.main`.

## Architecture

- **Config-driven**: parameters live in `config/*.yaml`. Nothing hardcoded.
- **Factor pipeline** (`src/factors/`): each factor takes `(prices, as_of)`, reads only data ≤ `as_of` (anything later is a lookahead bug), and returns a tidy `ticker, raw, rank, z_score` frame; `composite.py` rank-combines them. Live picks: `scripts/daily_factor_picks.py`.
- **Deterministic backtests**: content-addressed frozen snapshots in `data/snapshots/` (prices + SPY + VIX + EDGAR PIT). Build with `scripts/build_snapshot.py`, run with `scripts/run_factor_backtest.py --snapshot-id <id>`. Same inputs → same `snapshot_id` → bit-identical results.
- **Web app**: `web/` (Next.js) + FastAPI (`src/api/`), Postgres-backed.

## Data layer

- **OHLCV → Polygon/Massive** (`src/market_data/polygon/`, adapter `src/data/polygon_fetcher.py`). Selected via `config/settings.yaml` `data.source: polygon | yfinance` (factory `src/data/fetcher_factory.py`). Polygon is deterministic + delisting-inclusive — it replaced yfinance, whose dividend-adjustment non-determinism caused ±0.4 Sharpe drift across runs. `POLYGON_API_KEY` in `.env`.
- **`^VIX` stays on yfinance** — Polygon index data (`I:VIX`) is Indices-tier, not on the $29 Stocks plan; `PolygonDataFetcher` falls back transparently for `^`-prefixed symbols.
- **Fundamentals → EDGAR PIT** (`src/factors/fundamentals_pit_loader.py`, `src/market_data/edgar/`), in Postgres, frozen per-snapshot to `fundamentals_pit.json`. NOT migrated to a price vendor — true point-in-time-from-filings is the edge.
- **Earnings → yfinance** (`src/factors/earnings_cache.py`, for PEAD). **Paper execution → Alpaca** (`src/execution/`).
- Tier caveat: $29 Starter = ~5yr history; backtests before ~mid-2021 (the COVID window) need the $79 (10yr) tier.

## Key Commands

```bash
uv run python -m scripts.daily_factor_picks                 # today's factor picks
uv run python -m scripts.run_daily_pipeline                 # full daily: picks → analysis → exit → monitor → briefing
uv run python -m scripts.build_snapshot --as-of YYYY-MM-DD --start YYYY-MM-DD --end YYYY-MM-DD
uv run python -m scripts.run_factor_backtest --snapshot-id <id> --output reports/<name>.json
```

## Tech Stack

- Python 3.12 (via `uv`), pandas, numpy
- **Polygon/Massive** (OHLCV) · yfinance (VIX + earnings fallback) · EDGAR/SEC (PIT fundamentals) · finvizfinance (screening) · Alpaca (paper trading)
- Postgres + SQLAlchemy 2.0 async + Alembic · Redis cache · Parquet OHLCV store
- FastAPI (`src/api/`) + Next.js (`web/`) · Rich (CLI output) · python-telegram-bot (alerts)
- YAML config, `.env` secrets

## Evaluation discipline (read before trusting ANY backtest number)

- **NEVER trust a single-offset backtest.** A 2yr/63-day window (~8 rebalances) has a **±20–30pp phase-noise envelope** — the headline "+9.26%" was a lucky-phase outlier (median ~−19% across phases). Always evaluate phase-averaged: `uv run python scripts/phase_envelope.py --snapshot-id <id> --base-args "..."` → judge on the mean/median ± spread + %-positive, not one number. See `project_phase_luck_capstone`.
- **2026-05-25 audit caveats — all three RESOLVED (commits `ff13d8b`, `c5b38f2`):**
  - **value factor** — FIXED. `_period_ok` (edgar/parser.py) now rejects YTD 10-Q durations (10-Q EPS = single quarter ~80-100d, 10-K = ~year), and `compute_eps_ttm` does a proper 10-K-anchor + quarter roll. No more duration mixing.
  - **universe freeze** — FIXED (#16). `build_snapshot` freezes full-window membership (additions + removals) and the backtest re-resolves per rebalance. The old freeze was *flattering* — median α +4.5% → +2.8% once corrected.
  - **CAPM α** — FIXED. Backtest computes Jensen's α + market β via OLS (`run_factor_backtest.py`), not raw excess; `alpha_vs_spy_pct` is retained but α is the headline for regime-gated books.
  - Lookahead/PIT discipline audited CLEAN.
  - Net: the phase-luck capstone still stands (edge is in the noise envelope), but it's now phase-luck on *correct* fundamentals + universe + α, not stacked on the old defects.

## Conventions

- Nothing hardcoded — thresholds / weights / params come from `config/*.yaml`.
- Factors return `ticker, raw, rank, z_score` and only read data ≤ `as_of` (lookahead = bug).
- Cross-sectional rank, not absolute thresholds (robust across regimes).
- Backtests run off frozen snapshots, never live fetches. Read autogenerated Alembic migrations before `upgrade head`.

## Config Files

- `config/settings.yaml` — global params incl. `data.source`, regime / VIX gates, indicators, risk, display
- `config/strategies.yaml` — strategy + factor-weight configuration
- `config/sectors.yaml` — sector / theme definitions, watchlist
- `config/portfolio.yaml` — holdings for P&L (gitignored; synced from Alpaca)

## Session log — 2026-06-06/07 (cross-PC handoff)

Local `~/.claude` memory does NOT sync across machines — this section is the portable continuity record.

**Shipped (committed):**
- **AI forward book** — isolated broad-AI 12-1 momentum top-20 HOLD book. `scripts.research.trend_forward_paper --book ai --universe-file data/universe_ai_broad_2026-06-06.txt`; UI at `/research/ai-book` (`GET /api/research/{book}`). Marked daily via a non-fatal `mark_ai_book` step in `run_daily_pipeline`. ~2x-beta, −38%-DD untested; observe, don't tune.
- **Market news** — `/news` + `GET /api/news`, Polygon-sourced, bellwethers config-driven (`settings.yaml::market_news.bellwethers`). First news ingestion.
- **Market outlook** — `/outlook` + `GET /api/market/outlook`: risk-on/neutral/risk-off lean (trend+VIX+news+after-hours tally) + pre/post-market moves (`PolygonClient.open_close`). "Conditions, not forecast."
- **TradingView** — Advanced Chart on stock pages, technicals gauge on `/outlook` (`tradingview-widget.tsx`). Iframe widgets, display-only. Benign `_replaceScript` console error in dev strict-mode only.

**Research findings:**
- **News sentiment IC** (`scripts/research/news_sentiment_ic.py`): weak 1d IC +0.078 (t=2.15), decays to noise by 3d. NOT tradeable at the 63d cadence → sentiment stays dashboard-only, NOT in the composite.
- **2026-05-25 audit caveats**: ALL fixed (value-EPS, universe-freeze, CAPM-α) — verified, doc updated above.
- **3-window validation** (production config, corrected pipeline, phase-averaged): CAPM-α median COVID **+22.8%** / bear +1.0% / bull +9.2% — all positive, ALL FRAGILE (WF 0–44%). COVID is a WIN (overturns the old −7.9%): the daily-regime gate dodges the 2020 crash (timing, not selection; β~0.30). Reports: `reports/phase_envelope_{2c853f10c6638fc0,1c1c314850bb7368,fe045eff04a15142}.json`.
- **Bear gate A/B**: slow gate (`--no-daily-regime`) beats daily +4.1% vs +1.0% CAPM-α (Sharpe 0.32 vs 0.11) in the bear → production trades ~3pp bear-edge for COVID crash-survival. Both still FRAGILE. `reports/phase_envelope_bear_{daily,slow}.json`.

**Net verdict:** positive beta-adjusted alpha in all 3 regimes on clean data, but not robust fold-by-fold (WF fails everywhere). Real-in-aggregate, phase-fragile. Forward-paper validation of the live config still runs (review ~2026-08-27); don't resume tuning until then.

**Open threads:** breadth is the real blocker (more OOS windows); slow-gate-on-COVID not yet A/B'd (the "trades bear-edge for crash-survival" COVID half is inferred, not freshly tested); PEAD 2020 coverage unconfirmed (COVID may degrade to mqv).

### Other-PC setup (what's NOT in git)

**Secrets** — `.env` is gitignored; recreate it. Keys (names only): `POLYGON_API_KEY` (OHLCV/news, $79 10yr tier), `STOCKNEW_DATABASE_URL` (`postgresql+asyncpg://stocknew:stocknew_dev@127.0.0.1:5432/stocknew`), `STOCKNEW_EDGAR_USER_AGENT` (SEC requires a UA), `ALPACA_API_KEY`/`ALPACA_API_SECRET` (paper trading), `ANTHROPIC_API_KEY` (ai_sanity_check). Optional: `OPENAI_API_KEY`/`GEMINI_API_KEY` (discovery loops), `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` (alerts), `STOCKNEW_USE_REAL_COST_BASIS`.

**Infra + data bring-up (in order):**
1. `uv sync` — Python 3.12 env.
2. `docker compose up -d` — Postgres (pgvector/pg16) + Redis on 127.0.0.1:5432 / 6379.
3. `uv run alembic upgrade head` — schema (read the migration first; autogen misses pgvector/enums/server-defaults).
4. `uv run python -m scripts.fetch_sp500_membership` — PIT S&P 500 membership (the universe oracle).
5. `uv run python -m scripts.run_edgar_backfill --universe all` — EDGAR PIT fundamentals into Postgres (slow, unattended; companyfacts path = the clean one). This is the edge data; backtests need it.
6. `cd web && npm install` — frontend deps.

**Regenerable (not pushed — rebuild as needed):** `data/snapshots/` (rebuild via `scripts.build_snapshot --start --end --as-of`; the validation reports above reference snapshot IDs 2c853f10c6638fc0 / 1c1c314850bb7368 / fe045eff04a15142 — rebuild those windows to re-run the sweeps), and `data/*_cache/` (Polygon/EDGAR caches, repopulate on first use). `config/portfolio.yaml` is gitignored (synced from Alpaca).

**Run:** `uv run python -m scripts.dev` (API :8000 + web :3000 together). Daily: `uv run python -m scripts.run_daily_pipeline`. WINDOWS DEV GOTCHA: `--reload` doesn't reliably pick up NEW router files, and killed uvicorn workers leave zombie 8000/3000 binds serving stale code — hard-restart (kill all `scripts.dev`/`run_api`/`next dev`/`multiprocessing-fork` procs) when a new route 404s.
