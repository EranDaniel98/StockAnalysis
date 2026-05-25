# Strategy Comparison — Frozen Snapshot 4504fcb65f549dae

Generated 2026-05-16T05:09:16.098590+00:00.

- Snapshot: `4504fcb65f549dae`
- Universe: `russell_1000`
- Window: 2022-05-13 → 2024-05-13
- Code revision: `85b15b6`

All strategies below ran against the SAME frozen Parquet snapshot. Any difference in metrics is attributable to the strategy's weights/thresholds, NOT to data drift (`project_yfinance_nondeterminism` is mitigated by the freeze).

## Headline OOS metrics

| Strategy | OOS Sharpe | OOS Sharpe CI | OOS α vs SPY | OOS Max DD | OOS trades | OOS win rate |
|---|---|---|---|---|---|---|
| minimal_baseline | +3.24 | [0.79, 7.99] (OOS) | +23.09% | -9.73% | 69 | +66.70% |
| minimal_baseline_v2 | +3.69 | [1.23, 8.16] (OOS) | +23.69% | -6.91% | 106 | +55.70% |
| minimal_baseline_v3 | +3.34 | [0.53, 8.62] (OOS) | +19.69% | -9.16% | 93 | +54.80% |

## Full-window metrics

| Strategy | Full Sharpe | Full return | α vs SPY | Max DD | Trades | Avg hold (d) |
|---|---|---|---|---|---|---|
| minimal_baseline | +1.09 | +53.68% | +20.65% | -17.06% | 203 | 32.40 |
| minimal_baseline_v2 | +1.60 | +99.84% | +67.36% | -18.87% | 269 | 30.40 |
| minimal_baseline_v3 | +1.43 | +81.22% | +49.42% | -16.58% | 234 | 34.20 |

## Walk-forward folds (Sharpe)

| Strategy | fold 0 | fold 1 | fold 2 | fold 3 | fold 4 | mean | min | passed |
|---|---|---|---|---|---|---|---|---|
| minimal_baseline | -0.43 | -0.91 | +1.96 | +1.56 | +3.39 | +1.11 | -0.91 | FAIL |
| minimal_baseline_v2 | +0.76 | -0.73 | +2.36 | +2.46 | +3.78 | +1.73 | -0.73 | FAIL |
| minimal_baseline_v3 | +1.00 | -0.18 | +0.63 | +2.04 | +3.22 | +1.34 | -0.18 | FAIL |

## Walk-forward folds (return %)

| Strategy | fold 0 | fold 1 | fold 2 | fold 3 | fold 4 | min DD across folds |
|---|---|---|---|---|---|---|
| minimal_baseline | -6.67% | -7.93% | +11.98% | +9.78% | +29.89% | -16.40% |
| minimal_baseline_v2 | +7.48% | -7.24% | +14.91% | +16.40% | +27.12% | -17.55% |
| minimal_baseline_v3 | +10.29% | -2.51% | +4.09% | +13.22% | +23.18% | -12.54% |

## Concentration sensitivity (top-5 winners removed)

| Strategy | Headline Sharpe | Stripped Sharpe | Sharpe drop | Top-5 % of P&L | Verdict (drop ≤ 0.4) |
|---|---|---|---|---|---|
| minimal_baseline | +3.24 | +2.61 | +0.63 | 23.58% | FAIL |
| minimal_baseline_v2 | +3.69 | +2.67 | +1.03 | 30.49% | FAIL |
| minimal_baseline_v3 | +3.34 | +2.17 | +1.17 | 36.43% | FAIL |

## Benchmarks

- **Equal-weight universe (buy-and-hold all 949 tickers in the snapshot at window start, no rebalance)**: total return +40.73%, ann Sharpe 0.94
- **SPY total return (matched window)**: +33.76%

## Yearly breakdown (trades by exit year)

(no trades grouped by year — slim JSON may have dropped trades)

## Data quality

- minimal_baseline: pipeline `2026-05-15-survivorship-haircut`, survivorship `haircut_estimated`
- minimal_baseline_v2: pipeline `2026-05-15-survivorship-haircut`, survivorship `haircut_estimated`
- minimal_baseline_v3: pipeline `2026-05-15-survivorship-haircut`, survivorship `haircut_estimated`

## Provenance per strategy

| Strategy | snapshot_id | git_sha | regime |
|---|---|---|---|
| minimal_baseline | `4504fcb65f549dae` | `85b15b6` | off |
| minimal_baseline_v2 | `4504fcb65f549dae` | `85b15b6` | off |
| minimal_baseline_v3 | `4504fcb65f549dae` | `85b15b6` | off |