# Analyzer IC Report — minimal_baseline

Generated 2026-05-18T08:10:01.371955+00:00.

- Window: 2022-05-13 → 2024-05-13
- Universe: `russell_1000`
- Strategy (for scoring): `minimal_baseline`
- Horizons: 5D, 11D, 23D, 44D trading days
- Quantiles: 5
- Bonferroni k: 6
- Panel rows (all regimes): 97,406
- Regime split: `vix` (2 cell(s))

## Interpretation

- **IC mean** — Spearman rank correlation between the factor score and the forward return for that horizon. Cross-sectional retail factors are loud if > 0.03; > 0.05 is strong.
- **IC IR** — IC mean / IC std across rebalance dates. > 0.5 = the signal is stable over time, not driven by one window.
- **t-stat / Bonferroni-p** — t-test on the IC time series under null IC=0. Bonferroni adjusts for the seven analyzer tests; the composite is shown as control and is not Bonferroni-counted.
- **Top–Bottom %** — top quintile mean forward return minus bottom quintile, in percent. Useful sanity check that the IC translates into actually-tradable spread.
- **Regime asymmetry** — when the same factor's IC sign or magnitude differs across regimes, a regime-conditional composite is justified. When it's symmetric, a static composite captures everything available.

# Regime: low_vix

## Horizon: 5D

| Factor | IC mean | IC IR | t-stat | Bonferroni-p | Top–Bottom % | Verdict |
|---|---|---|---|---|---|---|
| technical | +0.0239 | +0.15 | +2.16 | 0.1919 | -0.029 | WEAK |
| fundamental | +0.0195 | +0.34 | +4.76 | 0.0000 | +0.179 | WEAK |
| statistical | +0.0215 | +0.15 | +2.09 | 0.2274 | -0.104 | WEAK |
| pattern | n/a | n/a | n/a | n/a | n/a | NA |
| trend | +0.0267 | +0.18 | +1.94 | 0.3297 | +0.333 | WEAK |
| alpha158 | +0.0078 | +0.08 | +1.13 | 1.0000 | -0.069 | NOISE |
| composite | +0.0255 | +0.21 | +2.89 | 1.0000 | +0.013 | WEAK |

## Horizon: 12D

| Factor | IC mean | IC IR | t-stat | Bonferroni-p | Top–Bottom % | Verdict |
|---|---|---|---|---|---|---|
| technical | +0.0210 | +0.15 | +2.16 | 0.1903 | -0.010 | WEAK |
| fundamental | +0.0288 | +0.50 | +7.10 | 0.0000 | +0.435 | WEAK |
| statistical | +0.0199 | +0.15 | +2.14 | 0.1999 | -0.150 | WEAK |
| pattern | n/a | n/a | n/a | n/a | n/a | NA |
| trend | +0.0145 | +0.10 | +1.11 | 1.0000 | +0.604 | WEAK |
| alpha158 | +0.0054 | +0.06 | +0.81 | 1.0000 | -0.144 | NOISE |
| composite | +0.0275 | +0.27 | +3.80 | 1.0000 | +0.106 | WEAK |

## Horizon: 25D

| Factor | IC mean | IC IR | t-stat | Bonferroni-p | Top–Bottom % | Verdict |
|---|---|---|---|---|---|---|
| technical | +0.0186 | +0.16 | +2.21 | 0.1704 | -0.027 | WEAK |
| fundamental | +0.0431 | +1.08 | +15.20 | 0.0000 | +0.945 | MODEST |
| statistical | +0.0191 | +0.15 | +2.11 | 0.2154 | -0.462 | WEAK |
| pattern | n/a | n/a | n/a | n/a | n/a | NA |
| trend | +0.0051 | +0.05 | +0.55 | 1.0000 | +0.971 | NOISE |
| alpha158 | -0.0183 | -0.24 | -3.38 | 0.0052 | -0.026 | NOISE |
| composite | +0.0360 | +0.39 | +5.45 | 1.0000 | +0.177 | MODEST |

## Horizon: 46D

| Factor | IC mean | IC IR | t-stat | Bonferroni-p | Top–Bottom % | Verdict |
|---|---|---|---|---|---|---|
| technical | -0.0092 | -0.08 | -1.16 | 1.0000 | -0.340 | NOISE |
| fundamental | +0.0581 | +1.96 | +27.57 | 0.0000 | +1.891 | STRONG |
| statistical | -0.0192 | -0.15 | -2.07 | 0.2380 | -1.057 | NOISE |
| pattern | n/a | n/a | n/a | n/a | n/a | NA |
| trend | +0.0013 | +0.01 | +0.11 | 1.0000 | +1.451 | NOISE |
| alpha158 | -0.0070 | -0.07 | -1.01 | 1.0000 | +0.434 | NOISE |
| composite | +0.0158 | +0.17 | +2.42 | 1.0000 | -0.019 | WEAK |

# Regime: high_vix

## Horizon: 5D

| Factor | IC mean | IC IR | t-stat | Bonferroni-p | Top–Bottom % | Verdict |
|---|---|---|---|---|---|---|
| technical | +0.0012 | +0.01 | +0.08 | 1.0000 | -0.291 | NOISE |
| fundamental | +0.0140 | +0.25 | +2.88 | 0.0281 | +0.042 | WEAK |
| statistical | +0.0182 | +0.11 | +1.22 | 1.0000 | -0.191 | WEAK |
| pattern | n/a | n/a | n/a | n/a | n/a | NA |
| trend | -0.0110 | -0.07 | -0.59 | 1.0000 | +0.151 | NOISE |
| alpha158 | -0.0055 | -0.04 | -0.48 | 1.0000 | +0.044 | NOISE |
| composite | +0.0130 | +0.10 | +1.18 | 1.0000 | -0.255 | WEAK |

## Horizon: 12D

| Factor | IC mean | IC IR | t-stat | Bonferroni-p | Top–Bottom % | Verdict |
|---|---|---|---|---|---|---|
| technical | -0.0204 | -0.13 | -1.45 | 0.9017 | -1.098 | NOISE |
| fundamental | +0.0153 | +0.31 | +3.59 | 0.0028 | -0.003 | WEAK |
| statistical | +0.0079 | +0.05 | +0.57 | 1.0000 | -0.909 | NOISE |
| pattern | n/a | n/a | n/a | n/a | n/a | NA |
| trend | -0.0184 | -0.14 | -1.17 | 1.0000 | +0.287 | NOISE |
| alpha158 | +0.0229 | +0.19 | +2.15 | 0.1987 | +0.420 | WEAK |
| composite | -0.0022 | -0.02 | -0.19 | 1.0000 | -0.904 | NOISE |

## Horizon: 25D

| Factor | IC mean | IC IR | t-stat | Bonferroni-p | Top–Bottom % | Verdict |
|---|---|---|---|---|---|---|
| technical | -0.0274 | -0.16 | -1.85 | 0.4002 | -2.412 | NOISE |
| fundamental | +0.0100 | +0.24 | +2.77 | 0.0384 | -0.110 | WEAK |
| statistical | -0.0031 | -0.02 | -0.21 | 1.0000 | -2.276 | NOISE |
| pattern | n/a | n/a | n/a | n/a | n/a | NA |
| trend | -0.0517 | -0.39 | -3.16 | 0.0145 | +0.224 | NOISE |
| alpha158 | +0.0296 | +0.26 | +2.98 | 0.0204 | +0.824 | WEAK |
| composite | -0.0149 | -0.11 | -1.24 | 1.0000 | -2.121 | NOISE |

## Horizon: 46D

| Factor | IC mean | IC IR | t-stat | Bonferroni-p | Top–Bottom % | Verdict |
|---|---|---|---|---|---|---|
| technical | -0.0239 | -0.15 | -1.71 | 0.5381 | -2.723 | NOISE |
| fundamental | +0.0166 | +0.41 | +4.70 | 0.0000 | +0.072 | WEAK |
| statistical | -0.0180 | -0.12 | -1.37 | 1.0000 | -3.195 | NOISE |
| pattern | n/a | n/a | n/a | n/a | n/a | NA |
| trend | -0.0694 | -0.69 | -5.55 | 0.0000 | -0.465 | NOISE |
| alpha158 | +0.0327 | +0.34 | +3.98 | 0.0007 | +0.976 | MODEST |
| composite | -0.0174 | -0.13 | -1.52 | 1.0000 | -2.739 | NOISE |

# Cross-regime IC comparison

For each (factor, horizon), the IC mean side-by-side across regimes. Asymmetry > 2× or sign flips are the strongest evidence for regime-conditional weighting.

| Factor | Horizon | low_vix | high_vix |
|---|---|---|---|
| technical | 5D | +0.0239 | +0.0012 |
| technical | 12D | +0.0210 | -0.0204 |
| technical | 25D | +0.0186 | -0.0274 |
| technical | 46D | -0.0092 | -0.0239 |
| fundamental | 5D | +0.0195 | +0.0140 |
| fundamental | 12D | +0.0288 | +0.0153 |
| fundamental | 25D | +0.0431 | +0.0100 |
| fundamental | 46D | +0.0581 | +0.0166 |
| statistical | 5D | +0.0215 | +0.0182 |
| statistical | 12D | +0.0199 | +0.0079 |
| statistical | 25D | +0.0191 | -0.0031 |
| statistical | 46D | -0.0192 | -0.0180 |
| pattern | 5D | n/a | n/a |
| pattern | 12D | n/a | n/a |
| pattern | 25D | n/a | n/a |
| pattern | 46D | n/a | n/a |
| trend | 5D | +0.0267 | -0.0110 |
| trend | 12D | +0.0145 | -0.0184 |
| trend | 25D | +0.0051 | -0.0517 |
| trend | 46D | +0.0013 | -0.0694 |
| alpha158 | 5D | +0.0078 | -0.0055 |
| alpha158 | 12D | +0.0054 | +0.0229 |
| alpha158 | 25D | -0.0183 | +0.0296 |
| alpha158 | 46D | -0.0070 | +0.0327 |
| composite | 5D | +0.0255 | +0.0130 |
| composite | 12D | +0.0275 | -0.0022 |
| composite | 25D | +0.0360 | -0.0149 |
| composite | 46D | +0.0158 | -0.0174 |

## Notes

- IC is computed on the raw analyzer sub-score 0-100 (not on the strategy-weighted contribution). This is what we want — we're measuring whether the analyzer carries information, separate from the question of how much weight it should get.
- alpha158 internally aggregates ~25 sub-factors into a single 0-100 score. This report tests the aggregate only. A separate per-factor breakdown would require exposing the raw 25 columns from the analyzer.
- Verdict thresholds are rough rules of thumb: STRONG = IC>0.05 + significant, MODEST = IC>0.03 + significant, WEAK = IC>0.01, NOISE = below. Bonferroni guards against us declaring an analyzer real just because we tested 7.
