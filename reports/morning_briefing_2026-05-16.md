# Morning Briefing — 2026-05-16

Overnight autonomous loop on branch `overnight/2026-05-16`. Goal: maximize
research value while you slept, within hard safety limits (no real-money
trading, no destructive ops, no paid services, no merge to main). Every
meaningful change committed.

## TL;DR

Two findings of the night, in priority order:

**1. The backtest engine is NOT deterministic across yfinance pulls.**
Two runs of 2024-2026 minimal_baseline hours apart returned full
Sharpe 2.08 → 1.60 (-0.48), OOS Sharpe 2.89 → 2.51 (-0.38),
walk-forward fold 0 Sharpe 1.57 → 0.49 (-1.08). Same code, same
pipeline version, same window. Cause is almost certainly yfinance
drift — Yahoo back-applies dividend/split adjustments for several
days after the event. Every prior point estimate in the audit chain
needs ±~0.4 Sharpe error bars around it that include this noise.

**2. Of the six analyzers, only `fundamental` carries
Bonferroni-significant 5D predictive signal.** `trend` and `alpha158`
are flat noise (IC -0.001 and +0.002 respectively). `technical` and
`statistical` are 0.73 correlated duplicates that voted together for
70% of the strategy's weight while neither one is significant alone.
The composite's top quintile actually UNDERPERFORMS the bottom
quintile at 5D (-0.067% spread). The strategy currently allocates
30% to its only proven signal and 70% to a duplicated weak/noise pair.

The 2022-2024 minimal_baseline result is still the first credible
signal we have, but the strategy is regime-dependent — it lost money
for ~10 months in the 2022 bear before recovering. Walk-forward strict
gate fails on those two folds. Tooling shipped to investigate WHY:
per-analyzer IC report (DONE, see above), regime-filter hypothesis
(running now), and analyzer correlation matrix (DONE). The next
ranked decisions are:

1. **Freeze price data into Parquet snapshots per backtest run.**
   Until this lands, every Sharpe in the audit chain has ~0.4 of
   irreducible yfinance noise on top of bootstrap noise. Without it
   you cannot compare any two backtest runs cleanly.
2. **Re-weight minimal_baseline_v2 toward fundamental + drop the
   technical/statistical duplicate.** Hypothesis: 0.60 fundamental +
   0.40 statistical (drop technical because they're 0.73 correlated;
   statistical has slightly stronger raw IC + IR). Test on 2022-2024
   OOS Sharpe + alpha-vs-SPY-matched. If alpha is preserved or
   improved on a smaller, cleaner weight set, we've found the
   load-bearing signal. If alpha collapses, the prior alpha was
   carried by the technical/statistical correlation noise after all.
3. **Drop the entire "edge exists" claim until walk-forward passes
   without survivorship + with the bear folds + averaged over ≥3
   independent yfinance pulls.** That is the load-bearing question,
   not point-estimate Sharpe magnitude.
4. **Wait for regime A/B (task `bkm9clcat`) result.** If skip_bear
   neutralizes folds 0/1 without killing folds 2-4, the strategy is
   salvageable behind a regime gate; if it kills 2-4 too, the "edge"
   was just being long in 2023.
5. **Per-analyzer IC at 21D + 42D horizons.** The strategy's actual
   avg hold is 35.9 days. Current 5D IC misses the timescale the
   strategy actually trades on. Rerun with prices extended to
   end_date + 90 calendar days so alphalens can compute 21D/42D
   forward returns without truncating.

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

### Runs completed
- **Verify1 (2024-2026, fresh yfinance pull, task `bx1m5fp0j`)** —
  result at `data/baseline/minimal_baseline_verify1.json`. Headline:
  ENGINE IS NON-DETERMINISTIC across yfinance pulls. Full Sharpe
  2.08 → 1.60. OOS Sharpe 2.89 → 2.51. Walk-forward folds 0/1
  shifted ~1.1-1.4 Sharpe each. Diff against the original is in
  commit message `234fe17`.

- **IC report 5D (2022-2024, task `bxw50bdxk`)** —
  `reports/analyzer_ic_2022_2024.md`. Bonferroni k=6, panel 97k rows.
  Only `fundamental` is significant (Bonferroni-p < 0.0001) at 5D.
  `trend` IC -0.001 NOISE, `alpha158` IC +0.002 NOISE. `technical`
  and `statistical` IC 0.014/0.020 (not significant). `pattern`
  refused by alphalens (>80% NaN, too sparse). Composite top-Q
  UNDERPERFORMS bottom at 5D. Commit `fc1cb43`.

- **EXTENDED IC report 5/11/23/44D (2022-2024)** —
  `reports/analyzer_ic_2022_2024_extended.md`. **Deepest finding of
  the night.** At the strategy's actual hold horizon (44D ≈ avg
  35.9-day hold):

  | factor      | 5D     | 11D    | 23D    | 44D     |
  |-------------|--------|--------|--------|---------|
  | technical   | +.014  | +.004  | -.001  | **-.015** (anti) |
  | fundamental | +.018* | +.023* | +.029* | **+.041*** (MODEST) |
  | statistical | +.020  | +.016  | +.011  | **-.016** (anti) |
  | composite   | +.024  | +.020  | +.020  | **+.008** (NOISE) |

  (* = Bonferroni-significant)

  Reading: at the horizon the strategy actually trades on,
  `fundamental` is MODEST signal (IC +0.041, top-bottom spread +1.2%),
  while `technical` and `statistical` go ANTI-predictive (their top-
  quintile UNDERPERFORMS bottom-quintile by 1.2% and 1.8% over 44
  trading days). The composite top-quintile underperforms bottom by
  0.91% at 44D.

  **How is the strategy generating +6.1% OOS alpha if its composite
  has zero predictive power at its hold horizon?** Three hypotheses
  remain to test:
    A. fundamental alone is doing all the work; tech/stat noise
       partially cancels and lets fundamental's signal through.
    B. The strategy's NON-SCORE machinery (min_score filter, ATR
       stop, time stop, position sizing, earnings blackout) is
       capturing positive expectancy independent of the score.
    C. Survivorship bias + AI-bubble window inflated the apparent
       alpha. On a truly PIT universe with delisted tickers, the
       6.1% would shrink.

  See commit `fefd43d`. Two new strategies shipped to test
  hypothesis A:
    - `minimal_baseline_v2` — 0.60 fundamental + 0.40 statistical
      (commit `208f0ce`)
    - `minimal_baseline_v3` — 1.00 fundamental
      (commit `58ab177`)

- **Correlation matrix (2022-2024)** — `reports/analyzer_correlation_2022_2024.md`.
  Exactly one flagged pair: `technical ↔ statistical = +0.73`. Pearson
  and Spearman agree. minimal_baseline weights 0.40 + 0.30 = 0.70 on
  this duplicated pair; effectively the strategy is voting one column
  twice. Implications detailed in commit `f469d02`.

- **Regime A/B `skip_bear` vs `off` on 2022-2024** (task `bkm9clcat`,
  completed). Result: the gate **did not fire**. Folds 0/1 are
  byte-identical to baseline; the bear classifier requires both
  SPY<SMA200 AND VIX>25, but VIX>25 was intermittent in 2022, so most
  Mondays got labeled "chop" which skip_bear permits. Trade telemetry
  confirms: `regimes.vix_high.n = 0` for the entire window. Commit
  `c7fe153`. The skip_bear hypothesis remains unfalsified by this run
  — we just chose the wrong gate.

### Runs queued / in-flight
- **`skip_bear_and_chop` on 2022-2024** (task `blv6po4nq`). This gate
  ALSO refuses on chop (SPY<SMA200 OR VIX in 20-25 zone), which
  matches the 2022 grinding-bear pattern. If folds 0/1 turn neutral
  here without killing 2-4, regime-filtering is a real fix. If folds
  2-4 collapse too, the strategy's edge is just being long in 2023.

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
- **02:15** — Verify1 (task `bx1m5fp0j`) completed. Compared against
  original 2024-2026 — engine non-deterministic; full Sharpe shift
  -0.48 across pulls. Briefing v2 elevates Parquet-snapshot work
  to #1 next step. Commit `234fe17`.
- **02:20** — Kicked off IC report on 2022-2024 in background
  (task `bxw50bdxk`). Cache-hot from verify1, so panel build is
  the only slow step.
- **02:43** — IC report completed in ~28 min. Reading: only
  `fundamental` carries Bonferroni-significant signal at 5D.
  `trend` and `alpha158` are flat noise. `pattern` too sparse for
  alphalens. Composite top-Q UNDERPERFORMS bottom-Q at 5D.
  Commit `fc1cb43`.
- **02:45** — Correlation matrix ran in seconds off the cached
  panel CSV. Result: `technical ↔ statistical = +0.73` — the
  strategy's 70% combined weight on these two is voting one
  column twice. Commit `f469d02`.
- **02:47** — Memory entries saved for both findings. Briefing v3
  rewrites TL;DR with both findings in priority order.
- **02:50** — Kicked off regime A/B (`skip_bear` vs `off`) on
  2022-2024 in background (task `bkm9clcat`). Final research run
  of the night.

<!-- Briefing closes after regime A/B notification fires. -->

