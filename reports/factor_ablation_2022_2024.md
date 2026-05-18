# Factor Ablation on 2022-2024 Stress Window — 2026-05-18

## Question

Which factor is dragging down the composite during 2022-2024?
The full `m+q+v+PEAD` blend at `d05_r63` returns -15.41% α vs SPY,
fails walk-forward (min Sharpe -2.10). Is there a single loser we
can drop or down-weight?

## Setup

Snapshot `234de3c737aa1eb2` (2022-05-13 to 2024-05-13, S&P 500 PIT
with 480 names). Same `d05_r63` configuration (top-decile 5%, monthly
rebalance counted as 21d here, but matched to the 63d cycle, etc.)
across all runs. Cost 5bp/side.

## Single-factor performance (each one alone)

| Factor alone   | α vs SPY  | WF mean | WF min | Passed |
|----------------|-----------|---------|--------|--------|
| value-only     | **+8.87%** | 1.05    | -1.36  | NO     |
| momentum-only  | -11.74%   | 0.46    | -2.01  | NO     |
| quality-only   | **-23.85%** | 0.21    | -2.52  | NO     |

Value was the only factor that beat SPY in this window. Quality
got crushed (-23.85%). Momentum was mid-table.

## Composite-minus-one ablation

| Configuration                        | α vs SPY    | WF mean | WF min |
|--------------------------------------|-------------|---------|--------|
| Full m+q+v+pead (baseline)           | -15.41%     | 0.47    | -2.10  |
| **m+q+v (drop PEAD)**                | **-11.63%** | 0.64    | -1.75  |
| q+v+pead (drop momentum)             | -11.88%     | 0.59    | -2.15  |
| m+v+pead (drop quality)              | -17.57%     | 0.37    | -1.78  |
| m+q+pead (drop value)                | -18.60%     | 0.54    | -1.51  |

The composite-ablation tells a DIFFERENT story than single-factor:

- **PEAD adds drag in 2022-2024.** Removing it improves α by +3.78pp.
  Cross-window PEAD remains a win (+2.53pp avg α per
  [[pead-validated-2026-05-18]]); the 2022 drag is offset by the
  2024-2026 gain. Keep PEAD on as the production default.
- **Dropping quality makes it WORSE** (-15.41% → -17.57%), even
  though quality standalone is -23.85%. Quality is partially
  diversifying — it picks defensive sectors that lose less in some
  weeks while value crushes others. Remove it and you over-concentrate
  on value/momentum, which has its own failure modes (e.g., the
  late-2022 momentum unwind).
- **Dropping value makes it MUCH worse** (-15.41% → -18.60%). Value
  was the only positive factor — losing it removes the lone
  diversifier that was helping.
- **Dropping momentum slightly helps** (-15.41% → -11.88%). Momentum
  is the marginal loser when blended with quality+value+pead.

## The deeper lesson

There's no single factor to drop. The composite blend IS doing
diversification work — each factor's wins/losses partially offset.
The 2022 loss is *structural*: every base factor in the set struggles
in a rate-rise + rotation regime simultaneously. Tweaking the
composition cannot fix it within the current factor set.

WF fails on EVERY configuration on this window. That's the underlying
truth: this strategy doesn't have an edge in 2022-style regimes —
hysteresis cushions it (-15.41% → -8.24%) but doesn't generate alpha.

## What actually might help (none of these are validated)

1. **Sector-neutral quality** — rank quality WITHIN each sector instead
   of cross-sectional. The 2022 quality loss came from "long defensive
   sectors" (staples, utilities) during a value/cyclical rotation;
   within-sector ranking would pick the better staples vs the worse
   staples, not the staples vs the cyclicals. Worth backtesting.

2. **Factor-disagreement gate** — when momentum and value strongly
   disagree on a name (one ranks top decile, the other ranks bottom),
   that's a signal of conflicting evidence. Cap the composite weight
   on those names. The 2022 unwind was partly momentum picking names
   that value bottomed.

3. **A defensive factor in the set** — none of m/q/v/pead is
   specifically defensive in a rate-rise. Balance-sheet quality
   (debt trends, interest coverage) might help, but the low-vol
   filter already failed (-8.01pp per
   [[edge-thickening-plan-2026-05-17]]).

4. **Accept the regime weakness** — paper-trade smaller in stress
   regimes; the SPY 200-SMA gate already kills entries in COVID-like
   tapes. Add a VIX-percentile size-down (not a hard gate; that
   already failed).

## Recommendation

Do NOT change the production composite based on this ablation.
- Keep PEAD on (cross-window net positive).
- Keep quality on (its removal hurts the composite by +2.16pp).
- Don't run separate "stress profile" weights (regime-conditional
  weighting already validated -3.93pp).

Instead, the next investigation should be **sector-neutral quality**
— that's the principled academic fix for the failure mode this
ablation surfaces (quality picked the wrong sectors in stress).

## Files

- Single-factor: `reports/ablation_{mom,qual,val}_234de3.json`
- Composite ablation: `reports/ablation_{no_quality,no_momentum,no_value}_234de3.json`
- No-PEAD: `reports/ablation_composite_nopead_234de3.json`
