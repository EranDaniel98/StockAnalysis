# Analyzer Correlation Matrix

Generated 2026-05-15T23:44:59.549027+00:00.

- Window: 2022-05-13 → 2024-05-13
- Panel rows: 97,406
- Redundancy flag: |corr| ≥ 0.7

## Reading the matrix

Each cell is the cross-sectional correlation of two analyzer sub-scores over every (date, ticker) in the panel. Pearson catches linear duplicates, Spearman catches rank-order duplicates (more robust when analyzers compress to similar score buckets but with different magnitudes).

**Redundancy reading:** if two analyzers carry > 0.7 correlation they're effectively voting the same way; the strategy's weighted composite is double-counting that signal. Either drop the weaker one or merge them.

## Pearson

| | technical | fundamental | statistical | pattern | trend | alpha158 |
|---|---|---|---|---|---|---|
| technical | +1.000 | +0.043 | +0.731 | -0.141 | +0.142 | -0.016 |
| fundamental | +0.043 | +1.000 | +0.050 | -0.008 | +0.028 | -0.001 |
| statistical | +0.731 | +0.050 | +1.000 | -0.139 | +0.149 | -0.080 |
| pattern | -0.141 | -0.008 | -0.139 | +1.000 | -0.044 | -0.233 |
| trend | +0.142 | +0.028 | +0.149 | -0.044 | +1.000 | -0.206 |
| alpha158 | -0.016 | -0.001 | -0.080 | -0.233 | -0.206 | +1.000 |

## Spearman

| | technical | fundamental | statistical | pattern | trend | alpha158 |
|---|---|---|---|---|---|---|
| technical | +1.000 | +0.040 | +0.730 | -0.143 | +0.149 | -0.019 |
| fundamental | +0.040 | +1.000 | +0.039 | -0.008 | +0.038 | -0.002 |
| statistical | +0.730 | +0.039 | +1.000 | -0.138 | +0.163 | -0.089 |
| pattern | -0.143 | -0.008 | -0.138 | +1.000 | -0.044 | -0.226 |
| trend | +0.149 | +0.038 | +0.163 | -0.044 | +1.000 | -0.214 |
| alpha158 | -0.019 | -0.002 | -0.089 | -0.226 | -0.214 | +1.000 |

## Flagged pairs (|corr| ≥ 0.70)

### Pearson
- **technical ↔ statistical**: +0.731

### Spearman
- **technical ↔ statistical**: +0.730
