# Strategy Comparison — Frozen Snapshot 1dd88cad8e1f7534

Generated 2026-05-16T08:38:51.798894+00:00.

- Snapshot: `1dd88cad8e1f7534`
- Universe: `russell_1000`
- Window: 2024-05-13 → 2026-05-13
- Code revision: `57ebf0d`

All strategies below ran against the SAME frozen Parquet snapshot. Any difference in metrics is attributable to the strategy's weights/thresholds, NOT to data drift (`project_yfinance_nondeterminism` is mitigated by the freeze).

## Headline OOS metrics

| Strategy | OOS Sharpe | OOS Sharpe CI | OOS α vs SPY | OOS Max DD | OOS trades | OOS win rate |
|---|---|---|---|---|---|---|
| minimal_baseline | +2.36 | [-0.55, 7.10] (OOS) | +18.79% | -9.71% | 100 | +46.00% |
| minimal_baseline_v2 | +1.64 | [-0.99, 5.15] (OOS) | +4.44% | -8.09% | 122 | +36.10% |
| minimal_baseline_v3 | +0.55 | [-2.47, 4.01] (OOS) | -6.49% | -13.30% | 88 | +35.20% |

## Full-window metrics

| Strategy | Full Sharpe | Full return | α vs SPY | Max DD | Trades | Avg hold (d) |
|---|---|---|---|---|---|---|
| minimal_baseline | +1.78 | +87.10% | +46.02% | -15.44% | 286 | 29.10 |
| minimal_baseline_v2 | +2.31 | +113.22% | +71.84% | -11.32% | 310 | 30.90 |
| minimal_baseline_v3 | +1.61 | +79.47% | +37.52% | -13.30% | 264 | 34.20 |

## Walk-forward folds (Sharpe)

| Strategy | fold 0 | fold 1 | fold 2 | fold 3 | fold 4 | mean | min | passed |
|---|---|---|---|---|---|---|---|---|
| minimal_baseline | +2.11 | +1.98 | -1.08 | +2.48 | +2.66 | +1.63 | -1.08 | FAIL |
| minimal_baseline_v2 | +2.56 | +2.34 | +1.62 | +2.39 | +2.06 | +2.19 | +1.62 | PASS |
| minimal_baseline_v3 | +2.93 | +1.12 | +1.22 | +1.86 | +0.83 | +1.59 | +0.83 | PASS |

## Walk-forward folds (return %)

| Strategy | fold 0 | fold 1 | fold 2 | fold 3 | fold 4 | min DD across folds |
|---|---|---|---|---|---|---|
| minimal_baseline | +16.93% | +14.16% | -6.58% | +16.35% | +21.09% | -11.00% |
| minimal_baseline_v2 | +22.99% | +16.62% | +11.21% | +12.77% | +11.89% | -8.75% |
| minimal_baseline_v3 | +22.34% | +11.41% | +9.30% | +8.75% | +5.15% | -13.30% |

## Concentration sensitivity (top-5 winners removed)

| Strategy | Headline Sharpe | Stripped Sharpe | Sharpe drop | Top-5 % of P&L | Verdict (drop ≤ 0.4) |
|---|---|---|---|---|---|
| minimal_baseline | +2.36 | +1.23 | +1.13 | 50.41% | FAIL |
| minimal_baseline_v2 | +1.64 | +0.49 | +1.15 | 73.80% | FAIL |
| minimal_baseline_v3 | +0.55 | -0.42 | +0.96 | 148.96% | FAIL |

## Benchmarks

- **Equal-weight universe (buy-and-hold all 970 tickers in the snapshot at window start, no rebalance)**: total return +39.27%, ann Sharpe 1.07
- **SPY total return (matched window)**: +45.16%

## Yearly breakdown (trades by exit year)

| Year | minimal_baseline | minimal_baseline_v2 | minimal_baseline_v3 |
|---|---|---|---|
| 2024 | n=66 win=39.4% avg=+3.92% P&L=$2357 | n=66 win=47.0% avg=+5.12% P&L=$3031 | n=72 win=45.8% avg=+3.48% P&L=$2240 |
| 2025 | n=138 win=35.5% avg=+1.54% P&L=$2031 | n=149 win=42.3% avg=+3.42% P&L=$4647 | n=120 win=36.7% avg=+3.77% P&L=$4214 |
| 2026 | n=82 win=50.0% avg=+6.08% P&L=$4322 | n=95 win=41.1% avg=+4.37% P&L=$3643 | n=72 win=40.3% avg=+2.80% P&L=$1493 |

## Data quality

- minimal_baseline: pipeline `2026-05-15-survivorship-haircut`, survivorship `haircut_estimated`
- minimal_baseline_v2: pipeline `2026-05-15-survivorship-haircut`, survivorship `haircut_estimated`
- minimal_baseline_v3: pipeline `2026-05-15-survivorship-haircut`, survivorship `haircut_estimated`

## Provenance per strategy

| Strategy | snapshot_id | git_sha | regime |
|---|---|---|---|
| minimal_baseline | `1dd88cad8e1f7534` | `57ebf0d` | off |
| minimal_baseline_v2 | `1dd88cad8e1f7534` | `15b7ddc` | off |
| minimal_baseline_v3 | `1dd88cad8e1f7534` | `15b7ddc` | off |