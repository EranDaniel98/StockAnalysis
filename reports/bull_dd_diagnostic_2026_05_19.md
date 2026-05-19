# Bull-window DD Diagnostic — d03 vs d05 — 2026-05-19

## Question

Memory `project_d03_concentration` flagged that top-3% (d03) widens
the 2024-26 max drawdown from -14.53% (d05) to **-19.21%**. Is the
wider DD a mechanical consequence of concentration (higher portfolio
beta, same direction as the market correction), or did name selection
at the pre-DD rebalance produce idiosyncratic loss?

## Numbers

| Series | Peak | Trough | Max DD | Days |
|---|---|---|---|---|
| **SPY** | 2025-02-19 | 2025-04-08 | **-18.76%** | 48 |
| d05 (top 5%) | 2025-02-18 | 2025-04-08 | -14.53% | 49 |
| d03 (top 3%) | **2024-12-06** | 2025-04-08 | **-19.21%** | **123** |

Three observations from the table:
1. **SPY had a major correction** Feb 19 → Apr 8 (-18.76%). The
   drawdowns are not strategy-internal; the market did this.
2. **d03 peaked 2.5 months EARLIER** than d05/SPY (Dec 6, 2024 vs
   Feb 18-19). So d03 had ~10 weeks of slow bleed before SPY's peak.
3. d03's DD window is 2.5× as long as d05's (123 days vs 49) because
   of #2.

## Beta decomposition

Full-window daily-return regression of each strategy vs SPY:

| Strategy | Beta vs SPY | Beta-implied DD (β × SPY drop) | Actual DD | Idiosyncratic excess |
|---|---|---|---|---|
| d05 | 0.694 | -12.35% | -14.38% | **-2.03pp** |
| d03 | **0.884** | -15.73% | -19.21% | **-3.48pp** |

Concentration raised beta from 0.694 → 0.884 (delta **+0.190**).
That higher beta mechanically predicts an extra **-3.38pp** of DD on
top of d05 (given the -17.80% SPY drop in the d03 window).

Actual extra DD vs d05: **-4.83pp**. So:

* **3.38pp** explained by mechanical concentration (higher β)
* **1.45pp** unexplained — idiosyncratic name selection at the
  Dec/Feb rebalances.

**~70% mechanical, ~30% idiosyncratic.**

## What this means

- **Most of the wider DD is the cost of concentration.** You can't
  remove it without partially removing the d03 alpha (the same
  concentration that doubled cross-window α also doubled drawdown
  exposure to broad-market corrections).
- **The 1.45pp residual is small but real.** d03's holdings at the
  Dec 2024 rebalance underperformed even what their higher beta
  would predict. Not catastrophic, but a signal that the composite
  was picking unfavorable names entering the correction.

## Mitigations ranked by expected leverage

1. **VIX exposure scaling (#3 in queue).** Continuous derisking as
   VIX rises — addresses the *systematic* portion of the DD without
   touching name selection. Has the best chance of cutting DD
   without losing the α from concentration. **Highest leverage.**
2. **Vol-aware sizing.** Equal-vol weights instead of equal-dollar.
   Inside the 15-name basket, names with realized 90d vol > X get
   smaller positions. Trims the idiosyncratic 1.45pp at marginal
   cost to α.
3. **Beta cap.** Hard cap portfolio beta at ~0.80. Mechanically
   tames the mechanical part. Cost: gives back upside α
   symmetrically. Probably net-negative on the cross-window verdict.
4. **Sector tilt audit.** If d03's Dec 2024 picks clustered in a
   single sector that took the brunt of the correction, the existing
   sector cap (30%) wasn't tight enough. Worth checking, but the
   diagnostic above doesn't have position-level data to confirm.

## What NOT to do

- **Don't revert to d05** to "fix" the DD. d05 lost the +9pp avg α
  that d03 brought; trading α for DD is not the right tradeoff
  given the user's edge-thickening priorities.
- **Don't add another binary regime gate.** The `vix-percentile`
  gate validation memo already shows that single missed rebalances
  via V-shape recovery cost 30+pp. Exposure-scaling (#3 above) is
  the better-shaped fix.

## Reproduce

```
uv run python scripts/bull_dd_diagnostic.py
```

Reads `data/backtests/post_24of24/{2024_2026_full_stack.json,
ablation_2024_2026_top3pct.json}` + `data/snapshots/1dd88cad8e1f7534/
spy.parquet`. Pure-Python, no live data.
