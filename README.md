# StockAnalysis

A personal, local-only quantitative trading + research platform.

The system ranks the S&P 500 each day with a point-in-time factor composite
(momentum + quality + value + PEAD), runs a daily pipeline that generates
picks, exit plans, position monitors and a morning briefing, and routes
trades through Alpaca paper. A FastAPI service and a Next.js dashboard sit
on top for browsing picks, backtests, IC diagnostics and the trade journal.

This repository is private and proprietary. There is no installer, no
public API, and no warranty.

---

## What's in the box

| Layer | What it does | Where |
|---|---|---|
| **Factor pipeline** | PIT S&P 500 universe + EDGAR PIT fundamentals → momentum / quality / value / PEAD factors → rank composite | `src/factors/`, `src/universe/`, `src/market_data/edgar/` |
| **Backtest harness** | Frozen Parquet snapshots, 5-fold walk-forward, hyperparameter sweeps, regime splits | `src/backtest/` |
| **Daily pipeline** | 7-step script: picks → analysis → exit plan → position monitor → stress test → watchlist → morning briefing | `scripts/run_daily_pipeline.py` |
| **Paper execution** | Pre-trade gates → bracketed orders → kill-switch on rolling 60-day α | `src/execution/`, `scripts/paper_trade_factor_picks.py` |
| **API** | FastAPI service: backtests, picks, portfolio, research-agent | `src/api/` |
| **Web** | Next.js 14 (App Router) dashboard | `web/` |
| **Research agent** | Anthropic Claude + EDGAR-grounded tools, AI sanity-check on daily picks | `src/research_agent/`, `scripts/ai_sanity_check.py` |

For the design rationale and the edge-discovery audit that led to the
factor rebuild, read `FACTOR_STRATEGY.md` and `SYSTEM.md`.

---

## Daily workflow

The recommended path is the one-command pipeline:

```bash
uv run python -m scripts.run_daily_pipeline --top-n 24
```

This runs all seven steps in sequence. Each step is idempotent and
continues on failure, so partial results stay usable. Outputs land under
`reports/` and `data/daily_picks/` (both gitignored).

After it finishes, read `reports/morning_briefing_*.md` first — it's the
single-page summary; everything else is drill-down.

To run any step on its own, see `FACTOR_STRATEGY.md § Daily Workflow`.

---

## Stack

- **Python 3.10+** managed with [`uv`](https://docs.astral.sh/uv/) (never
  `pip` / `poetry` / `python -m venv`)
- **FastAPI** (async) + **SQLAlchemy 2.0** + **Pydantic v2**
- **PostgreSQL 16** with **pgvector** for embeddings; **Redis 7** for cache
- **Parquet** for OHLCV
- **Next.js 14** (App Router) + **TypeScript** + **shadcn/ui** + **TanStack Query**
- **Alpaca** paper API for execution
- **Anthropic Claude** for the research agent

---

## Repository layout

```
StockAnalysis/
├── src/                          # Python sources
│   ├── factors/                  # momentum / quality / value / PEAD + pipeline
│   ├── universe/                 # PIT S&P 500 membership replay
│   ├── market_data/edgar/        # EDGAR client + PIT fundamentals
│   ├── backtest/                 # engine, sweep, metrics, walk-forward
│   ├── execution/                # Alpaca client, pre-trade gates, kill switch
│   ├── api/                      # FastAPI routers + services
│   ├── research_agent/           # LLM agent + RAG (pgvector)
│   ├── ml/                       # ensemble (Ridge + LightGBM + FFN)
│   ├── db/                       # SQLAlchemy 2.0 + Alembic
│   ├── cache/                    # Redis adapter + TTL policy
│   ├── storage/                  # Parquet OHLCV adapter
│   ├── observability/            # structlog + OTEL hooks
│   ├── contracts/                # pydantic entities + protocol classes
│   └── ...
│
├── web/                          # Next.js 14 dashboard
│   └── app/                      # dashboard / scan / stocks / portfolio /
│                                 # recommendations / backtests / diagnose /
│                                 # ml / research / sectors / journal / ...
│
├── scripts/                      # operational scripts (uv run python -m ...)
│   ├── run_daily_pipeline.py
│   ├── daily_factor_picks.py
│   ├── paper_trade_factor_picks.py
│   ├── ai_sanity_check.py
│   ├── kill_switch_check.py
│   └── ...
│
├── config/                       # YAML configuration (source of truth)
│   ├── settings.yaml
│   ├── strategies.yaml
│   ├── sectors.yaml
│   └── portfolio.example.yaml    # template; live portfolio.yaml is gitignored
│
├── alembic/                      # database migrations
├── tests/                        # pytest suite
├── FACTOR_STRATEGY.md            # factor system user guide
├── SYSTEM.md                     # platform-level design doc
├── CLAUDE.md                     # context for AI assistants
└── LICENSE
```

`data/`, `reports/`, `backups/`, `logs/`, `vendor/`, and `web/.next/`
are gitignored — they're either generated, vendored, or contain
account-specific state.

---

## Configuration

All thresholds, weights, indicator windows and risk parameters live in
`config/*.yaml`. Nothing is hardcoded.

| File | Purpose |
|---|---|
| `settings.yaml` | global params: indicators, filters, risk, display |
| `strategies.yaml` | strategy weights and thresholds |
| `sectors.yaml` | sector / theme definitions + watchlist |
| `portfolio.yaml` | live holdings (gitignored; copy from `portfolio.example.yaml`) |

Secrets go in `.env`. See `.env.example` for the schema.

---

## Disclaimer

This software is for personal research and educational purposes only. It
does not constitute financial, investment, legal or tax advice. Backtest
results, paper-trading P&L, and live signals carry no guarantee of future
performance. Trading equities involves risk of loss.

See `LICENSE` for full terms.
