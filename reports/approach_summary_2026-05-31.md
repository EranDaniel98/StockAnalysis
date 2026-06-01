# Approach — One-Page Summary

## What it is
A **cross-sectional factor composite** over the point-in-time S&P 500. Every name is
scored on several factors, the scores are **rank-combined** (not absolute thresholds),
the top ~24 are held and rebalanced every 63 trading days, gated by a market-regime
filter, and paper-traded via Alpaca. Edge comes from *relative* ranking across stocks,
not from any single metric's level.

## The factors (and the actual metrics each uses)

| Factor | What it measures | Metrics used |
|---|---|---|
| **Momentum (12-1)** | price trend, skipping last month | 12-month return excl. most recent month (Jegadeesh-Titman) |
| **Quality** | profitable, well-financed firms | ROE, ROA, operating & profit margin, FCF/revenue, debt-to-equity |
| **Value** | cheap relative to fundamentals | earnings yield = TTM-EPS / price *(P/E inverse). TTM bug FIXED 2026-05-31; regime-dependent — strong in value rotations (2024-26 IC +0.06, t2.9), negative in growth eras (2018-22)* |
| **PEAD** | post-earnings-announcement drift | earnings surprise % → short-term drift |

Combination: each factor → cross-sectional z-score/rank → equal-weight rank-blend.
Overlays: **regime gate** (200/75-day SMA trend + VIX), **turnover hysteresis** (0.75
carry bonus to incumbents), **sector caps**. All parameters live in `config/*.yaml`.

## Data
- Prices: **Polygon** (EOD + intraday minute bars; deterministic, delisting-inclusive).
- Fundamentals: **EDGAR point-in-time from filings** (the structural edge — true as-filed
  numbers, no lookahead). VIX + earnings dates from yfinance.

## What works (honest, after exhaustive testing)
- **The durable edge is the small PEAD + quality core** — the only signal that's positive
  and consistent across regimes *and* a 2000-name broad universe. Value (P/E etc.) is weak
  + has a known bug; momentum is strong but regime-fragile.
- **Measurement matters more than the factor:** a 2yr backtest has a ±20-30pp luck envelope,
  so everything is judged **phase-averaged** on **CAPM-α** (beta-adjusted), not single runs.

## What the search found (beyond the core)
- **PEAD+quality beta-neutral long-short (S&P-500):** real market-neutral α in value/quality
  regimes (+3-7%), but **regime-dependent** (negative in junk rallies) and break-even over
  full history. Not all-weather; regime-timing it doesn't work.
- **"Gap & crap" (intraday):** short earnings gap-ups rejected in the first 30 min. The one
  *robustly hardened, orthogonal* edge found (+0.41%/trade, t≈2.9, plateau-robust) — but
  **decaying** recently. A small intraday satellite candidate, not a core.

## Bottom line
Cheap EOD + EDGAR data yields **one durable edge (PEAD+quality)** plus a modest decaying
intraday satellite. A genuinely *new* edge needs new data (analyst revisions, options flow,
or long-history short-interest/insider), not more searching.
