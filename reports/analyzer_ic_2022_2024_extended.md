# Analyzer IC Report — minimal_baseline

Generated 2026-05-16T00:26:04.605360+00:00.

- Window: 2022-05-13 → 2024-05-13
- Universe: `russell_1000`
- Strategy (for scoring): `minimal_baseline`
- Horizons: 5D, 10D, 21D, 42D trading days
- Quantiles: 5
- Bonferroni k: 6
- Panel rows: 97,406

## Interpretation

- **IC mean** — Spearman rank correlation between the factor score and the forward return for that horizon. Cross-sectional retail factors are loud if > 0.03; > 0.05 is strong.
- **IC IR** — IC mean / IC std across rebalance dates. > 0.5 = the signal is stable over time, not driven by one window.
- **t-stat / Bonferroni-p** — t-test on the IC time series under null IC=0. Bonferroni adjusts for the seven analyzer tests; the composite is shown as control and is not Bonferroni-counted.
- **Top–Bottom %** — top quintile mean forward return minus bottom quintile, in percent. Useful sanity check that the IC translates into actually-tradable spread.

## Horizon: 5D

| Factor | IC mean | IC IR | t-stat | Bonferroni-p | Top–Bottom % | Verdict |
|---|---|---|---|---|---|---|
| technical | +0.0144 | +0.09 | +1.61 | 0.6517 | -0.135 | WEAK |
| fundamental | +0.0183 | +0.32 | +5.77 | 0.0000 | +0.139 | WEAK |
| statistical | +0.0205 | +0.13 | +2.36 | 0.1131 | -0.143 | WEAK |
| pattern | n/a | n/a | n/a | n/a | n/a | NA |
| trend | -0.0007 | -0.00 | -0.07 | 1.0000 | +0.281 | NOISE |
| alpha158 | +0.0023 | +0.02 | +0.38 | 1.0000 | -0.032 | NOISE |
| composite | +0.0240 | +0.19 | +3.34 | 1.0000 | -0.067 | WEAK |

## Horizon: 11D

| Factor | IC mean | IC IR | t-stat | Bonferroni-p | Top–Bottom % | Verdict |
|---|---|---|---|---|---|---|
| technical | +0.0043 | +0.03 | +0.52 | 1.0000 | -0.383 | NOISE |
| fundamental | +0.0233 | +0.43 | +7.72 | 0.0000 | +0.267 | WEAK |
| statistical | +0.0161 | +0.11 | +2.02 | 0.2683 | -0.382 | WEAK |
| pattern | n/a | n/a | n/a | n/a | n/a | NA |
| trend | +0.0058 | +0.04 | +0.63 | 1.0000 | +0.467 | NOISE |
| alpha158 | +0.0127 | +0.12 | +2.12 | 0.2076 | +0.069 | WEAK |
| composite | +0.0196 | +0.16 | +2.91 | 1.0000 | -0.239 | WEAK |

## Horizon: 23D

| Factor | IC mean | IC IR | t-stat | Bonferroni-p | Top–Bottom % | Verdict |
|---|---|---|---|---|---|---|
| technical | -0.0005 | -0.00 | -0.07 | 1.0000 | -0.869 | NOISE |
| fundamental | +0.0293 | +0.65 | +11.74 | 0.0000 | +0.542 | WEAK |
| statistical | +0.0114 | +0.08 | +1.39 | 0.9869 | -1.019 | WEAK |
| pattern | n/a | n/a | n/a | n/a | n/a | NA |
| trend | +0.0106 | +0.09 | +1.30 | 1.0000 | +0.646 | WEAK |
| alpha158 | +0.0029 | +0.03 | +0.54 | 1.0000 | +0.226 | NOISE |
| composite | +0.0197 | +0.16 | +2.86 | 1.0000 | -0.625 | WEAK |

## Horizon: 44D

| Factor | IC mean | IC IR | t-stat | Bonferroni-p | Top–Bottom % | Verdict |
|---|---|---|---|---|---|---|
| technical | -0.0149 | -0.11 | -1.99 | 0.2839 | -1.209 | NOISE |
| fundamental | +0.0408 | +1.00 | +18.07 | 0.0000 | +1.204 | MODEST |
| statistical | -0.0162 | -0.12 | -2.10 | 0.2180 | -1.757 | NOISE |
| pattern | n/a | n/a | n/a | n/a | n/a | NA |
| trend | +0.0076 | +0.07 | +1.09 | 1.0000 | +0.941 | NOISE |
| alpha158 | +0.0064 | +0.07 | +1.18 | 1.0000 | +0.539 | NOISE |
| composite | +0.0079 | +0.06 | +1.15 | 1.0000 | -0.910 | NOISE |

## Notes

- IC is computed on the raw analyzer sub-score 0-100 (not on the strategy-weighted contribution). This is what we want — we're measuring whether the analyzer carries information, separate from the question of how much weight it should get.
- alpha158 internally aggregates ~25 sub-factors into a single 0-100 score. This report tests the aggregate only. A separate per-factor breakdown would require exposing the raw 25 columns from the analyzer.
- Verdict thresholds are rough rules of thumb: STRONG = IC>0.05 + significant, MODEST = IC>0.03 + significant, WEAK = IC>0.01, NOISE = below. Bonferroni guards against us declaring an analyzer real just because we tested 7.
