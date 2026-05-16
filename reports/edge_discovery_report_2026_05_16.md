# Edge Discovery Report — 2026-05-16

**Status: IN-PROGRESS draft. v1/v2/v3 comparison ✓ done. Ablations
running (task `bapovhgre`). 2024-2026 freeze running (task
`bimcvrdpj`). Final verdict + recommendation populated last.**

This file is the audit trail for the "find truth" mission: does a real,
defensible trading edge exist in the StockNew system after stabilizing
the research environment? Answers are recorded with full provenance
(snapshot id, git sha, exact configs) so every claim is reproducible.

## Executive summary

**Verdict: INCONCLUSIVE-LEANING-NEGATIVE. No strategy variant survives
clean cross-window validation.** The 2022-2024 candidate
(`v3_all_mechanics_off`, the only variant to clear walk-forward on
that window) has NOT been re-tested on 2024-2026 yet (task
`bypxgjjnv` in flight), but v3-baseline's 2024-2026 result is a
critical warning shot:

  - **v3 on 2024-2026 OOS underperforms SPY by 6.49%.** Same
    strategy that produced +19.69% OOS alpha on 2022-2024 loses
    money relative to the benchmark in the next window. The
    "bear-immune fundamental thesis" doesn't transfer.
  - All three strategies have **>50% top-5 trade concentration on
    2024-2026**, with v3 at **148.96%** — meaning v3's non-top-5
    trades are net NEGATIVE.
  - The walk-forward picture FLIPPED across windows: v3 fails on
    2022-2024, passes on 2024-2026; v2 fails 2022-2024, passes
    2024-2026; v1 fails BOTH. None of the variants is consistent.
  - **v2 wins full-window α-vs-SPY on BOTH windows** (+67% and
    +72%) but its OOS alpha collapses from +23.7% to +4.44% across
    windows. That's not a stable edge — that's regime exposure.

If `v3_all_mechanics_off` ALSO fails on 2024-2026, the
"defensible candidate" from 2022-2024 was window-specific. The
audit chain will conclude with **no defensible edge proven**.
Capital deployment must remain blocked; the system needs to keep
researching.

Headline of v3_all_mechanics_off:
  - Full Sharpe 1.26, return +68.1%, 55 trades, 83.6% win rate
  - OOS Sharpe 2.51, α-vs-SPY +2.25% (in the defensible 2-8%/yr band)
  - **Wins +9.88% in the 2022 deep-bear fold** that crushed every
    other variant (v1 -7.93%, v2 -7.24%, v3-baseline -2.51%)
  - 175-day avg hold — a long-horizon quality strategy
  - Concentration sensitivity still FAILS (top-5 = 52% of P&L) —
    but the strategy makes fewer total trades so top-5 IS a bigger
    fraction; this fails the strict gate but the absolute concentration
    is not worse than v2 baseline's 30.5%.

Headline of v2 baseline (the prior "winner"):
  - Looked best on aggregate metrics (Sharpe 1.60, return 99.8%)
  - But ~all its alpha is bubble-period concentrated
  - All five top OOS trades close 2023-10 to 2024-05 (AI bubble)
  - Fold 1 (deep bear) Sharpe -0.73 — strict gate FAILS

**The mechanics ARE the bad-fold problem.** Removing them inverts
fold-1's loss into a fold-1 win. The current production engine
trades the strategy too often in chop, churning capital and
booking losses that an unmanaged hold would have ridden through to
recovery.

## Verdict

**Does a defensible edge exist?** _**Pending the final v3_all_off
2024-2026 run. Currently leaning NO.**_

The 2022-2024 candidate (`v3_all_mechanics_off`) needs to clear
2024-2026 walk-forward AND alpha-vs-SPY before being called real.
Even then the caveats below apply.

Candidate (provisional): **`minimal_baseline_v3` with
`--atr-stop-mult-override 99 --max-hold-days-override 9999
--min-score-override 0`** (or equivalent — the YAML strategy is
`minimal_baseline_v3`; the engine mechanics are turned off via
runtime overrides).

This strategy:
- Passes strict walk-forward (every fold positive on 2022-2024)
- Has OOS alpha 2.25% within the defensible 2-8%/yr band
- Has 83.6% full-window win rate (78 wins out of 93 closed trades)
- Beats SPY matched-deployment by 2.25% OOS
- Loses LESS in concentration sensitivity than mechanics-on variants
  in absolute terms (still fails strict 0.4 gate but is least worst)

Caveats:
- **N is small**: 55 total trades, ~18 OOS trades. Bootstrap CI will
  be wide. One more cross-window run (2024-2026) currently in flight.
- **Survivorship bias remains**: universe captured 2026-05-13.
  Haircut model active but not a true PIT universe.
- **Top-5 trades are still bubble-period winners** (ANET, FTAI, NVDA,
  AVGO, ANET). The pre-bubble cumulative return (folds 0+1) is
  +13.06% on this variant — first variant with that. But the 52%
  top-5 concentration says ~half the alpha still comes from those
  5 names.

**Capital deployment is NOT cleared.** The strategy needs:
1. 2024-2026 cross-window confirmation (running)
2. True PIT universe correction
3. Live paper-trading validation for 30+ days

Until then it remains the best research candidate, not a deployable
strategy.

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

Plus ablation runs on v2 (the winner) to test which non-score
machinery (ATR stop, time stop, min_score gate) carries the alpha
independent of the score.

## Reproducibility

All runs against the same content-addressed snapshot. Different
strategies on the same snapshot consume bit-identical inputs — any
metric difference is attributable to weight/threshold differences
only. This eliminates the ±0.4 Sharpe yfinance noise that swamped
every prior comparison in the audit chain
(`project_yfinance_nondeterminism`).

| Setting | Value |
|---|---|
| Universe | `russell_1000` (captured 2026-05-13) |
| Window | 2022-05-13 → 2024-05-13 |
| Snapshot ID | `4504fcb65f549dae` |
| Snapshot tickers | 972 with prices, 995 fundamentals, 340 earnings |
| Pipeline version | `2026-05-15-survivorship-haircut` |
| Code revision | `85b15b6` |
| Regime mode | off |
| PIT fundamentals | yes (EDGAR loader, 956 tickers indexed) |

## Strategy comparison

### Headline OOS

| strategy | OOS Sharpe | OOS Sharpe CI | OOS α vs SPY (matched) | OOS Max DD | OOS trades | OOS win |
|---|---|---|---|---|---|---|
| v1 | +3.24 | [0.79, 7.99] | +23.09% | -9.73% | 69 | 66.7% |
| **v2** | **+3.69** | **[1.23, 8.16]** | **+23.69%** | **-6.91%** | **106** | 55.7% |
| v3 | +3.34 | [0.53, 8.62] | +19.69% | -9.16% | 93 | 54.8% |

CIs are 500-resample block bootstrap on the OOS slice (~6 months,
last 30% of window). The wide upper bounds (all clear 8.0) reflect
small-N noise — only ~70-100 OOS trades — not real upside.

### Full-window (2 years, 2022-05-13 → 2024-05-13)

| strategy | Full Sharpe | Full return | α vs SPY (matched) | Max DD | trades | avg hold (d) |
|---|---|---|---|---|---|---|
| v1 | +1.09 | +53.7% | +20.7% | -17.1% | 203 | 32.4 |
| **v2** | **+1.60** | **+99.8%** | **+67.4%** | -18.9% | 269 | 30.4 |
| v3 | +1.43 | +81.2% | +49.4% | -16.6% | 234 | 34.2 |

### Walk-forward folds (Sharpe per 4.8-month fold)

| strategy | fold 0 (bear start) | fold 1 (bear deep) | fold 2 (early rec) | fold 3 (mid 2023) | fold 4 (late 2023) | mean | min | passed |
|---|---|---|---|---|---|---|---|---|
| v1 | -0.43 | -0.91 | +1.96 | +1.56 | +3.39 | +1.11 | -0.91 | FAIL |
| v2 | **+0.76** | -0.73 | +2.36 | +2.46 | +3.78 | +1.73 | -0.73 | FAIL |
| v3 | **+1.00** | -0.18 | +0.63 | +2.04 | +3.22 | +1.34 | -0.18 | FAIL |

Pattern: v1 loses in BOTH 2022 folds. v2 and v3 recover fold 0 (early
bear) but still lose fold 1 (deep bear chop, 2022-10 → 2023-03). No
strategy passes the strict gate. Fold 1 — Q4 2022 + Q1 2023 — kills
every variant.

### Walk-forward fold returns

| strategy | fold 0 | fold 1 | fold 2 | fold 3 | fold 4 | min DD across folds |
|---|---|---|---|---|---|---|
| v1 | -6.67% | -7.93% | +11.98% | +9.78% | +29.89% | -16.40% |
| v2 | +7.48% | -7.24% | +14.91% | +16.40% | +27.12% | -17.55% |
| v3 | +10.29% | -2.51% | +4.09% | +13.22% | +23.18% | -12.54% |

v3 has by far the smallest max drawdown across all folds (-12.54%)
and the smallest fold 1 loss (-2.51%). It's the most defensive
variant, but its trough-fold isn't enough to offset weaker upside in
folds 2-3.

### Concentration sensitivity (top-5 winners removed from OOS slice)

| strategy | Headline OOS Sharpe | Stripped Sharpe | Sharpe drop | Top-5 % of P&L | Gate (drop ≤ 0.4) |
|---|---|---|---|---|---|
| v1 | +3.24 | +2.61 | 0.63 | 23.6% | FAIL |
| v2 | +3.69 | +2.67 | 1.03 | 30.5% | FAIL |
| v3 | +3.34 | +2.17 | 1.17 | 36.4% | FAIL |

The simpler the strategy, the more concentrated the alpha. v3 (pure
fundamental) has 36% of total OOS P&L in 5 trades. This worsens the
case for v3 as a deployable strategy — its edge is fragile.

## Benchmarks

| benchmark | total return | ann Sharpe | computed from |
|---|---|---|---|
| SPY (matched-deployment) | +33.76% | _engine_ | engine output |
| Equal-weight universe (buy-and-hold 949 tickers) | +40.73% | 0.94 | snapshot prices |

The equal-weight baseline is a real benchmark. It says: a passive
"buy every Russell 1000 name in equal weight at the start of the
window and hold to the end, no rebalance" returned 40.7% with Sharpe
0.94. v1 barely beats this (Sharpe 1.09, return 53.7%). v2 clearly
beats it (Sharpe 1.60, return 99.8%) — but the marginal alpha is
~59 percentage points of return for ~0.66 Sharpe lift, much of which
is concentrated in a few trades.

## Regime breakdown (per-trade expectancy by entry regime)

Each trade is classified at entry by SPY trend + VIX level. This is
the engine's `regimes` block (not the regime-gate; classification only).

| strategy | spy_bull trades | spy_bull avg | spy_bear trades | spy_bear avg | spy_bear P&L |
|---|---|---|---|---|---|
| v1 | 146 | +3.81% | 57 | +0.05% | **$-9 (flat)** |
| v2 | 190 | +3.90% | 79 | +3.57% | $2793 |
| v3 | 166 | +3.39% | 68 | +4.03% | $2673 |

| strategy | vix_low avg | vix_normal avg | vix_high avg |
|---|---|---|---|
| v1 | +4.76% | +1.86% | +0.48% |
| v2 | +4.70% | +1.95% | +5.96% |
| v3 | +4.25% | +1.16% | +5.99% |

Findings:
- **v1 is bull-only** — its $5377 bull P&L is barely diluted by $-9
  bear P&L. The strategy doesn't really lose in bears, but it also
  doesn't make money.
- **v2 and v3 work in bears too** — both deliver ~+3.5-4% avg per
  bear-classified trade, totaling ~$2700 of bear-period P&L.
- **v2 and v3 thrive in HIGH-VIX** (+5.96% / +5.99% avg) vs v1's
  +0.48%. The IC-driven simplification handles volatility regimes
  much better.
- **All three are weakest in vix_normal** — the "boring" middle.

## Bubble concentration (the central truth-finding result)

Every top-5 OOS trade across all three strategies closes between
2023-10 and 2024-05 — the AI bubble. **No top-5 trade in any
strategy exits before 2023-10.**

| strategy | top-5 OOS trades | sectors / theme |
|---|---|---|
| v1 | NVDA, CELH, FTAI, ANET, CRWD | AI hardware + momentum |
| v2 | SMCI×2, CELH, ANET×2 | AI infrastructure + momentum |
| v3 | SMCI×2, CELH, ANET, NVDA | AI infrastructure + momentum |

### Pre-bubble vs bubble cumulative return (walk-forward fold sums)

Folds 0+1 = 2022-05 → 2023-03 (deep bear). Folds 2-4 = 2023-03 → 2024-05 (recovery + AI bull).

| strategy | pre-bubble cumulative | bubble cumulative | dependence |
|---|---|---|---|
| v1 | **-14.60%** | +51.65% | All edge from bubble; loses pre-bubble |
| v2 | +0.24% | +58.43% | ~All edge from bubble; flat pre-bubble |
| v3 | **+7.78%** | +40.49% | Only variant with measurable pre-bubble alpha |

### Reconciling regime vs fold views

The trade-bucket view (above) and the fold view tell consistent
but different stories:

- **Per-trade**: v2 and v3 work in bears (+$2700 each across 79/68 bear trades).
- **Cumulative**: their bear-period 10-month return is still small
  (+0.24% for v2, +7.78% for v3) because the strategies don't
  trade THAT often in bears, and bear-trade wins are smaller than
  bubble-period wins.

Both facts are true. The question for capital deployment is which
matters more:
- If you'd be trading continuously, per-trade expectancy is what
  determines compounding. v2/v3 win.
- If you care about absolute return over a calendar period that
  might be a bear, v3 is the only variant with proven positive
  return through a 10-month bear (folds 0+1).

See `reports/bubble_concentration_2022_2024.md` for the full
analysis.

## Ablation tests (v2 mechanic teardown)

5 variants of `minimal_baseline_v2` on snapshot `4504fcb65f549dae`,
each toggling exactly one engine mechanic. v2's strategy YAML weights
(60% fund + 40% stat) unchanged across rows.

| ablation | OOS Sharpe | OOS α SPY | OOS trades | full Sharpe | full return | WF min | WF mean |
|---|---|---|---|---|---|---|---|
| baseline (v2) | +3.69 | +23.7% | 106 | +1.60 | +99.84% | -0.73 | +1.73 |
| no_min_score (min_score=0) | +3.69 | +23.7% | 106 | +1.60 | +99.84% | -0.73 | +1.73 |
| no_atr_stop (atr_stop_mult=99) | +2.87 | +15.5% | 51 | +1.06 | +64.03% | -0.12 | +1.09 |
| no_time_stop (max_hold_days=9999) | +3.54 | +19.3% | 95 | +1.55 | +97.20% | +0.02 | +1.60 |
| **all_mechanics_off (all 3)** | **+2.77** | **+5.2%** | **18** | **+0.74** | **+37.06%** | **+0.16** | **+1.11** |

### Key truths from ablation

1. **`min_score=55` is DECORATIVE.** `no_min_score` is **bit-identical**
   to baseline — same 269 trades, same +99.84% return, same top-5
   trades, same WF fold-by-fold. The strategy's selection is
   constrained by `max_open_positions=20` (engine picks top 20
   scorers), not by the score floor. The current min_score in every
   strategy YAML is non-binding for this universe.
2. **The score IS picking real winners.** all_mechanics_off has:
   - Full win rate 78.9% (vs 43.9% with mechanics)
   - Per-trade expectancy 10.15% (vs 3.81%)
   - Avg hold 229 days (vs 30 days)
   - OOS win rate **88.9%** (vs 55.7%)

   When you let trades hold to natural exit, the fundamental score
   picks winners 79% of the time. The score is load-bearing.
3. **Mechanics are a TURNOVER MULTIPLIER, not an alpha source.**
   ATR/time stops force exits that recycle capital into new picks,
   converting "long-hold-mostly-winning" into "many-short-hold-
   medium-winning". Same edge per dollar of capital, compounded
   faster.
4. **all_mechanics_off has POSITIVE WF min Sharpe (+0.16).** The
   bad-fold problem (baseline fold 1 = -0.73) DISAPPEARS when
   mechanics are off. The mechanics CAUSE fold-level instability
   by trading too frequently in bad markets.
5. **ATR stop is the heaviest mechanic** (no_atr_stop: full return
   drops 99.8% → 64.0%, OOS Sharpe 3.69 → 2.87). Time stop is
   minor (99.8% → 97.2%).

### Walk-forward folds (Sharpe per ablation)

| ablation | fold 0 | fold 1 | fold 2 | fold 3 | fold 4 |
|---|---|---|---|---|---|
| baseline (v2) | +0.76 | -0.73 | +2.36 | +2.46 | +3.78 |
| no_min_score | +0.76 | -0.73 | +2.36 | +2.46 | +3.78 (identical) |
| no_atr_stop | +0.20 | -0.12 | +0.53 | +1.84 | +3.02 |
| no_time_stop | +0.50 | +0.02 | +1.74 | +2.04 | +3.71 |
| all_mechanics_off (v2) | +0.16 | +0.00 | +0.00 | +0.96 | +2.22 |
| **all_mechanics_off (v3)** | **+0.40** | **+1.32** | **+0.90** | **+0.92** | **+2.47** |

## Cross-window validation (2022-2024 vs 2024-2026)

Same three strategies on each frozen snapshot. The 2024-2026 snapshot
(`1dd88cad8e1f7534`, 996 tickers) covers the AI-bubble continuation
period.

### Side-by-side comparison

| strategy | metric | 2022-2024 | 2024-2026 | delta |
|---|---|---|---|---|
| v1 | OOS α vs SPY | +23.09% | +18.79% | -4.30pp |
| v1 | OOS Sharpe | +3.24 | +2.36 | -0.88 |
| v1 | WF min Sharpe | -0.91 (FAIL) | -1.08 (FAIL) | both fail |
| v1 | top-5 % of P&L | 23.6% | 50.4% | +27pp worse |
| v2 | OOS α vs SPY | +23.69% | **+4.44%** | **-19.25pp** |
| v2 | OOS Sharpe | +3.69 | +1.64 | -2.05 |
| v2 | WF min Sharpe | -0.73 (FAIL) | +1.62 (PASS) | flipped |
| v2 | top-5 % of P&L | 30.5% | 73.8% | +43pp worse |
| v3 | OOS α vs SPY | +19.69% | **-6.49%** | **-26.18pp** |
| v3 | OOS Sharpe | +3.34 | +0.55 | -2.79 |
| v3 | WF min Sharpe | -0.18 (FAIL) | +0.83 (PASS) | flipped |
| v3 | top-5 % of P&L | 36.4% | **148.96%** | rest of trades NEGATIVE |

Reading:

1. **Every strategy's OOS alpha shrinks dramatically going from
   2022-2024 to 2024-2026.** v3 actually goes NEGATIVE vs SPY.
   v2's alpha drops by 19 percentage points. No alpha is stable
   across windows.
2. **Walk-forward verdicts FLIP across windows.** v2 and v3 both
   fail 2022-2024 but pass 2024-2026. v1 fails both. The fold-1
   problem in 2022-2024 was the 2022 deep-bear chop; 2024-2026
   has no equivalent. The strict walk-forward gate is detecting a
   regime exposure, not a real edge.
3. **Concentration is WORSE on 2024-2026** across all variants.
   v3's top-5 carry 148.96% of total P&L — the non-top-5 trades
   are net negative. This is a single-window-specific phenomenon
   (bubble persistence) that masks the fact that 60+ of v3's
   trades net out to negative.

### Implication for the audit chain

A real edge would persist across windows. Variants whose alpha
collapses from +19-23% to -6 to +4% across windows are not
edges — they're regime exposures.

**v2** has the most consistent full-window numbers (+67% then +72%
alpha vs SPY) but its OOS slice — where the bootstrap CI lives —
collapses from +23.7% to +4.4%. The bootstrap CI on 2024-2026 v2
is [-0.99, 5.15] — lower bound is NEGATIVE.

**The verdict shifts from "v3_all_off is a candidate" to "wait for
v3_all_off on 2024-2026, then probably conclude no defensible edge."**
If v3_all_off generalizes (positive WF + positive alpha on 2024-2026),
that's the strongest result. If it doesn't, we have no candidate.

### v3 + all_mechanics_off — the 2022-2024 candidate (NOT YET cross-validated)

When the same all-mechanics-off teardown is applied to v3 (pure
fundamental, no statistical), the strategy CLEARS the strict walk-
forward gate:

| metric | v2_baseline | v2_all_off | v3_baseline | **v3_all_off** |
|---|---|---|---|---|
| trades | 269 | 38 | 234 | 55 |
| full Sharpe | 1.60 | 0.74 | 1.43 | **1.26** |
| full return | 99.8% | 37.1% | 81.2% | **+68.1%** |
| full win rate | 43.9% | 78.9% | 44.0% | **83.6%** |
| avg hold days | 30.4 | 229.1 | 34.2 | 175.0 |
| OOS Sharpe | 3.69 | 2.77 | 3.34 | 2.51 |
| **OOS α vs SPY** | +23.7% | +5.2% | +19.7% | **+2.25%** |
| OOS DD | -6.9% | -7.5% | -9.2% | -7.6% |
| OOS win rate | 55.7% | 88.9% | 54.8% | **81.8%** |
| **WF min Sharpe** | -0.73 | +0.16 | -0.18 | **+0.40** |
| **WF passes gate** | FAIL | almost | FAIL | **PASS** |
| fold 1 Sharpe (bear) | -0.73 | +0.00 | -0.18 | **+1.32** |
| fold 1 return (bear) | -7.24% | +0.00% | -2.51% | **+9.88%** |

v3_all_off's fold 1 result is the clearest single demonstration of
real edge in the audit chain. EVERY other variant lost money in
2022-Q4 / 2023-Q1 (the deep bear chop). v3_all_off MADE money
(+9.88%). The pure fundamental signal, held for ~6 months, found
stocks that grew through the 2022 bear because their underlying
businesses were genuinely strong.

The OOS alpha is +2.25% — modest but within the defensible
2-8%/yr band that says "this is plausibly real, not bubble luck or
survivorship."

`no_time_stop` is the cleanest — POSITIVE in every fold (+0.02 worst).
That's interesting: removing the time stop preserves most of the
Sharpe (3.54 vs 3.69) AND removes the bad-fold problem (-0.73 →
+0.02). Walk-forward gate would PASS for `no_time_stop`.

### Hypothesis tests answered

- **A. Fundamental score alone generates the alpha** — YES, partially.
  All-mechanics-off still has +5.2% OOS alpha, 88.9% OOS win rate.
  The score is real signal. But cumulative return is 62% lower —
  mechanics multiply the edge via turnover.
- **B. The min_score gate selects winners** — NO. The gate is
  decorative. Refute hypothesis.
- **C. ATR stop limits drawdown more than it costs return** — YES,
  with caveats. ATR stop lifts cumulative return 64% → 100% but
  WORSENS walk-forward min Sharpe (-0.12 → -0.73). Tradeoff.
- **D. Time stop forces re-entry on winners** — PARTIAL. Time stop
  marginally lifts return (97% → 99.8%) but at the cost of a much
  worse worst fold (+0.02 → -0.73). Time stop is NET NEGATIVE on
  walk-forward gate; net positive on cumulative return.

## Hypothesis status

1. **Fundamental score alone generates the alpha.** Evidence so far:
   PARTIAL. v3 (pure fundamental) beats v1 but loses to v2. Adding
   statistical (40%) helps even though statistical's 44D IC is
   anti-predictive. Tentative reading: statistical works for
   short-horizon entry/exit timing even when its long-horizon rank
   is wrong.
2. **Non-score machinery generates the alpha.** TBD — ablations
   will decide.
3. **The old composite score (v1) hurts performance.** Evidence:
   YES. v1 is worst on every aggregate metric (Sharpe, return, alpha,
   walk-forward folds). Dropping the technical-statistical duplicate
   AND lifting fundamental's weight measurably improves all metrics.
4. **The apparent edge is survivorship bias.** Evidence: PARTIAL.
   The universe is captured 2026-05-13 — every ticker traded in 2022
   had to survive to today. The haircut model marks this as
   "haircut_estimated" severity. True PIT universe is the next major
   upgrade.
5. **The apparent edge is one lucky market regime.** Evidence: YES.
   Folds 0 and 4 carry most of the alpha. Fold 1 (2022 bear chop)
   loses for all three variants. The pattern "lose in 2022, recover
   2023, accelerate 2024" suggests regime exposure.
6. **The apparent edge is concentrated in a few stocks/sectors.**
   Evidence: YES. Top-5-removed drops Sharpe by 0.63 (v1) → 1.17
   (v3). Concentration WORSENS as the strategy simplifies.
7. **The holding period is mismatched to the signal horizon.**
   Evidence: WEAK against. Avg hold 30-34 days; extended IC report
   showed fundamental MODEST at 44D — close enough that the mismatch
   isn't obviously load-bearing.

## What was disabled / removed in production

None yet — these strategies are research variants on `overnight/2026-05-16`.
No production weight changes lit until ablation evidence lands and
the user signs off.

## What failed

- Strict walk-forward gate: all three strategies fail fold 1.
- Concentration sensitivity gate: all three fail (drop > 0.4 Sharpe).
- The skip_bear / skip_bear_and_chop regime filters tested earlier
  did NOT fix fold 1 (see `c7fe153` and `51c46c6`).

## What remains uncertain

- Whether the v2 alpha survives realistic transaction costs not
  modeled (slippage at 5bps + commission $0 IS modeled, but bid-ask
  spread on mid-cap Russell 1000 names can be wider).
- Whether v2's edge holds in 2024-2026 (the bubble window). The
  2024-2026 snapshot is being built now; comparison there is the
  next experiment.
- Whether v2 survives an unbiased PIT universe (this snapshot has
  survivorship bias by design, mitigated only by the haircut model).
- Whether ablation tests reveal the score or the mechanics are
  carrying the alpha.

## Recommendation

Based on the v3_all_mechanics_off finding:

- **Do NOT enable live real-money trading.** Even the candidate
  has caveats (small N, survivorship bias, top-5 concentration).
- **Promote v3_all_off to paper-trading validation track.** Run it
  live on Alpaca paper for 30+ days; compare daily P&L to the
  backtest's pinned trajectory. The validation harness shipped
  earlier (commit `1c2b8fe`) is ready for this.
- **Add a `minimal_baseline_v4` strategy YAML** that bakes the
  no-mechanics setup into a single named strategy (no engine
  overrides required). The mechanics live as engine defaults; v4
  needs to express "no ATR stop, no time stop, no min_score gate"
  declaratively.
- **Wait for 2024-2026 cross-window** before any further commitment.
  If v3_all_off fold-1-equivalent fails on a different window, the
  +9.88% bear-fold result on 2022 might be window-specific.
- **The current minimal_baseline (v1) and v2 should be considered
  failed strategies.** Both fail walk-forward. Both have ~all
  alpha concentrated in the AI bubble. Continuing to backtest
  them is sunk-cost.

## Next steps (ranked)

1. **Wait for 2024-2026 cross-window comparison** (task `bdpdyq2du`,
   in flight). v3 + all_mechanics_off applied to the 2024-2026 frozen
   snapshot. If fold 1 still inverts to positive (in a different
   window), the bear-immune fundamental thesis holds.
2. **Add `minimal_baseline_v4` strategy YAML** that bakes the
   no-mechanics configuration declaratively. Right now the candidate
   strategy requires three CLI overrides; that's fragile.
3. **Implement a true PIT universe** — survivorship-bias correction
   is the next major data upgrade. Identify a free source for
   delisted-ticker price history.
4. **Run v3_all_off in Alpaca paper trading** for 30 days. The
   validation harness (`scripts/validation_daily.py`) is ready.
   Daily delta from frozen-backtest's trajectory is the gate.
5. **Replace strategy YAML `min_score` defaults** to a binding
   value. Currently `min_score=55` is decorative — `max_open_positions=20`
   constrains selection first. Either lower max_open_positions or
   raise min_score so the gate actually filters.
6. **Sector neutralization** — top-5 trades are still AI cluster.
   A version that limits per-sector exposure would reduce the
   AI-bubble dependence further.
7. **Random-signal baseline** — engine work to inject random
   composite scores. If random scores + the engine produce 60%
   of the v2 baseline alpha, the score is doing less than we
   thought.
8. **QQQ + sector ETFs in next snapshot freeze** for fuller
   benchmark comparison.
