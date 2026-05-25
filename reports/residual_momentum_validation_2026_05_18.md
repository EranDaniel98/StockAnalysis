# Residual Momentum A/B Validation — 2026-05-18

## Hypothesis

Replace raw Jegadeesh-Titman 12-1 momentum with Blitz-Huij-Martens
2011 residual momentum: strip SPY beta out of the 12-month window
before cumulating. Academic literature reports residual Sharpe 0.94
vs raw 0.65 cross-sectionally, with less crash risk.

## Test setup

Live config `d05_r63 + PEAD` on both stress-test snapshots, identical
parameters except `--momentum-flavor`.

```bash
uv run python -m scripts.run_factor_backtest \
    --snapshot-id <id> --factor composite --include-pead \
    --top-decile 0.05 --rebalance-days 63 --cost-bps 5 \
    --momentum-flavor {raw,residual} ...
```

## Results

| Window      | Flavor   | α vs SPY  | Sharpe | Max DD   | WF passed | n trades |
|-------------|----------|-----------|--------|----------|-----------|----------|
| 2024-2026   | raw      | **+24.41%** | 1.87 | -16.47%  | YES (mean 2.18) | 233 |
| 2024-2026   | residual | +3.55%    | 1.27   | -19.14%  | YES (mean 1.43) | 301 |
| 2022-2024   | raw      | -15.41%   | 0.88   | -12.04%  | NO  (mean 0.47, min -2.10) | 132 |
| 2022-2024   | residual | -26.59%   | 0.36   | -13.67%  | NO  (mean -0.09, min -2.98) | 183 |

**Cross-window α delta:** residual = -16.0pp on average vs raw
(-20.9pp on 2024-2026, -11.2pp on 2022-2024).

## Verdict: REJECT

Residual momentum loses ~16pp average alpha and turns over more
aggressively (n_trades 301 vs 233 on the recent window). The
hypothesis fails decisively in this setup.

## Why it didn't work here

1. **Universe is already quality-filtered.** S&P 500 PIT has 480 names
   all in the top quintile of market cap. The high-β-no-alpha names
   that residual momentum is designed to penalize don't dominate the
   selection in the first place — quality + value filters strip them
   out before momentum gets to vote.

2. **2024-2026 was a beta-led tape.** Mag-7 + AI-adjacent leadership
   was high-β by definition. Stripping β explicitly de-ranked the
   names that won the period. Residual momentum punishes leadership
   concentration; this window rewarded it.

3. **Composite redundancy.** When momentum is one of three rank
   frames (m+q+v) with optional PEAD, the marginal alpha from a
   better momentum implementation is diluted ~3-4×. Even a 30% Sharpe
   bump in pure momentum maps to a small composite shift.

4. **Cost drag from higher turnover.** Residual ranks shuffle every
   rebalance because β estimates wiggle. The d05_r63 selection sees
   ~30% more trades, eating 50-75bp/year at 5bp roundtrip.

## What this rules out

Don't re-test residual without ALL of:
- Broader universe (Russell 3000 / Russell 2000) where β contamination
  actually dominates
- Pure-momentum strategy (no composite blending) where the Sharpe
  bump isn't diluted
- A regime that doesn't reward high-β concentration

## What we keep

`src/factors/residual_momentum.py` stays — the tests pin its math,
the implementation is correct (verified: high-β-no-alpha < low-β-with-alpha
ranks). It's the right tool for a different problem. The backtest
runner keeps `--momentum-flavor` so this can be re-evaluated later
without re-implementation.

## Files

- Backtest results: `reports/ab_{raw,residual}_{be2f46,234de3}.json`
- Implementation: `src/factors/residual_momentum.py`
- Tests: `tests/factors/test_residual_momentum.py`

---

Pattern: 5th feature in a row to validate as net-negative in our
setup (VIX gate, regime weights, low-vol filter, insider cluster,
residual momentum). The actually-working overlays are PIT
fundamentals (+0.54 / +0.36 / -0.02 Sharpe) and PEAD (+2.53pp avg α).
The lesson is stable: improvements must clear cross-window α uplift,
not just academic IC.
