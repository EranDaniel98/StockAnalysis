# Bubble-concentration analysis — 2022-2024 frozen snapshot

Generated 2026-05-16. Snapshot `4504fcb65f549dae`. Strategies: v1, v2, v3.

## Headline

**Every top-5 OOS trade across all three strategies closes between
2023-10 and 2024-05** — the AI bubble run. The strategies' apparent
edge is heavily regime-dependent. v2's "winning" status on aggregate
OOS metrics is almost entirely AI-bubble exposure.

## Top-5 OOS trades by strategy

| strategy | top-5 % of OOS P&L | trades (all close in AI-bubble period) |
|---|---|---|
| v1 | 23.6% | NVDA, CELH, FTAI, ANET, CRWD |
| v2 | 30.5% | SMCI×2, CELH, ANET×2 |
| v3 | 36.4% | SMCI×2, CELH, ANET, NVDA |

Overlapping winners across all three: **SMCI**, **CELH**, **ANET**,
**NVDA**. These are AI infrastructure + momentum names. No top-5
trade in any strategy exits before 2023-10.

## Pre-bubble vs bubble cumulative return (walk-forward folds)

Folds 0+1 = 2022-05 → 2023-03 (pre-bubble: bear + bear-chop).
Folds 2-4 = 2023-03 → 2024-05 (bubble: recovery, AI heat, AI bubble).

| strategy | pre-bubble cumulative | bubble cumulative | bubble/pre ratio |
|---|---|---|---|
| v1 | **-14.60%** (loses) | +51.65% | 3.5x in magnitude |
| v2 | **+0.24%** (flat) | +58.43% | 240x (~zero baseline) |
| v3 | **+7.78%** | +40.49% | 5.2x |

## Reading

1. **v1 loses pre-bubble, gains in bubble** — the technical/statistical
   weight (70% combined) gets chewed up in the 2022 bear. The bubble
   recovery overshoots and produces big gains. Pre-bubble, v1 has
   NEGATIVE edge.
2. **v2 is flat pre-bubble, massive in bubble** — dropping the
   technical/statistical duplicate stops v1's bleeding in 2022. But
   v2's apparent +58% bubble return is doing 99.6% of the cumulative
   work. Without a bubble window, v2's edge is approximately ZERO.
3. **v3 actually has pre-bubble alpha** (+7.78% over the worst 10
   months of 2022 → early 2023). It still gets pulled into the
   bubble (40% of cumulative return) but it's less bubble-dependent
   than v2 in proportion.

## What this means for the verdict

**v2's win-on-paper is a regime artifact.** It looks great on the
aggregate 2-year metrics because it didn't lose in 2022 AND it
caught the AI bubble. But its pre-bubble performance is zero, and
its top-5 trades are entirely AI-bubble winners.

**v3 (pure fundamental) is structurally more credible.** It's worse
on aggregate metrics BUT it has pre-bubble alpha (+7.78%), it's the
defensive strategy in fold 1 (-2.5% vs -7% for v1/v2), and its
fundamental-only construction has IC-theory backing at the
strategy's 44D hold horizon (Bonferroni-significant IC +0.041).

**The fundamental signal IS doing real work** — confirmed by v3's
pre-bubble alpha. But the "v2 has more alpha" claim is mostly
"v2 caught the AI bubble harder."

## Implications

1. **Reject the conclusion that v2 is best.** It's the empirical
   winner on this window because the window contains a bubble. On
   any window without a bubble, v2 would underperform v3.
2. **v3 (pure fundamental) is the safer working theory** going
   forward. It survives the worst pre-bubble period with positive
   alpha.
3. **The 2024-2026 cross-window test** is now critical. If v3 also
   has pre-bubble-style alpha in 2024-2026 (which has its own bubble
   tail), that supports the pure-fundamental thesis. If v3 collapses
   in 2024-2026, the 2022-2024 pre-bubble alpha was its own kind of
   regime luck.
4. **Ablation tests are even more interesting now** — if v2's
   "no_min_score" or "no_atr_stop" ablation preserves the bubble
   trades but loses the bubble alpha, the entry filters AREN'T
   the alpha source — selection is. If they're preserved, the
   filters were essentially neutral.

## Files

- Generator: ad-hoc inline analysis (not yet a script).
- Source data: `data/baseline/compare_minimal_baseline*.json` (all
  three strategies on snapshot `4504fcb65f549dae`).
- Walk-forward folds: `reports/strategy_comparison_2022_2024_frozen.md`
- Edge discovery report: `reports/edge_discovery_report_2026_05_16.md`
