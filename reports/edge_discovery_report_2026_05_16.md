# Edge Discovery Report — 2026-05-16

**Status: DRAFT — populated once v1/v2/v3 comparison + ablations complete.**

This file is the audit trail for the "find truth" mission: does a real,
defensible trading edge exist in the StockNew system after stabilizing
the research environment? Answers are recorded with full provenance
(snapshot id, git sha, exact configs) so every claim is reproducible.

## Executive summary

(Populated last — once all runs land.)

## Verdict

**Does an edge exist?** _Yes / No / Inconclusive_ → TBD

## What this report compares

Three strategy variants on identical frozen data:

- **`minimal_baseline_v1`** — current control. Weights:
  `technical 0.40 + fundamental 0.30 + statistical 0.30`.
- **`minimal_baseline_v2`** — IC-driven follow-up. Weights:
  `fundamental 0.60 + statistical 0.40` (drops technical, the
  0.73-correlated duplicate; lifts fundamental, the only
  Bonferroni-significant analyzer at the strategy's hold horizon).
- **`minimal_baseline_v3`** — extreme test. Weights:
  `fundamental 1.00`. The cleanest test of "is fundamental alone
  delivering the alpha?"

Plus ablation runs on the winner of v1/v2/v3 to test which non-score
machinery (ATR stop, time stop, min_score gate) carries the alpha
independent of the score.

## Reproducibility

All runs against the same content-addressed snapshot. Different
strategies on the same snapshot consume bit-identical inputs — any
metric difference is attributable to weight/threshold differences
only. This eliminates the ±0.4 Sharpe yfinance noise that swamped
every prior comparison in the audit chain.

| Setting | Value |
|---|---|
| Universe | `russell_1000` (captured 2026-05-13) |
| Window | 2022-05-13 → 2024-05-13 |
| Snapshot ID | `4504fcb65f549dae` |
| Snapshot tickers | 972 with prices, 995 fundamentals, 340 earnings |
| Pipeline version | `2026-05-15-survivorship-haircut` |
| Code revision | _populated at end-of-run_ |

## Strategy comparison

(See `reports/strategy_comparison_2022_2024_frozen.md` for the table —
this report embeds the headline numbers + interpretation.)

### Headline OOS

| strategy | OOS Sharpe (CI) | α vs SPY (matched) | Max DD | trades |
|---|---|---|---|---|
| v1 | TBD | TBD | TBD | TBD |
| v2 | TBD | TBD | TBD | TBD |
| v3 | TBD | TBD | TBD | TBD |

### Walk-forward folds

(TBD — fold-by-fold Sharpe + return across all three strategies.)

### Concentration sensitivity

(TBD — top-5-trades-removed Sharpe drop per strategy.)

### Yearly breakdown

(TBD — 2022 / 2023 / 2024 trade-return tallies per strategy.)

## Benchmarks

| benchmark | total return | ann Sharpe |
|---|---|---|
| SPY (matched) | TBD | TBD |
| Equal-weight universe (buy-and-hold 972 tickers) | TBD | TBD |

## Ablation tests

Which mechanic is doing the work? Run on the best of v1/v2/v3 with
individual mechanics disabled:

| ablation | OOS Sharpe | α vs SPY | trades |
|---|---|---|---|
| baseline | TBD | TBD | TBD |
| no ATR stop (atr_stop_mult=99) | TBD | TBD | TBD |
| no time stop (max_hold_days=9999) | TBD | TBD | TBD |
| no min_score gate (min_score=0) | TBD | TBD | TBD |
| all mechanics off | TBD | TBD | TBD |

## Hypothesis tests

Each from the user's "find truth" plan, mapped to the data:

1. **Fundamental score alone generates the alpha.** Evidence: TBD
2. **Non-score machinery generates the alpha.** Evidence: TBD
3. **The old composite score hurts performance.** Evidence: TBD
4. **The apparent edge is survivorship bias.** Evidence: TBD
5. **The apparent edge is one lucky market regime.** Evidence: TBD
6. **The apparent edge is concentrated in a few stocks/sectors.** Evidence: TBD
7. **The holding period is mismatched to the signal horizon.** Evidence: TBD

## What was disabled / removed

(TBD — analyzers / mechanics dropped in light of the evidence.)

## What failed

(TBD — runs that errored or returned non-meaningful results.)

## What remains uncertain

(TBD — open questions the data couldn't resolve.)

## Recommendation

(TBD — paper-only / tiny live capital / shut down / keep researching.)

## Next steps

(TBD — ranked TODO with rationale.)
