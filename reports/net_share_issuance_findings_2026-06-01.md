# Net-Share-Issuance Factor — Screen Findings (2026-06-01)

**Status: screened POSITIVE (modest, directionally robust) — incremental-composite value TBD.**

## Signal
Pontiff-Woodgate (2008) composite-issuance anomaly: `nsi_1y = log(shares_t / shares_{t-~1y})`, PIT from EDGAR companyfacts (keyed by filing date). Net repurchasers (buybacks, negative nsi) are bullish; net issuers (dilution) bearish. Factor `raw = -nsi_1y`.

## factor_lab screen — 3 regimes (COVID-2020 / 2022 / 2024-26) × {21d, 63d} = 6 cells, n_perm=500

```
net_share_issuance   avg fwd-IC +0.0173   [min +0.0003 .. max +0.0332]   2/6 cells signif   sign_cons 100%
```

- **Real signal, not noise.** All 6 cells positive (sign-consistency 100%) — joint directional agreement is itself significant (binomial p≈0.016) even though only 2/6 cells clear the per-cell perm-p<0.05 bar (IC magnitude is modest → cells underpowered individually).
- **Mid-pack magnitude**, alongside the live composite's own legs: pead +0.0195, sue_lite +0.0173, quality +0.0155, value +0.0125, mom_12_1 +0.0142. Below QGF6 (+0.0264) / rm_mom (+0.0252).
- **Cleanest new-factor screen of the 2026-06-01 discovery arc** — distinctly better-behaved than the distressed-insider idea (which failed its matched-control + permutation nulls).

## Interpretation
A genuine but modest standalone signal. The open question is **incremental value**: NSI's IC is in the same band as factors already in the m+q+v+PEAD composite, and buybacks plausibly overlap quality/value — so it may be redundant. The deciding test is whether adding NSI as a 5th composite leg improves cross-window CAPM-α under the WF-gated phase-envelope vs the baseline. Not answered by the IC screen.

## Known limitation
EDGAR share counts are as-reported (not split-adjusted), so a split looks like issuance. The extractor drops |nsi_1y| > 0.5 as a crude split/M&A guard. If NSI proves incrementally valuable, replace this with proper Polygon split-ratio adjustment before any ship decision.

## Incremental-composite result — DO NOT SHIP into the composite

Added NSI as a 5th leg (`--composite-factors mqvn`, top 5%, +PEAD, daily-regime) and ran the WF-gated phase-envelope vs the `mqv` baseline across all 3 regimes:

| Regime | mqv CAPM-α | mqvn CAPM-α | Δ | WF-pass |
|---|---|---|---|---|
| COVID-2020 | +22.6% | +24.6% | +2.0 | 33% → 22% ↓ |
| 2022 bear | +1.9% | +3.1% | +1.2 | 0% → 0% |
| 2024-26 bull | +8.1% | +6.4% | −1.7 | 33% → 22% ↓ |

NSI nudges α up in 2 windows, down in the bull, **walk-forward-pass is equal-or-worse in all three**, and every delta sits inside the per-window noise band (~3–5pp std). Both arms remain FRAGILE. **Verdict: redundant — it overlaps the crowded premia already in the book and does not earn a composite slot.** A clean demonstration that on this dataset even a positively-screening factor adds no money. The `--composite-factors n` leg is kept in `run_factor_backtest` as reusable test infrastructure, off by default.

## Build
- `src/factors/net_share_issuance.py` — PIT extractor + loader + `net_share_issuance_factor()` (ticker/raw/rank/z_score).
- `scripts/build_nsi_sidecar.py` — per-snapshot `nsi_pit.json` (reuses cached companyfacts; ~90% coverage, ~24k records/snapshot).
- `scripts/factor_lab.py` — wired as a screenable base signal.
