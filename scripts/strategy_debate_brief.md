# Strategy Debate Brief — the LIVE system

Curated evidence pack for the Opus↔Gemini strategy debate. This describes the
system that is **actually traded today** (`src/factors/*` + `scripts/daily_factor_picks.py`).

> ⚠️ Do NOT debate `config/strategies.yaml`. That file configures the *deleted*
> 5-analyzer 0-100 scoring engine (`src/scoring/engine.py` + analyzers — removed
> 2026-05-23, no source remains). It is orphaned: still read by the web dashboard
> for display, but it does **not** drive stock selection. The live model below
> bears no resemblance to it (no `min_score`, no consensus scaling, no PEAD bonus
> envelope, no per-analyzer weights).

## The live strategy (what is actually traded)

- **Cross-sectional factor composite** over the point-in-time (PIT) S&P 500.
  Factors: Jegadeesh-Titman **12-1 momentum** + EDGAR PIT **quality** + EDGAR PIT
  **value** (the "m/q/v" composite), with a **PEAD** overlay on by default.
- **Rank-combine, not absolute thresholds.** Each factor returns
  `ticker, raw, rank, z_score`; `src/factors/composite.py` rank-combines them
  (optionally regime-weighted via `regime_weights.py`). This is already fully
  cross-sectional — z-scored against the universe each rebalance.
- **Concentration:** hold the **top 24** names (config "d05"). A top-15 ("d03")
  variant was tried and **reverted** after 90d paper logged **-11.2% α vs SPY**.
- **Rebalance cadence:** 63 trading days.
- **Regime gate:** asymmetric SMA trend filter — 200-SMA exit, **75-SMA re-entry**
  + a VIX gate (`regime.py`, `vix_regime.py`). Already exists; do not propose
  building it.
- **Turnover hysteresis:** 0.75 carry bonus to incumbents.
- **Sector-neutralization** available (`sector_neutralize.py`); sector cap from
  `config/settings.yaml`.
- **Data layer (HARD CONSTRAINT — propose nothing outside this):** OHLCV from
  **Polygon $29 Stocks tier** (~5yr history, EOD bars, delisting-inclusive);
  VIX + earnings from yfinance; **EDGAR** PIT fundamentals from filings; Alpaca
  paper execution. **No** dark-pool prints, **no** options/dealer-gamma (GEX/Vanna),
  **no** intraday/L2, **no** alternative data. Strategies requiring those are
  non-starters.
- **Execution:** paper-traded via Alpaca. Position sizing is roughly equal-weight
  across the top-24 with a sector cap — **no covariance/vol-aware sizing yet.**

## The case FOR the edge

- Composite beats its parts: m/q/v **+9.26%** α vs momentum-only **-6.46%** (S&P
  2024-26). PIT fundamentals beat a lookahead baseline. PEAD overlay +2.53pp avg α
  with tighter drawdown. Hysteresis +4.31pp avg α. α survives costs to 50bps
  (+9.26%→+4.32%). Sensitivity sweep shows the config is a robust compromise, not a
  knife-edge.

## The case AGAINST / open caveats (read before trusting any number)

- **PHASE-LUCK is the headline risk.** The +9.26% is an **offset-0 phase-luck
  outlier**. A `--rebal-offset` sweep is positive in only **2 of 9 phases**, median
  **~-19%**, worst **-40.77%**. A 2yr/63-day window carries a **±20-30pp
  phase-noise envelope** that **swamps** the measured edge. Judge phase-averaged
  (mean/median ± spread, %-positive), never one number.
- **Value factor is suspect (known bug).** EDGAR EPS facts aren't disambiguated by
  period (quarterly vs YTD), so `compute_eps_ttm` can mix durations. Value /
  full-composite numbers unreliable until fixed.
- **Universe-freeze eligibility bias.** Universe frozen at the snapshot's as-of
  date, not re-resolved per rebalance.
- **"alpha" is raw excess return, not CAPM α.** Meaningless for a regime-gated /
  low-beta book. Concentration to top-15 mechanically raised β 0.694→0.884 (~70% of
  its excess drawdown was beta, not skill).
- **Regime gate fails fast crashes.** Slow-bear insurance, NOT crash insurance:
  63-day cadence too slow for a 5-week crash. COVID CAPM-α median **-7.9%**.
  Cross-window CAPM-α: bull +8.8% / slow-bear +6.1% / COVID -7.9%.
- **Regime whipsaw** cost -6.46% α on 2024-26 (a 0.31% 75-SMA whipsaw at the
  2025-01-02 rebalance × 63-day cadence parked the book in cash through SPY +6.11%).
- **Breadth does not help (here).** A clean broad PIT universe (2000 names) scored
  **-9.30% α** vs the S&P's +9.26% — breadth HURT this mega-cap-led window
  (the Russell "+73%" was a survivorship artifact).
- **Regime-dependence:** bear-window crusher (+20.65pp α), bull-window
  underperformer.

## Status

A **forward paper-trading run** of the shipped config (daily-regime + band + PEAD)
started **2026-05-27** at baseline equity $41,895.66 — the un-overfittable test.
First review **~2026-08-27**. No live edge is *proven*; the system is mid-OOS-validation.
Adding new strategies mid-validation risks the exact multiple-comparisons /
overfitting failure the eval discipline warns against.

## Suggested debate focus (symmetric — both critique freely + propose fixes)

1. Is there *any* defensible edge, or is the whole result inside the phase-noise
   envelope? How should edge be **measured** to tell signal from luck?
2. Highest-leverage fix among: value-factor EPS bug, CAPM-α measurement,
   regime-gate crash latency, universe-freeze, covariance-aware sizing?
3. Is a 63-day, top-24, regime-gated S&P-500 composite even the right *shape*, or
   is the design fighting itself (bear-crusher vs bull-laggard)?
4. **Constraint discipline:** every proposal must run on the data layer above. No
   dark-pool, no options-flow, no intraday. What's the best move *within* that box?
