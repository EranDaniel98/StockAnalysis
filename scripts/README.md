# scripts/

Everything runnable as `uv run python -m scripts.X`. Organised by what
the script is *for* — not by what it does. The directory had grown into
a research diary; this README and the `research/` subdirectory are the
line between production and experiment.

## Production daily pipeline

Orchestrator: `run_daily_pipeline.py` — runs the lot in order.

| Script | Purpose |
| --- | --- |
| `daily_factor_picks.py` | Top-N composite-factor picks for today |
| `comprehensive_analysis.py` | Per-stock trading plans for the picks |
| `exit_analysis.py` | Sell plan for current paper positions |
| `position_monitor.py` | Stop / target check on held positions |
| `stress_test.py` | Hypothetical drawdown if the next macro shock lands today |
| `generate_watchlist.py` | Ranks 25–75 — "names on the bubble" |
| `ai_sanity_check.py` | LLM advisory KEEP / FLAG / VETO on each pick |
| `morning_briefing.py` | Single-page summary (reads picks + analysis) |
| `paper_vs_spy_snapshot.py` | Trailing 3M α vs SPY (UI's `/factors` page) |
| `kill_switch_check.py` | 60d rolling α gate — refuses new entries below threshold |

## Paper trading

| Script | Purpose |
| --- | --- |
| `paper_trade_factor_picks.py` | Submit today's picks to Alpaca PAPER (dry-run default) |
| `track_paper_pnl.py` | Roll up paper account P&L over the trailing window |
| `flatten_paper.py` | Close every paper position (use before strategy rollover) |
| `sync_real_holdings.py` | Pull real cost basis from broker into `config/real_holdings.yaml` |

## Backtesting

| Script | Purpose |
| --- | --- |
| `run_factor_backtest.py` | The factor-composite walk-forward harness |
| `analyzer_ic_report.py` | Per-analyzer IC (information coefficient) across regimes |
| `analyze_ticker.py` | One-shot per-stock 5-engine analysis (CLI) |

## Data ops (run when stale)

| Script | Purpose |
| --- | --- |
| `freeze_snapshot.py` | Pin a point-in-time price + universe snapshot |
| `snapshot_features.py` | Cache today's factor features for reproducibility |
| `fetch_sp500_membership.py` | Refresh the PIT S&P 500 universe |
| `fetch_russell_1000.py` | Refresh the Russell 1000 ticker list |
| `run_russell_scan.py` | Score the Russell 1000 |
| `ingest_filings.py` | Ingest 10-K / 10-Q / 8-K from EDGAR into the corpus |
| `backfill_insider.py` | Insider transactions (SEC Form 4) |
| `backfill_insider_narrative.py` | Narrative-feature backfill for insider clusters |
| `backfill_short_interest.py` | FINRA short-interest history |
| `run_edgar_backfill.py` | EDGAR PIT fundamentals (per-ticker) |
| `run_edgar_bulk_backfill.py` | EDGAR PIT fundamentals (universe-wide) |
| `validate_edgar_backfill.py` | Audit EDGAR coverage after a backfill |

## Infrastructure

| Script | Purpose |
| --- | --- |
| `run_api.py` | Launch the FastAPI server |
| `dev.py` | Local dev helper (env, migrations, schema check) |
| `backup.py` / `restore.py` | Postgres + on-disk artifacts |
| `migrate_cache_to_redis.py` | One-time SQLite-cache → Redis migration |
| `migrate_ohlcv_to_parquet.py` | One-time OHLCV → Parquet migration |
| `migrate_paper_db.py` | One-time paper-DB schema upgrade |
| `export_openapi.py` | Dump the FastAPI OpenAPI schema |
| `register_legacy.py` | One-time backfill of legacy strategy IDs |

## Research one-offs (`research/`)

Things we ran once, learned from, and kept for posterity. Not part of
any pipeline. Re-run only if you want to reproduce the finding logged
in `~/.claude/.../memory/MEMORY.md` for that experiment.

| Script | Memory entry / finding |
| --- | --- |
| `research/bull_dd_diagnostic.py` | Decomposed d03 -19% DD into ~70% mechanical β + 30% idiosyncratic |
| `research/kronos_proper_test.py` | Properly-powered Kronos eval (sign-rate CIs include 50%) — KILL |
| `research/spike_kronos_forecast.py` | Initial Kronos spike that was later overruled by the proper test |
| `research/check_backtest_align.py` | One-shot reproducibility check after PIT snapshot freeze |
| `research/compare_strategies.py` | Multi-strategy head-to-head on a frozen snapshot |

## Windows launchers (`.ps1`)

`install_schedule.ps1` / `uninstall_schedule.ps1` — register the daily
pipeline with Task Scheduler. `run_paper.ps1`,
`submit_d03_post_open.ps1`, `sync_real_post_open.ps1`,
`wait_then_sweep.ps1` — convenience wrappers that just call into the
Python scripts above. The `d03` launcher is stale after the
2026-05-23 d05 revert; safe to delete, kept around as a reference.
