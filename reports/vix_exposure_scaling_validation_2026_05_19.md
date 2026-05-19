# VIX Exposure Scaling Validation — 2026-05-19

## Motivation

Bull-DD diagnostic (`reports/bull_dd_diagnostic_2026_05_19.md`)
showed ~70% of d03's wider 2024-26 drawdown is **mechanical**:
concentration raises portfolio beta (0.694 → 0.884), so a -18.76%
SPY correction translates to a wider strategy DD than d05's. The
recommended lever was *continuous* exposure scaling — not a binary
gate, which the 2026-05-18 regime-gating battery showed costs
-32pp via the V-shape-recovery failure mode.

This memo records the A/B against the d03 production config on both
windows, across three parameter sets.

## Implementation

`src/factors/exposure_scaling.py` exposes a piecewise-linear ramp:

* `vix_smoothed <= low_threshold`  → exposure = 1.0
* `low < vix < high_threshold`     → linear ramp down
* `vix_smoothed >= high_threshold` → exposure = floor

Tuneable via `--vix-exposure-scaling --vix-exposure-{low,high,floor,smoothing}`
on `scripts/run_factor_backtest.py`. Default OFF.

## Results

Baseline = d03 production config WITHOUT exposure scaling:

| Window | α | Sharpe | DD | WF mean / min | passed |
|---|---|---|---|---|---|
| 2022-24 | +39.49% | 1.751 | -12.85% | 1.638 / -0.699 | False |
| 2024-26 | -3.28% | 1.091 | -20.20% | 1.199 / +0.461 | True  |

Three exposure-scaling configs tested:

| Config              | 22-24 α | 24-26 α | avg α | 22-24 DD | 24-26 DD |
|---------------------|---------|---------|-------|----------|----------|
| **baseline**            | +39.49% | -3.28%  | **+18.10%** | -12.85% | -20.20% |
| vexp 20/30/floor=0.30 | +21.32% | +2.03%  | +11.67% | -11.19% | -18.81% |
| vexp 20/30/floor=0.60 | +24.65% | +3.34%  | +13.99% | -12.03% | -18.81% |
| vexp 25/35/floor=0.50 | +27.58% | +3.53%  | +15.55% | -13.88% | -18.81% |

## What works

* **Bull-window DD tightens** by ~1.4pp on every configuration.
  This validates the diagnostic's mechanical-beta hypothesis — even
  mild derisking when VIX-21d-MA crosses 20-25 trims some of the
  April-2025 correction loss.
* **Bull-window α improves** by +5-7pp depending on parameters.
  The capital not deployed during the correction also wasn't
  exposed to the drawdown.
* **Sharpe modestly up** on bull window for every config.

## What doesn't work

* **Stress-window α regresses by 12-18pp** on every configuration.
  Root cause is the V-shape-recovery problem from
  `project_regime_gating_battery_2026_05_18`: when the strategy
  derisks during 2022 stress, the Nov 2022 rebalance is at
  exposure 0.46-0.86 — half-deployed into the recovery that
  produced most of the 2022-24 alpha.
* Tightening parameters (raising floor + low_threshold) reduces
  the bleed but doesn't close it. Even the most conservative
  config (low=25, high=35, floor=0.5) gives up -11.91pp on stress.

## Cross-window verdict

**Net cross-window α loss of 2.5-6.4pp** across all tested
parameters. The bull-window improvement is real but doesn't pay
for the stress-window regression.

Per the user's "no regression" constraint, **this CANNOT ship as
default**.

## Ship plan

1. **Implementation shipped as opt-in** behind `--vix-exposure-scaling`.
   Default OFF. Tested + 9 unit tests in
   `tests/factors/test_exposure_scaling.py`.
2. **Document the regime-dependent tradeoff** in this memo and
   memory. Future contributors who think "let's just turn on
   exposure scaling" need to see this table.
3. **Not plumbed into live `daily_factor_picks.py`** for the same
   reason — would change live position sizing in a way that's
   net-negative cross-window. Adding the flag there would require
   the same A/B validation across more windows first.

## What's next

The mechanical 70% of bull-DD partially addressed (1.4pp/3.4pp =
~40% of mechanical, ~28% of total). To do better without the V-shape
penalty, need a fix that:
1. Derisks during *sustained* stress only (filtering more aggressively)
2. Re-risks rapidly on falling VIX (asymmetric exposure ramp)
3. Or attacks the idiosyncratic 30% via vol-aware position sizing

(3) is the most promising next step — it operates inside the basket
(name-level vol weights) rather than on the gross exposure timing,
so it doesn't fight V-shape recoveries.

## Reproduce

```
uv run python -m scripts.run_factor_backtest \
  --snapshot-id 4504fcb65f549dae --factor composite \
  --vix-exposure-scaling \
  [--vix-exposure-low 20] [--vix-exposure-high 30] \
  [--vix-exposure-floor 0.3] \
  --output data/backtests/post_align/2022_2024_vexp.json
```

All five backtests for this memo are under `data/backtests/post_align/`.
