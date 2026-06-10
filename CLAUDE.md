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
- **Gate A/B (daily vs slow), CONFIRMED both halves** — daily-regime (production) vs `--no-daily-regime`, CAPM-α median: COVID daily **+22.8%** / slow **−3.5%**; bear daily +1.0% / slow **+4.1%**. The daily gate trades ~3pp of bear-edge for ~26pp of COVID crash-survival (asymmetric WIN → production gate validated). Slow-COVID −3.5% explains the old covid_breadth −7.9% (that was the slow gate; daily flipped it). All four FRAGILE (WF 0–33%) — robustness is orthogonal to gate choice. `reports/phase_envelope_{covid,bear}_{daily,slow}.json`.
- **PEAD 2020 coverage CONFIRMED real** (34/40 sampled tickers have earnings ≤2020, ~quarterly in 2020-21) → the COVID +22.8% is a genuine mqv+PEAD run, not a silent mqv degrade.

- **Breadth validation (7 rolling windows 2018-2026, 12-mo step, production config)** — answers the fragility question 3 windows couldn't. **6/7 windows positive median CAPM-α (86%), median +5.0%** (even 3/4 non-overlapping positive) → edge real-in-aggregate, NOT a coin-flip. BUT mean WF-pass **20%, 0/7 ROBUST** → fragility is STRUCTURAL, more windows did not rescue it. Beta-adjusted edge only (excess often negative — low-β book lags SPY raw). Constraint: Polygon 10-yr horizon caps breadth at 2018-2026 (pre-2016 = 403, needs tier upgrade). `reports/breadth_summary_2018_2026.txt`. See `project_breadth_validation_2026_06_07`.

**Net verdict (most credible estimate to date):** the production config has a **real but modest beta-adjusted edge — ~+5% median CAPM-α, positive in 6/7 windows across 2018-2026 — that is NOT walk-forward-robust in any window.** Genuine central tendency, structural fold-fragility. Defensive/risk-managed (lags SPY on raw return in bulls). The daily-regime gate + PEAD are validated production choices. Forward-paper validation runs (review ~2026-08-27); don't resume tuning until then.

- **Selection-vs-timing split (gate-off + Treynor-Mazuy, $100M)** — isolates selection from the regime-gate timing. **Gate-OFF (always invested, β~1) selection CAPM-α positive in all 5 clean windows, median ~+5%** → the selection edge is REAL, not a timing artifact. Gate's market-TIMING is NEGATIVE (TM γ<0, several significant) — it cuts β/DD but whipsaws; the COVID crash-exit is its one big win. COVID gate-ON +22.9% vs selection-only +4.8% → the COVID headline WAS mostly the gate. NOTE: prior session phase-envelopes used the $10k default (rounding-dampened — audit #19); $100M is cleaner. NEW data flag: gate-off blew up on 2 windows (+300%/+47%) = a corrupted/delisted price (likely 2023 bank failures) the gated book dodged — worth a universe-data audit. `reports/selection_vs_timing_2018_2026.txt`, see `project_selection_vs_timing_2026_06_07`.

- **Price-artifact hunt — ROOT-CAUSED:** corporate-action discontinuities (Polygon serves one ticker across reuse/rename/split/delist; a window spanning the event stitches two price regimes → fake +1000%+ jumps). Worst: META (Meta Materials→Meta Platforms 2022-06, +1395%), GEN (+5043%). ~12 tickers across 7 snapshots. The momentum factor ranks the artifact #1 → the GATED book buys it, so headline numbers for windows spanning a reuse event (2021-23, 2022-24 = bear A/B, 2023-25) are CONTAMINATED, not just gate-off. **Live picks CURRENTLY CLEAN (verified — trailing 13mo window doesn't span the events), but UNGUARDED.** Tool: `scripts/research/price_artifact_scan.py`. See `project_price_artifact_hunt_2026_06_07`.

- **Price-artifact guard — SHIPPED** (`src/factors/price_quality.py`, `drop_price_artifacts`; |day move|>0.80 or gap>45d). Two chokepoints: live pipeline = PER-as_of drop-on-hit (re-enters once event rolls out); backtest = WHOLE-WINDOW panel scrub (a held position rides the stitch via mark-to-market, so per-as_of isn't enough). Verified gate-off 2021-23 +304%→+8.2%; 4 tests pass; live drops 0 today.

- **Clean re-run ($100M + post-guard) — verdict SURVIVES.** Breadth 6/7 positive, median **+4.8%** (was +5.0%; <1pp/window change → contamination did not mislead the headline). **2024-26 (bull) is now ROBUST** (WF 78%, +12.9%) — $10k rounding was hiding it → 1/7 ROBUST not 0/7. Gate matrix holds: COVID daily +22.9/slow −2.4; bear daily +0.4/slow +4.7. `reports/breadth_summary_2018_2026.txt`.

- **Right-tail harness — BUILT + run** (`scripts/research/right_tail_harness.py`, panel green-lit #1). Scores the composite RANKING vs realized top-decile forward-X risers (pure signal, no gate/cost). **The composite HAS modest tail skill: precision@24 = 0.125 (lift ~1.25) at catching top-decile risers, consistent across 1/3/6-mo, 6-7/7 windows beat random.** sel-return + IC GROW with horizon (+0.85%/1mo → +4.09%/6mo) → best biggest-riser ranker at 3-6mo, weakest at 1mo. A TILT not an oracle. Tail consistency (6-7/7) > trading-book WF (1/7) → supports "WF fragility partly a beta-grading artifact." `reports/right_tail_harness_2018_2026.txt`.

- **Factor x horizon decomposition — DONE** (`scripts/research/factor_horizon_decomp.py`). **MOMENTUM dominates biggest-riser prediction** (lift 2.08 at 3-6mo, 7/7 windows, sel +7.1%/6mo); **value clean #2** (1.67, 7/7); **quality BELOW random** (0.83, 2/7 — stable != biggest mover); **PEAD weak** (1.25 @3-6mo, ~0 sel). **The equal-weight blend DILUTES the tail signal** (momentum-alone lift 2.08 >> composite 1.25). For "rise the most in X": momentum-heavy + value, drop/down-weight quality & PEAD — OPPOSITE of the risk-balanced production blend. CAVEAT: momentum-alone = highest crash risk; quality/PEAD pay for downside, not upside. `reports/factor_horizon_decomp_2018_2026.txt`.

- **52w-high probe — KILLED 2026-06-10** (`scripts/research/high_52w_probe.py`). Orthogonality gate PASSES (Spearman vs 12-1 mom 0.646 pooled, top-24 overlap only 8% — not a clone) but the orthogonal part is **ANTI-tail**: h52_only lift 0.62 @3mo / 0.83 @6mo (below random), sel_ret negative; every h-blend dilutes (mom+h52 0.83 vs mom_only 2.08; m+v+h 0.83/1.25 vs mom+val 1.67). Near-the-high names are steady grinders, not biggest-risers. Don't add to the momval book; only re-test for a conditional-MEAN/low-vol book. `reports/high_52w_probe_2018_2026.txt`.

- **Calibration + abstention — SHIPPED 2026-06-10** (`scripts/research/calibration_abstention.py`, walk-forward, 108 deduped dates). Calibration: top-2% composite names realize **P(top-decile riser) 0.195@3mo / 0.228@6mo** vs 0.10 base, monotone by rank bin. Abstention: **momentum-dispersion (IQR of 12-1 raw) is the only valid signal** of 6 features (LOW disp → edge present; worst-quartile → edge ABSENT: traded sel +3.4/+6.2 vs skipped −0.1/+1.5; survives quartile sensitivity; everything else sign-flips). Wired ADVISORY on the momval screener: live IQR vs frozen reference (`reports/momval_dispersion_reference.json`, `strategies.yaml::momval_book.dispersion_guard`, q75=0.360) → JSON/API/UI banner. **Fired day 1: 2026-06-10 dispersion 0.395 = p82 → caution.** `reports/calibration_abstention_2018_2026.txt`.

- **Beta-neutral WF re-grade — DONE 2026-06-10, hypothesis REFUTED.** Per-fold CAPM-α grading (`passed_capm` in `run_factor_backtest`; both grades in `phase_envelope` + `breadth_summary`): beta-neutral WF-pass = **0% in all 7 windows** vs path-gate 25%/1-ROBUST — STRICTER, not looser. 2024-26 loses ROBUST (its passing folds rode beta: e.g. fold +5.7% return, α −8.2%). Fold-level α is EPISODIC; ~100d fold α noise ≈ ±10-15pp swamps a ~+5%/yr edge, so all-folds-positive WF is an edge-MAGNITUDE test our edge can't pass in principle — fragility ≠ beta artifact, it's the phase-luck capstone at fold granularity. Judge configs on breadth + envelopes, not strict WF. Caveat: non-frozen-earnings snapshots read the live PEAD cache → small cross-session drift (2024-26 med +12.9→+9.0). `reports/breadth_summary_2018_2026.txt`.

- **PEAD earnings sidecar — FIXED 2026-06-10.** Pre-freeze snapshots no longer drift: first PEAD run freezes the live cache to `<snap>/earnings_sidecar.parquet` (outside the content hash, fundamentals_pit.json pattern) and round-trips through the frozen format so run 1 == run N bit-identical (verified, equity curve included). Serialization centralized in `snapshot.earnings_to_long/earnings_from_long`. Breadth-trio sidecars pre-frozen (sidecars are local-only — regenerable, not in git).

**Open threads:** ALL FOUR CLOSED (right-tail→momval book 2026-06-08; 52w-high KILLED; calibration+abstention SHIPPED; beta-neutral WF re-grade REFUTED — all 2026-06-10), + earnings-drift fixed. Next gate: live forward-paper review ~2026-08-27 (don't resume tuning before). Remaining: pre-2016 breadth needs a Polygon tier upgrade.

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
