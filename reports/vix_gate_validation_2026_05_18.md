# VIX Gate Validation — 2026-05-18

Three-window A/B of `composite_d05_r63` with `--vix-gate --vix-cutoff 0.80`
against the unfiltered baseline.

## Headline

**Net negative on the one window where the gate fired.** The 2024-2026
window has the only material vol spike inside the 252-day trailing
window (April 2025 SPY correction → VIX into the top-20% of the prior
year). The gate liquidated into cash through the spike and missed the
V-shape recovery, dropping alpha from +16.93% to **-11.12%** and
flipping the walk-forward gate from PASS to FAIL.

The 2022-2024 window's VIX trajectory never crossed the trailing-252d
80th percentile (the regime was elevated throughout, so no single day
stood out), so the gate didn't fire and results are byte-identical to
the baseline. The 2020-2022 (COVID) snapshot has no pre-window VIX
history, so the gate also didn't fire there.

## Numbers

| Window | Strategy | SPY | Alpha | Sharpe | Max DD | WF |
|---|---|---|---|---|---|---|
| 2020-2022 baseline | -3.13% | -4.34% | +1.21% | -0.07 | -23.35% | FAIL (gate inert: no pre-window VIX) |
| 2020-2022 +vixgate | -3.13% | -4.34% | +1.21% | -0.07 | -23.35% | FAIL (same — gate didn't fire) |
| 2022-2024 baseline | +48.08% | +33.76% | +14.32% | 1.06 | -15.08% | PASS |
| 2022-2024 +vixgate | +48.08% | +33.76% | +14.32% | 1.06 | -15.08% | PASS (gate didn't fire) |
| **2024-2026 baseline** | **+62.09%** | +45.16% | **+16.93%** | **1.38** | -23.18% | **PASS** |
| **2024-2026 +vixgate** | +34.04% | +45.16% | **-11.12%** | 0.93 | -25.14% | **FAIL** |

## Reading

The IC regime report (`reports/analyzer_ic_regime_vix_2022_2024.md`)
correctly identified that **fundamental's IC degrades 3.5x in
high_vix** and composite IC goes negative. The hypothesis "block
entries when VIX is elevated" was reasonable.

But the implementation — liquidate to cash on VIX percentile spikes —
falls into the same V-shape-recovery pathology that `factor_strategy_
report_2026_05_16.md:201` documented for the 200-DMA trend filter:

> The trend filter (200d SMA) hurts. Sells the bottom in 2022 and
> 2025 V-shaped corrections, misses the recovery.

VIX-spike-trigger is correlated with V-shape exit timing. The gate
exits at the wrong moment.

## What MIGHT work (deferred, not implemented)

The IC asymmetry is real — the gate's failure mode is in HOW it
reacts, not WHETHER to react. Alternatives worth A/B'ing:

1. **Dampen gross, don't liquidate.** Hold 50% in cash when VIX > 80th
   pct instead of 100%. Smaller exit penalty on the recovery snapback.
2. **Entry-only filter.** Block NEW entries during elevated VIX but
   keep existing positions. The factor strategy's quarterly hold
   already rides through most regimes; we just want to avoid initiating
   new exposure into stress.
3. **Contrarian gate.** Buy harder when VIX > 80th pct (vol-crush is
   the historical edge). Inverts the current logic.
4. **Regime-conditional WEIGHTING** (item 1 below) instead of a binary
   gate — let the factor blend itself shift toward whatever sub-factor
   actually carries signal in stress.

## Verdict for production

**Keep the gate opt-in, default off.** It exists in the codebase
(`src/factors/vix_regime.py` + flags on the daily/backtest scripts)
for future research; nothing the daily pipeline writes will fire it.

Source files:
- `data/backtests/d05_r63_{2020,2022,2024}_{baseline,vixgate}.json`
- Code in `scripts/run_factor_backtest.py:--vix-gate` and
  `scripts/daily_factor_picks.py:--vix-gate`.
