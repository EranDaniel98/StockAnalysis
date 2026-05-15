# StockNew — System Documentation

A personal, local-only quantitative trading platform. Scans US equities, scores them across multiple analysis engines, generates broker-actionable recommendations, paper-trades them on Alpaca, and re-baselines its strategies on historical data. This is a real-money platform — every component is built for correctness first, latency second, cost third.

> **Today's date for any time-sensitive references in this document:** 2026-05-15.

---

## 1. Purpose and design ethos

The system answers four questions, in order:

1. **What is happening?** — pull daily and intraday market data for ~7,500 US equities and the macro context around them (insider transactions, SEC filings, earnings, sentiment).
2. **What is worth attention?** — score the universe through 5 analysis engines + Alpha158 + PEAD, combine via configurable strategy weights, surface the top picks.
3. **How would I act on it?** — translate scores into concrete orders (entry / stop / take-profit / position size) with risk budget enforced at the portfolio level.
4. **Would it have worked?** — historical backtests with point-in-time fundamentals, walk-forward CV, regime splits, and IC diagnostics.

### Design ethos

- **Config-driven.** Every threshold, weight, indicator window, risk parameter lives in `config/*.yaml`. Zero hardcoded magic numbers.
- **Fail-loud over fail-quiet.** A broken analyzer must not silently produce composite 50 + buy lift. A misconfigured EDGAR User-Agent must not silently degrade to IP-ban risk. A dead stream must not report "alive".
- **Belt-and-suspenders at the boundaries.** External-data coercion happens at the boundary AND on access. yfinance string sentinels (`'Infinity'`, `'NaN'`, `'null'`) are neutralized in 3 independent paths.
- **Point-in-time correctness.** Backtests use EDGAR XBRL fundamentals with `valid_from` / `valid_to` ranges. No look-ahead leakage. `LookaheadGuardError` raised loudly if a code path requests a future-dated row.
- **Local-only.** Postgres 16 + Redis 7 + Parquet on localhost. No managed services, no cloud dependencies, no third-party data-broker subscriptions in the critical path.

---

## 2. Repository layout

```
StockNew/
├── src/                          # Python sources
│   ├── contracts/                # pydantic v2 entities + Protocol classes (frozen)
│   │   ├── entities/             # OHLCV, Fundamentals, Signal, Recommendation, …
│   │   ├── protocols/            # PriceRepository, FundamentalsRepository, …
│   │   └── errors.py             # DomainError + LookaheadGuardError
│   ├── data/                     # numeric coercer, screener, fetcher, fetch_outcome
│   ├── market_data/              # EDGAR client + parser + concept_map + ingest
│   │   ├── edgar/
│   │   └── regime.py             # market-regime classifier
│   ├── scoring/                  # composite engine + analyzers + recommender
│   │   ├── analyzers/            # technical, fundamental, patterns, statistical,
│   │   │                         # trend_detector, alpha158, pead
│   │   ├── diversification.py    # consensus scaling (Carver)
│   │   ├── engine.py             # calculate_composite_score, batch_score
│   │   └── recommender.py        # action determination + position sizing
│   ├── portfolio/                # Portfolio, allocation, diversification checks
│   ├── execution/                # Alpaca client, paper trade orchestration
│   ├── backtest/                 # engine, sweep, metrics, portfolio sim, score_cache
│   ├── research/                 # backtest_service, diagnostic_service, quantstats
│   ├── research_agent/           # LLM-backed deep-research agent + RAG
│   │   ├── llm_client.py         # Anthropic Claude wrapper
│   │   ├── orchestrator.py       # multi-step agent loop
│   │   ├── tools.py              # tool implementations
│   │   ├── event_monitor.py      # 8-K / earnings catalysts
│   │   └── rag/                  # chunker, embedder, search (pgvector)
│   ├── ml/                       # ensemble (Ridge + LightGBM + FFN)
│   │   ├── feature_store.py
│   │   ├── drift.py
│   │   ├── ensemble.py
│   │   └── models/               # ridge_trainer, lightgbm_trainer, ffn_trainer
│   ├── db/                       # SQLAlchemy 2.0 models + Alembic + repositories
│   ├── cache/                    # Redis adapter + TTL policy + key builders
│   ├── storage/                  # Parquet OHLCV adapter + partition helpers
│   ├── api/                      # FastAPI routes, schemas, services
│   │   ├── routers/              # /market, /trades, /ml, /research, /backtests, …
│   │   ├── services/             # live_prices, trade_updates, diagnostic_runner, …
│   │   └── middleware.py
│   ├── presentation/             # Rich tables + CLI formatters (used by CLI and web)
│   ├── cli/                      # argparse entrypoints
│   ├── observability/            # structured logging + OTEL hooks
│   └── alerts/                   # Telegram bot
│
├── web/                          # Next.js 14 (App Router) frontend
│   └── app/
│       ├── page.tsx              # dashboard — today's best picks
│       ├── scan/                 # universe scan results
│       ├── stocks/[ticker]/      # per-ticker deep dive
│       ├── portfolio/            # holdings + P&L (authoritative from Alpaca)
│       ├── recommendations/      # strategy-filtered recommendations
│       ├── backtests/            # backtest browser + equity curves
│       ├── diagnose/             # IC reports + quantile spreads (alphalens)
│       ├── ml/                   # ensemble model registry + drift
│       ├── research/             # research-agent feed + chat
│       ├── analytics/            # cross-strategy comparisons
│       ├── calibration/          # score calibration plots
│       ├── journal/              # trade journal
│       ├── sectors/              # sector heatmap
│       └── help/
│
├── config/                       # YAML configuration (the source of truth)
│   ├── settings.yaml             # global params: indicators, filters, risk, display
│   ├── strategies.yaml           # 6 strategies × weights × thresholds
│   ├── sectors.yaml              # sector/theme definitions + watchlist
│   ├── portfolio.yaml            # user holdings (for P&L tracking)
│   └── russell_1000_tickers.txt  # universe override option
│
├── data/                         # local data store (gitignored)
│   ├── ohlcv/year=YYYY/ticker=TICKER.parquet
│   ├── cache.db                  # legacy SQLite cache (migrating to Redis)
│   ├── paper_trading.db          # legacy paper trades (migrating to Postgres)
│   ├── sweep_battery/            # baseline sweep results
│   └── sweep_battery_post_status/# post-hardening sweep results
│
├── scripts/                      # one-shot operational scripts
│   ├── run_sweep_battery.py      # multi-strategy sweep orchestrator
│   ├── summarize_sweep_results.py# diff baseline vs post-status
│   ├── migrate_paper_db.py
│   ├── migrate_cache_to_redis.py
│   ├── migrate_ohlcv_to_parquet.py
│   ├── validate_edgar_backfill.py
│   └── sweep_insider_flow.py
│
├── tests/
│   ├── analyzers/                # per-analyzer unit tests
│   ├── scoring/                  # composite engine, recommender, gating
│   ├── backtest/                 # engine, metrics, portfolio, score_cache
│   ├── data/                     # screener, fetcher, coercion
│   ├── storage/                  # parquet locks, tz normalization
│   ├── market_data/              # EDGAR client + parser + units
│   ├── research_agent/           # RAG, orchestrator, tools
│   ├── api/                      # FastAPI routes + stream resilience
│   ├── parity/                   # cache-replay parity vs recompute
│   └── fixtures/baseline/        # CLI output fixtures for parity diffs
│
├── alembic/                      # DB migrations
├── docker-compose.yml            # Postgres 16 + Redis 7 + pgvector
├── pyproject.toml                # uv-managed dependencies
├── CLAUDE.md                     # AI-assistant instructions
└── SYSTEM.md                     # this file
```

---

## 3. The data layer

### 3.1 OHLCV (Parquet)

- **Why Parquet:** the dominant read pattern is `read range-of-dates for one ticker`. Parquet with year+ticker partition pruning yields sub-millisecond per-ticker reads with no SQL parser overhead.
- **Partition layout:** `data/ohlcv/year=YYYY/ticker=TICKER.parquet`.
- **Concurrency:** single-writer process in Phase 0. Per-partition `portalocker` file locks live under `year=YYYY/.locks/` (Windows-safe — `try/finally` outside the `with` so the OS releases the handle before unlink).
- **Timezone convention:** all stored timestamps are tz-naive UTC. The fix: `df.index.tz_convert("UTC").tz_localize(None)` (previously `tz_localize(None)` directly, which silently dropped data on tz-aware inputs).

### 3.2 Fundamentals (Postgres, point-in-time)

Two backends, one repository:

1. **`yfinance` snapshot** — fast path, current quarter only. Used in the live `analyze` / `scan` flows where look-ahead is not a concern.
2. **SEC EDGAR XBRL** — historical, point-in-time. Used in backtests. Schema:
   ```
   fundamentals(ticker, valid_from, valid_to NULL, source, concept_map_id, value, unit)
   PRIMARY KEY (ticker, valid_from, source, field)
   ```

EDGAR ingestion (`src/market_data/edgar/`):
- **User-Agent fail-loud:** unset or placeholder → `RuntimeError`. SEC explicitly bans connections without a real UA.
- **Rate limiting:** 10 req/s honored via `_RateLimiter` (uses `asyncio.get_running_loop()` — not the deprecated `get_event_loop()`).
- **Retry policy:** 429 honors `Retry-After`. 5xx → exponential backoff. 4xx (other) → no retry, surface to caller.
- **Unit-bucket semantics:** every concept is tagged with an expected unit (`USD`, `USD/shares`, `shares`). EPS reads only the `USD/shares` bucket — so revenue is never accidentally summed into EPS.
- **Concept curation:** `concept_map.py` maps XBRL concepts (`us-gaap:Revenues`, `us-gaap:SalesRevenueNet`, …) to canonical fields. Curation is ongoing.

### 3.3 Cache (Redis)

- `redis.asyncio` with a connection pool and explicit timeouts.
- TTL policy lifted verbatim from the legacy SQLite cache: 5 minutes during market hours, 24 hours when closed.
- Keys are typed and built by `src/cache/keys.py` — shape compatible with legacy keys so hit-rate parity is testable.
- Screener cache keys are full-filter-hashed (`screener_finviz_v2_{sector}_{sha256[:16]}`) so any filter change invalidates the cache instead of returning a stale list.
- Serialization: `orjson` for dicts/lists, Parquet path-pointer for DataFrames.

### 3.4 Postgres (Postgres 16 + pgvector)

Tables (autoritative list, see `alembic/versions/`):
- `fundamentals` — PIT fundamentals (above).
- `paper_recommendations`, `paper_orders`, `paper_trades` — row-for-row port of `data/paper_trading.db`.
- `backtest_runs` — header row + JSONB result tree, indexed on `(strategy, window_start, window_end)`.
- `scan_runs` — every scan's top-N picks with full sub-score breakdown.
- `ic_diagnostics` — alphalens output history.
- `factor_snapshots` — ML feature store rows (one per ticker/date/feature-set).
- `rag_chunks` — research-agent corpus with `halfvec(2048)` embeddings, HNSW index.

---

## 4. The scoring pipeline

```
┌──────────┐      ┌─────────────────┐      ┌──────────────────┐      ┌─────────────────┐
│ Universe │ ───► │ 5 analyzers +   │ ───► │ Composite engine │ ───► │ Recommender     │
│ (7.5K eq)│      │ Alpha158 + PEAD │      │ (weighted avg +  │      │ (action +       │
└──────────┘      └─────────────────┘      │  consensus nudge)│      │  position size) │
                                            └──────────────────┘      └─────────────────┘
```

### 4.1 Analyzers (`src/scoring/analyzers/`)

Each analyzer returns a `SubAnalysisResult`:
```python
{
    "score": float | None,       # 0-100, None if analyzer disabled or errored
    "signals": list[Signal],     # bullish/bearish with strength
    "indicators": dict,          # raw indicator values for display
    "status": Literal["ok", "disabled", "error"],
    "error": str | None,
}
```

The 7 analyzers:
| Name           | Inputs                          | What it does                                                          |
|----------------|---------------------------------|-----------------------------------------------------------------------|
| `technical`    | OHLCV                           | RSI, MACD, Bollinger, MAs, volume profile                             |
| `fundamental`  | yfinance / EDGAR snapshot       | Valuation, growth, profitability, leverage, dividend, analyst targets |
| `patterns`     | OHLCV                           | Chart-pattern detection (cup/handle, double-bottom, breakouts)        |
| `statistical`  | OHLCV (returns)                 | Drift, volatility regime, mean-reversion z-scores                     |
| `trend_detector` | OHLCV                         | Multi-timeframe trend strength + alignment                            |
| `alpha158`     | OHLCV + factor lib              | Microsoft Qlib's Alpha158 factor zoo                                  |
| `pead`         | Earnings surprises + drift      | Post-earnings-announcement drift bonus (additive, gated)              |

### 4.2 Composite engine (`src/scoring/engine.py:calculate_composite_score`)

```
composite = weighted_avg(sub_scores × strategy.weights[source])  # 0–100
         + signal_consensus_nudge                                # ±5, normalized per analyzer slot
         + carver_consensus_scaling                              # multiplicative, gated on alignment
         + pead_bonus                                            # additive, requires pead enabled
```

**Critical correctness gate (the keystone fix):**
```python
score_valid = all(sub.status != "error" for sub in active_subs)
if not score_valid:
    return CompositeScore(score=composite, score_valid=False, ...)
# PEAD / Carver / ±5 nudge applied ONLY when score_valid=True
```

Previously, a broken analyzer returned `score=50.0` silently. The composite then received the full PEAD bonus + Carver lift + consensus nudge on top, producing a manufactured BUY signal on a broken pipeline. The `score_valid` flag now propagates through `Recommendation`, paper-trade entry filter, AND backtest entry loop. The recommender force-overrides to `HOLD` / confidence `Low` when `score_valid=False`.

### 4.3 Enabled-sources symmetry

Sweep replays use a cached `CachedScore` and re-compose with different `enabled_sources` sets. The keystone parity fix: `recompose_composite` filters `pead_bonus`, `sub_scores`, AND `signal_counts` symmetrically. Previously PEAD leaked through both arms of any A/B test, producing byte-identical composites and masking real differences (likely root cause of the 2026-05-14 insider_flow R1000 null result).

### 4.4 Recommender (`src/scoring/recommender.py`)

- **Action:** thresholds (`strong_buy`, `buy`, `hold_upper`, `hold_lower`, `sell`) come from `strategies.yaml`, defaults from `settings.yaml`.
- **Position sizing:** fixed-fractional or volatility-targeted. Kelly is **refused** (logged WARNING, falls back to fixed-fractional, marked `original_method="kelly"` + `kelly_refused_reason` in the result). Real money + Kelly + finite sample = pain.
- **Risk budget:** `risk_per_trade_pct` from `sizing_config` (`vol_target_risk_pct` alias accepted, canonical wins).
- **Stop / take-profit:** ATR-based stop, conviction-scaled TP (Stage 2/3 of triple-barrier work — pending).

---

## 5. The backtest engine

`src/backtest/engine.py` runs strategies over historical windows with:

- **Walk-forward CV** with configurable train / test split.
- **Regime splits** — bull / bear / range markets, plotted separately.
- **Point-in-time fundamentals** — fundamentals queried with `valid_from <= as_of_date < valid_to`. `LookaheadGuardError` raised if the loader is asked for future data.
- **Score caching** — `_score_ticker` caches `CachedScore(sub_scores, signals, pead_bonus, atr, close, …)`. Replays compose composites on the fly via `recompose_composite`, so an entire sweep over `enabled_sources` configurations costs one base pass + N composition passes (orders of magnitude faster than re-scoring).
- **Honest metrics** (`src/backtest/metrics.py`):
  - **CAGR** respects `compound` flag — linear for fixed-fractional sizing, geometric for compounding.
  - **Sharpe** uses empirical `periods_per_year = n_samples / years_elapsed` derived from equity-curve dates, then annualizes via `sqrt(periods_per_year)`. Previously a hardcoded `WEEKS_PER_YEAR=52` lied on holiday weeks.
  - `annualization_method` field emitted alongside summary ("compound" / "linear").
- **Equity conservation** — `current_equity()` sums `cost_basis`, not `shares × entry_price`, so per-trade commission doesn't shrink the vol-target sizing basis transaction by transaction.

### Sweep battery (`scripts/run_sweep_battery.py`)

Multi-strategy orchestrator. `--parallelism N` dispatches via `ThreadPoolExecutor`. `--skip-existing` resumes after a crash. `--bootstrap-resamples 500` is the new default (was 2000 — diminishing returns).

⚠️ **Windows subprocess caveat:** orphan grandchild Python workers can survive a parent kill because Windows doesn't cascade process-group kills the way POSIX does. Future orchestrators should use `subprocess.Popen(creationflags=CREATE_NEW_PROCESS_GROUP)` or Windows job objects.

---

## 6. Paper trading (Alpaca)

`src/execution/paper_trade_service.py` orchestrates entries; `paper_evaluate_service.py` walks open positions through their exit conditions; `sync_service.py` reconciles with Alpaca's authoritative state.

**Entry filter:** qualified-list filter now refuses any recommendation with `score_valid=False`. Logs WARNING with refused count.

**Real-money safety:**
- Real-time price coercion at the fast_info boundary (`coerce_numeric` on every field) — neutralizes the BILL-class string-sentinel TypeError that crashed the pipeline on Mondays when yfinance returned `'Infinity'`.
- Stop-loss / take-profit dicts coerced to `{}` (not `None`) so `.get("stop_loss", {}).get("price")` chains don't crash on migration targets.

### Live infrastructure (Alpaca streams)

Two singleton fanout buses share a single Alpaca websocket each (free-tier accounts get one concurrent WS):
- `LivePriceBus` (`src/api/services/live_prices.py`) — per-symbol refcounts, queues per SSE client.
- `TradeUpdatesBus` (`src/api/services/trade_updates.py`) — account-wide trade events.

**Resilience pattern (audit #24):**
- `_run_task.add_done_callback(_on_stream_exit)` fires when the stream task ends for any reason.
- `_on_stream_exit` captures the cause (cancelled / exception / clean-exit), flips `_stream_healthy=False`, captures `_stream_last_error`, marks every subscriber `failed=True`.
- `is_healthy` property combines the flag with task-done state — operators read this, not `_run_task`.
- Next `_ensure_stream` call reconnects automatically.

Previously, a stream task could die silently (alpaca-py losing the WS quietly, auth rotation, network blip) and the bus would keep reporting "alive" while delivering zero trade events. Operators missed fill notifications on real trades.

---

## 7. The web app (Next.js 14)

App Router, TypeScript, TanStack Query for server state, shadcn/ui components, Tailwind. Routes:

| Route                         | What it shows                                                        |
|-------------------------------|----------------------------------------------------------------------|
| `/`                           | Dashboard — today's best picks across all strategies                 |
| `/scan`                       | Universe scan results, strategy-filtered                             |
| `/stocks/[ticker]`            | Per-ticker deep dive: sub-score breakdown, signals, chart, news      |
| `/portfolio`                  | Holdings + authoritative P&L from Alpaca + live tick-delta estimate  |
| `/recommendations`            | Strategy-filtered recommendations with order details                 |
| `/backtests`                  | Backtest browser, equity curves, regime splits                       |
| `/diagnose`                   | IC reports, quantile spreads (alphalens output)                      |
| `/ml`                         | Ensemble model registry, drift monitor                               |
| `/research`                   | Research-agent feed + chat                                           |
| `/calibration`                | Score calibration plots (predicted vs realized)                      |
| `/journal`                    | Trade journal with notes + tags                                      |
| `/sectors`                    | Sector heatmap                                                       |
| `/analytics`                  | Cross-strategy comparisons                                           |

**Portfolio P&L (authoritative):**
- `snapshotUnrealizedPnl = sum(positions[].unrealized_pnl)` — direct from Alpaca's portfolio snapshot.
- `liveTickDelta = sum((tick.price - position.current_price) × shares)` — estimated drift since the snapshot, from the LivePriceBus SSE stream.
- Tile subtitle marks "live tick est." when `liveTickDelta != 0`. The snapshot is the truth; ticks are a UI nicety.

**TradingView link-outs:** every page that renders a ticker has a small `ExternalLink` icon that opens `https://www.tradingview.com/symbols/{TICKER}/` in a new tab (`rel="noopener noreferrer"`).

---

## 8. The research agent

`src/research_agent/` — an Anthropic-Claude-backed deep-research agent that can investigate a ticker, an event, or a thesis end-to-end.

### Components

- **`llm_client.py`** — Anthropic SDK wrapper. Explicit `timeout` and `max_retries`. Streams user-facing responses; batches background work.
- **`orchestrator.py`** — multi-step agent loop: plan → call tool → observe → re-plan. Budget-bounded.
- **`tools.py`** — tool implementations: `read_recent_news`, `query_rag`, `fetch_filing`, `score_ticker`, `query_backtest_db`, …
- **`event_monitor.py`** — proactively surfaces 8-K filings, earnings releases, and unusual options activity as candidate research triggers.
- **`budget.py`** — token / cost ceiling per session.
- **`rag/`** — Retrieval-Augmented Generation corpus.
  - `chunker.py` — semantic chunking of filings + news.
  - `embedder.py` — embedding generation with **dimension validation** (raises RuntimeError if `vecs.shape != (n, EMBEDDING_DIM)` — prevents pgvector corruption from silent model changes).
  - `search.py` — pgvector HNSW search, always filters by `embedding_model = :model` so a model swap doesn't silently return stale vectors.

---

## 9. The ML ensemble

`src/ml/` — a stacked ensemble that predicts forward returns from the same factor set the analyzers consume.

- **Ridge regression** — linear baseline, fast, well-calibrated.
- **LightGBM** — gradient-boosted trees, captures nonlinear interactions.
- **Feed-forward NN** — deep model for residuals.

Stacking weights are learned out-of-sample via walk-forward CV. The ensemble's prediction becomes an additional sub-score (`ml_ensemble`), weighted by strategies that enable it.

`drift.py` monitors feature distributions and prediction quality online; `registry.py` versions models with their training window + feature set so reproducibility is guaranteed.

---

## 10. CLI

`src/cli/main.py` — argparse + dispatch. The CLI is a thin shell over the service layer; everything it does is reachable from the API too.

```bash
# uv-managed; all commands prefixed `rtk` for token-efficient output
rtk uv run python -m src.cli.main analyze TICKER [--budget N] [--strategy NAME]
rtk uv run python -m src.cli.main scan [--budget N] [--strategy NAME] [--theme NAME]
rtk uv run python -m src.cli.main backtest --strategy NAME [--years N] [--min-score N]
rtk uv run python -m src.cli.main diagnose --strategy NAME --years N --quantiles N
rtk uv run python -m src.cli.main portfolio [--analyze]
rtk uv run python -m src.cli.main watchlist [--budget N]
rtk uv run python -m src.cli.main paper {bootstrap, evaluate, status, sync, trade}
rtk uv run python -m src.cli.main strategies
rtk uv run python -m src.cli.main cache {clear, stats}
```

CLI output goes through `src/presentation/cli/` — Rich tables + panels. The same formatters are reusable by the web layer (server-rendered components consume the same `Recommendation` and `CompositeScore` types).

---

## 11. The configuration system

All knobs live in `config/*.yaml`. The system never reads a hardcoded threshold.

### `config/settings.yaml`

- `indicators` — RSI period, MACD windows, Bollinger σ, ATR period, …
- `filters` — min price, min volume, min market cap, sector exclusions
- `risk` — max drawdown, max position size, max sector concentration
- `display` — Rich table widths, color thresholds, decimal precision
- `paper_trading` — commission model, slippage assumption, time-in-force defaults
- `sizing_config` — `risk_per_trade_pct`, vol-target target

### `config/strategies.yaml`

6 strategies, each with:
- `weights` — per-analyzer weight (sums to 1.0 over enabled sources)
- `thresholds` — `strong_buy / buy / hold_upper / hold_lower / sell`
- `holding_horizon_days`, `min_score`, `max_positions`
- Strategy-specific filters (e.g. `min_dividend_yield` for `dividend_income`)

Current strategies: `swing_trading`, `short_term_momentum`, `mean_reversion`, `long_term_growth`, `value_investing`, `dividend_income`.

### `config/sectors.yaml`

Sector and theme definitions + the watchlist.

### `config/portfolio.yaml`

User's current holdings (cost basis, share count, account). Used for P&L tracking and as a hard filter on `scan` (don't re-recommend what you already own).

---

## 12. Recent hardening (2026-05-15 audit sweep)

A 7-agent code-weakness audit produced 22 findings across Tiers 1-4. All Tier-1 and Tier-2 items shipped in PR #1 (branch `audit-fixes-2026-05-15`). Headline outcomes:

| # | Area | Fix |
|---|------|-----|
| 1 | Composite | `score_valid` flag — broken pipeline can no longer manufacture BUY |
| 2 | Recommender | Force-HOLD on `score_valid=False`; Kelly refused; risk-per-trade configurable |
| 3 | Backtest entry | Refuses `score_valid=False` recommendations (both single + multi-mode) |
| 4 | Paper trade | Same entry-side refusal |
| 5 | Fundamentals | Shared `coerce_numeric` at boundary AND on-access (BILL fix, 3 paths) |
| 6 | Fetcher | Realtime fast_info coerced at boundary |
| 7 | Sizing | `current_equity` sums `cost_basis` so commission doesn't shrink vol-target basis |
| 8 | Sharpe | Empirical `periods_per_year` from equity-curve dates (was hardcoded 52) |
| 9 | CAGR | Respects `compound` flag — linear when fixed-fractional |
| 10 | Score cache | PEAD bonus + signal counts symmetric with `enabled_sources` |
| 11 | Parquet | Lock files in `.locks/` subdir + outside-with cleanup (Windows-safe) |
| 12 | Parquet | `tz_convert("UTC").tz_localize(None)` — no more silent data drops |
| 13 | Fetch outcome | Daemon thread pool (re-implemented `_adjust_thread_count`) |
| 14 | EDGAR | User-Agent fail-loud; 429 honors `Retry-After`; 5xx exp backoff |
| 15 | EDGAR | Unit-bucket semantics — EPS reads only `USD/shares` bucket |
| 16 | RAG | Embedder validates dimension; search filters by model fingerprint |
| 17 | Screener | Full-filter-hashed cache key (filter change → cache miss) |
| 18 | LivePriceBus | `add_done_callback` + `is_healthy` + janitor on subscribers |
| 19 | TradeUpdatesBus | Same resilience pattern |
| 20 | Portfolio P&L | Authoritative from Alpaca snapshot + live tick-delta estimate |
| 21 | Effective weight | Breakdown rows emit renormalized weight (sums to 1.0 on `ok` rows) |
| 22 | Signal consensus | Per-analyzer normalization (not per-indicator) — prevents flood from one source |

17 new test files were added across the audit (~80 assertions total).

---

## 13. Operational runbook

### Cold start

```bash
docker compose up -d                                  # Postgres + Redis
rtk uv run alembic upgrade head                       # migrations
rtk uv run python -m src.cli.main paper status        # smoke
```

### Daily flow

```bash
rtk uv run python -m src.cli.main scan --strategy swing_trading --budget 41904
rtk uv run python -m src.cli.main paper evaluate      # walk open positions
rtk uv run python -m src.cli.main paper sync          # reconcile with Alpaca
```

### Backtest a config change

```bash
rtk uv run python -m src.cli.main backtest --strategy swing_trading --years 3 --min-score 50
rtk uv run python -m src.cli.main diagnose --strategy swing_trading --years 2 --quantiles 4
```

### Re-baseline all strategies

```bash
rtk uv run python -m scripts.run_sweep_battery --parallelism 4 --bootstrap-resamples 500 \
  --output-dir data/sweep_battery_post_status
rtk uv run python -m scripts.summarize_sweep_results --markdown memory/sweep_results_clean.md
```

### Where the data ends up

- OHLCV → `data/ohlcv/year=YYYY/ticker=TICKER.parquet`
- Cache → Redis (port 6379) + legacy SQLite fallback (`data/cache.db`)
- Paper trades → Postgres (`paper_*` tables) + legacy SQLite (`data/paper_trading.db`)
- Backtest results → Postgres (`backtest_runs`) + JSON dump in `data/backtests/`
- Sweep results → `data/sweep_battery/` (baseline) and `data/sweep_battery_post_status/` (post-hardening)

---

## 14. Glossary

- **Composite score** — weighted average of analyzer sub-scores, 0-100, plus consensus nudges and the PEAD bonus, all gated on `score_valid`.
- **`score_valid`** — boolean flag, False when any active analyzer errored. Propagates through Recommendation → paper-trade entry → backtest entry. The keystone correctness gate.
- **Silent-50** — the pre-audit failure mode: a broken analyzer returned `score=50.0` placeholder; PEAD/Carver/±5 then stacked on top, manufacturing a BUY signal on a broken pipeline.
- **PEAD** — Post-Earnings-Announcement Drift. Additive bonus, only applied when `"pead" in enabled_sources` AND `score_valid=True`.
- **Carver consensus scaling** — multiplicative lift when analyzer signals align (named for Robert Carver's systematic-trading book).
- **Signal consensus ±5** — small additive nudge based on count of bullish-minus-bearish analyzer slots (NOT raw indicator votes — that overweighted flood from a single analyzer).
- **Score cache (`CachedScore`)** — frozen per-analyzer sub-scores + signals + PEAD bonus per (ticker, date), letting sweeps replay against many `enabled_sources` configurations without re-scoring.
- **Point-in-time (PIT)** — fundamentals valid for a date range `[valid_from, valid_to)`. Backtests query by `as_of_date`; future-dated rows are excluded by definition.
- **Lookahead guard** — `LookaheadGuardError` raised by repositories when a backtest code path requests data dated after the current bar.
- **Triple barrier** — fixed-take-profit + ATR-stop + time-stop. Stage 2/3 conviction-scaled TP and ATR-trailing stop are pending (#182-#185, blocked on clean-pipeline sweep).
- **Sweep battery** — running every strategy through every interesting configuration (insider mode `off / signal_only / weighted`, min_score, atr_stop) and diffing OOS Sharpe deltas.
