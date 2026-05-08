# CLAUDE.md - Project Context for Claude Code

## Project Overview

Stock Market Scanner - A Python CLI tool that scans US stocks, analyzes them using 5 analysis engines (technical, fundamental, pattern, statistical, trend), scores them 0-100 with configurable strategy weights, and generates step-by-step broker-actionable recommendations.

## Architecture

- **Config-driven**: All parameters in `config/*.yaml`. Zero hardcoded values.
- **Modular**: Each analysis engine is independent in `src/analysis/`.
- **Scoring pipeline**: Analysis -> Weighted composite -> Recommendation -> Order instructions.
- **Caching**: SQLite cache in `data/cache.db`, market-hours aware (5min open, 24h closed).

## Key Commands

```bash
python -m src.main analyze TICKER [--budget N] [--strategy NAME] [--fresh]
python -m src.main scan [--budget N] [--strategy NAME] [--theme NAME]
python -m src.main portfolio [--analyze] [--budget N]
python -m src.main watchlist [--budget N]
python -m src.main help [topic]
```

## Tech Stack

- Python 3.10+, pandas, numpy, yfinance, finvizfinance, Rich (CLI), python-telegram-bot
- SQLite for caching, YAML for config, .env for secrets

## Conventions

- Nothing hardcoded - all thresholds, weights, parameters from config
- Each analysis module returns `{score: 0-100, signals: [...], ...}`
- Scoring engine combines sub-scores with strategy-defined weights
- Display uses Rich library (panels, tables, color-coded output)

## Config Files

- `config/settings.yaml` - Global parameters (indicators, filters, risk, display)
- `config/strategies.yaml` - 5 strategies with analysis weights
- `config/sectors.yaml` - Sector/theme definitions, watchlist
- `config/portfolio.yaml` - User's holdings for P&L tracking
