# Morning Briefing — 2026-05-16

Overnight autonomous loop on branch `overnight/2026-05-16`. Goal: maximize
research value while you slept, within hard safety limits (no real-money
trading, no destructive ops, no paid services, no merge to main). Every
meaningful change committed.

## TL;DR

The 2022-2024 minimal_baseline result is the first credible signal we
have, but the strategy is regime-dependent — it lost money for ~10
months in the 2022 bear before recovering. Walk-forward strict gate
fails on those two folds. Tooling shipped to investigate WHY: per-
analyzer IC report (which analyzers actually predict?), regime-filter
hypothesis flag (does skip_bear neutralize 2022?), and analyzer
correlation matrix (which scoring sources are redundant?). Pending the
runs that need fresh compute, the next ranked decisions are:

1. **Drop the entire "edge exists" claim until walk-forward passes
   without survivorship + with the bear folds.** That is the load-
   bearing question, not Sharpe magnitude.
2. **Run the IC report; any analyzer in the NOISE bucket should have
   its weight zeroed in minimal_baseline_v2** — currently we silently
   weight noise into the composite.
3. **Run the skip_bear regime gate on 2022-2024 and compare folds
   head-to-head.** If folds 0/1 turn neutral without killing 2-4, the
   strategy is salvageable behind a regime filter; if it kills 2-4 too,
   the "edge" was just being long in 2023.

## What was true at sleep time

- **2022-2024 baseline result** (`data/baseline/minimal_baseline_2022_2024.json`)
  - Full Sharpe 0.88 / OOS 2.25; alpha vs SPY matched +6.1% OOS (first
    number in the audit chain that sits in the defensible 2-8%/yr band)
  - Walk-forward FAIL — mean Sharpe 0.91, min -0.87. Gate reason:
    `min fold Sharpe -0.87 <= 0 — at least one fold lost money`
  - Concentration: top-5 trades = 39.3% of total P&L (NVDA, ABNB, ALK,
    ANET, DECK); headline OOS Sharpe 2.25 → stripped 1.46 → drop 0.79 (FAIL)
  - Bootstrap Sharpe CI [0.57, 5.09] — lower bound still below 0.7 floor
  - 185 total trades; 66 OOS

  Walk-forward fold table (the headline observation of this run):

  | Fold | Window | Trades | Sharpe | Return | Max DD |
  |---|---|---|---|---|---|
  | 0 | 2022-05-13 → 2022-10-06 | 37 | -0.87 | -11.38% | -18.23% |
  | 1 | 2022-10-06 → 2023-03-01 | 28 | -0.11 |  -1.52% | -12.22% |
  | 2 | 2023-03-01 → 2023-07-25 | 37 | +2.19 | +16.07% |  -4.03% |
  | 3 | 2023-07-25 → 2023-12-18 | 39 | +0.96 |  +7.74% | -12.19% |
  | 4 | 2023-12-18 → 2024-05-13 | 44 | +2.37 | +16.11% |  -7.90% |

  Reading: strategy is regime-dependent. Lost money for ~10 months in
  the 2022 bear (folds 0 + 1 stacked), recovered strongly from 2023
  onward (folds 2-4). The walk-forward gate (strict: every fold > 0
  AND mean ≥ threshold) fails on the negative folds even though the
  mean is above 0.5. A weaker mean-only gate would pass.

- **2024-2026 prior result** (different window, in-bubble): OOS Sharpe 2.89,
  CI [0.66, 5.93], alpha +18.6% — too good, almost certainly carries
  AI-bubble luck. Concentration: 45.7%, also a FAIL.

## Loop work this session

### Checkpointed
- 2022-2024 baseline JSON + interpretation — commit `4c1ba6e`.

### Tooling shipped (commits this session)
- `scripts/analyzer_ic_report.py` — per-analyzer Information Coefficient
  + Bonferroni-adjusted significance + verdicts. Reuses
  `src/research/diagnostic_service.build_score_panel`. Commit `1566442`.
- `scripts/analyzer_correlation.py` — Pearson + Spearman cross-correlation
  of the six analyzer sub-scores. Flags |corr| ≥ 0.7. Commit `678ebf7`.
- `scripts/run_minimal_baseline.py` — `--regime-mode {off,skip_bear,
  skip_bear_and_chop}` flag, fetches ^VIX, monkey-patches the gate.
  Commit `87af0f4`.

### Runs queued / in-flight
- **Verification re-run** (2024-2026 window, fresh yfinance pull, task
  `bx1m5fp0j`). Output → `data/baseline/minimal_baseline_verify1.json`.
  Tests: is the engine deterministic across hours-apart runs, or does
  yfinance drift produce 1.84-vs-2.89 Sharpe noise?
- **Pending compute** (queued for the morning, blocked behind verify
  finishing to avoid yfinance contention):
  - Per-analyzer IC report on 2022-2024 (1000 tickers × 100 weeks)
  - Analyzer correlation matrix on 2022-2024
  - Regime-filter A/B (`--regime-mode skip_bear` vs `off`) on 2022-2024

## What you should look at first

1. **`data/baseline/minimal_baseline_verify1.json`** — did the engine
   return the SAME Sharpe as `minimal_baseline.json`? If yes, the
   pipeline is deterministic and the 2024-2026 number stands. If no,
   we have run-to-run noise that invalidates every prior "OOS Sharpe
   = X" finding in the audit chain.
2. **This file's "Loop log" section below** — every decision and its
   rationale, time-stamped.
3. **`reports/morning_briefing_2026-05-16_results.md`** (if it exists) —
   the IC + correlation + regime-A/B results, generated *after* this
   skeleton.

## Decision rationale snapshot

I treated the loop as a research multiplier, not a "make changes" loop.
Specifically I avoided:

- Touching live trading config (`trading_enabled` stays False).
- Re-running the headline `minimal_baseline` to "confirm" the
  finding — re-runs without changing methodology just buy more noise.
- Adding new analyzers (no edge claim until existing ones have an IC > 0).
- Merging anything to main.

I prioritized tooling that answers questions we currently can't:
*which* analyzers carry signal vs. noise; whether regime filtering
fixes the 2022 problem; whether two analyzers are accidentally voting
the same way and inflating their joint weight.

## Loop log

- **00:31** — Switched to `overnight/2026-05-16`. Read 2022-2024 result.
  First credible signal in the audit chain.
- **00:35** — Kicked off verification re-run of 2024-2026 (task
  `bx1m5fp0j`). Hypothesis: yfinance drift, not engine noise, drove the
  prior 1.84-vs-2.89 Sharpe gap.
- **01:00** — Decision: build the per-analyzer IC framework while
  compute runs. The composite Sharpe is meaningless without knowing
  which analyzers carry the signal. Walked the existing
  `src/research/diagnostic_service.py` — `build_score_panel` and
  `run_alphalens` are already the right primitives.
- **01:15** — Discovered sub-score keys are `technical, fundamental,
  pattern, statistical, trend, alpha158` (engine convention), NOT the
  module file names. PEAD is a bonus modifier, not a sub-score, so it
  is out-of-scope for IC test from the panel. Corrected the script.
- **01:25** — Committed 2022-2024 result as checkpoint `4c1ba6e`.
- **01:30** — Committed IC framework script.
- **01:40** — Added `--regime-mode` flag to `run_minimal_baseline.py`
  (with ^VIX fetch + config monkey-patch). Defaults to `off` so prior
  runs stay reproducible.
- **01:55** — Shipped analyzer correlation matrix script.

<!-- Results section appended once the IC + correlation + regime
runs complete. Verification result fills in the second TL;DR bullet. -->
