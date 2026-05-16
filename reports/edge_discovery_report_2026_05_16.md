# Edge Discovery Report — 2026-05-16

**Status: IN-PROGRESS draft. v1/v2/v3 comparison ✓ done. Ablations
running (task `bapovhgre`). 2024-2026 freeze running (task
`bimcvrdpj`). Final verdict + recommendation populated last.**

This file is the audit trail for the "find truth" mission: does a real,
defensible trading edge exist in the StockNew system after stabilizing
the research environment? Answers are recorded with full provenance
(snapshot id, git sha, exact configs) so every claim is reproducible.

## Executive summary

On a single frozen snapshot of 2022-2024 Russell 1000 data, the
strategy `minimal_baseline_v2` (60% fundamental + 40% statistical,
technical dropped because of the 0.73 correlation duplicate) is the
empirical winner across every aggregate metric (OOS Sharpe 3.69,
α-vs-SPY +23.7% matched, max DD -6.9%, 106 OOS trades, win rate
55.7%). v3 (100% fundamental) is the IC-theory pick but underperforms
v2 in practice. v1 (current production) is third on every metric.

**But:**

- All three strategies FAIL the strict walk-forward gate because of
  fold 1 (2022-10 → 2023-03, deep-bear chop). Every variant lost
  money in that fold.
- All three FAIL the top-5-removed concentration sensitivity gate:
  removing the 5 best trades drops the OOS Sharpe by 0.63 / 1.03 /
  1.17 respectively. The edge is meaningfully concentrated.
- v2's OOS Sharpe CI is [1.23, 8.16] — the lower bound clears the
  "demonstrably above noise" 0.7 floor, but the spread is unrealistic
  (no real strategy has a true Sharpe band that wide; it's a small-N
  artifact — only 106 OOS trades).
- Equal-weight buy-and-hold of all 949 tickers in the snapshot
  returns +40.7% over the window with Sharpe 0.94. v1 only beats
  this by 13 percentage points of return and v1's Sharpe is barely
  higher (1.09 vs 0.94). Without v2's lift, the system barely
  justifies the operational cost.

## Verdict

**Does a defensible edge exist?** _**Inconclusive — leaning toward
yes for v2 with major caveats**_.

The numerical signal is positive (v2 beats every benchmark on every
aggregate metric), but the strict gates (walk-forward, concentration)
fail. Capital deployment is NOT justified yet. Ablation tests
(in flight) will decide whether the apparent v2 alpha is real or is
just non-score mechanics.

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
| baseline | +0.76 | -0.73 | +2.36 | +2.46 | +3.78 |
| no_min_score | +0.76 | -0.73 | +2.36 | +2.46 | +3.78 (identical) |
| no_atr_stop | +0.20 | -0.12 | +0.53 | +1.84 | +3.02 |
| no_time_stop | +0.50 | +0.02 | +1.74 | +2.04 | +3.71 |
| all_mechanics_off | +0.16 | +0.00 | +0.00 | +0.96 | +2.22 |

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

## Recommendation (placeholder until ablations land)

Based on what we have so far:
- **Do NOT enable live trading.** Walk-forward fail + concentration
  fail = no defensible edge by the strict gates.
- **Continue researching v2 as the working theory.** It's the
  empirical best; the IC-theory rationale is partly confirmed
  (dropping the 0.73-correlated duplicate helped) and partly refuted
  (v3 didn't dominate v2).
- **Wait for ablation results** before assigning the alpha to
  "score" vs "machinery".
- **2024-2026 snapshot is being built** for an out-of-bubble
  validation pass.

## Next steps (ranked)

1. (running) Ablation suite on v2 — answer hypothesis B before any
   bigger investment.
2. (running) Build 2024-2026 snapshot — re-run v1/v2/v3 there for
   the cross-window check.
3. Implement a true PIT universe (delisted tickers re-added) — only
   way to put a credible ceiling on the v2 alpha number.
4. Sector concentration analysis — which sectors carry the top-5
   trades? If they're all one sector (e.g. tech) the strategy's
   edge is really a sector bet.
5. QQQ benchmark — add to the next snapshot freeze for completeness.
6. Random-signal baseline — requires engine support but would tell
   us if the mechanics + universe alone deliver the apparent alpha
   regardless of the score.
