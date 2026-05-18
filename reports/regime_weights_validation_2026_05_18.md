# Regime-Conditional Weights Validation — 2026-05-18

Tests the `fundamental_lean` profile (m=0.6, q=1.2, v=1.2 in low_vix;
m=1.0, q=0.6, v=0.6 in high_vix) against equal-weight baseline.

## Hypothesis (from `reports/analyzer_ic_regime_vix_2022_2024.md`)

Fundamental analyzer IC degrades 3.5x in high_vix. Lean into quality+value
when calm (their IC is strongest); dampen them when stressed.

## Numbers

| Window | Baseline α | fundamental_lean α | Δ |
|---|---|---|---|
| 2020-2022 (COVID) | +1.21% | +1.21% | 0pp (gate inert: snapshot has no pre-window VIX) |
| 2022-2024 | +14.32% | **+23.33%** | **+9.01pp** |
| 2024-2026 | +16.93% | -3.86% | **-20.79pp** |
| **3-window avg** | **+10.82%** | **+6.89%** | **-3.93pp** |

Walk-forward:

| Window | Baseline | fundamental_lean |
|---|---|---|
| 2020-2022 | FAIL | FAIL |
| 2022-2024 | PASS (mean 1.29, min 0.45) | PASS (mean 1.51, min 0.76) |
| 2024-2026 | PASS (mean 1.54, min 0.59) | PASS (mean 1.18, min 0.35) |

## Reading

**The hypothesis tested correctly but failed cross-window.**

* In 2022-2024 (bear → recovery), quality+value names (CF, NEM, OXY,
  the eventual top picks) carry the alpha; up-weighting them gave a
  +9pp lift.
* In 2024-2026 (AI bubble continuation), MOMENTUM is the alpha driver.
  Dampening it cost -20pp.

**Cross-window average drops** from +10.82% to +6.89%. This is the
same "regime exposure dressed as edge" pattern the edge-discovery
report flagged back on 2026-05-16 — a knob that helps one window
trades it off in another.

**The IC asymmetry is real, the weighting response is wrong.** 44D IC
measures sub-score predictive power at a 2-month horizon; the
realized-return distribution at the same horizon is bubble-skewed
when momentum is the dominant factor. Up-weighting the strongest-IC
factor under-weighted the strongest-realized-return factor.

## What we learned

1. **IC ≠ realized P&L weighting.** A factor with stronger IC at the
   horizon isn't automatically the factor you should up-weight — the
   distribution of returns matters as much as the rank correlation.
2. **Equal-weight m+q+v is a defensible default.** The audit chain
   (`reports/edge_discovery_report_2026_05_16.md`) reached the same
   conclusion from a different angle.
3. **Regime-conditional weighting as implemented is not productionizable.**
   The code stays in the tree (`src/factors/regime_weights.py`) for
   future research; `--regime-weights fundamental_lean` is opt-in via
   the backtest CLI, off by default in the daily pipeline.

## What MIGHT work (deferred)

* **Conditional weighting on REALIZED-RETURN regime, not VIX.** Detect
  whether momentum is leading or lagging quality/value over the past
  ~63d and weight accordingly. This is a feedback loop with its own
  pathologies (chasing) but at least it would adapt to the actual
  return distribution rather than a proxy.
* **Ensemble across profiles.** Run equal + fundamental_lean + a
  momentum_lean variant and average their picks. Diversification across
  regime profiles rather than picking one.
* **ML composite** trained on the IC panel that just landed
  (`data/ic_panels/russell1000_2022_2024.csv`). Lets the model learn
  conditioning from the data rather than a hand-coded profile.

Source files:
- `data/backtests/d05_r63_{window}_{baseline,fundlean}.json` × 3
- Code in `src/factors/regime_weights.py`, `--regime-weights` flag.
