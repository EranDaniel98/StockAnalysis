# Decision-Logic Uplift Pass — 2026-05-18

## Brief

Open-ended ask: "enhance decision-making / analyzer / logic — research,
validate, test, implement". This pass picked candidate improvements
that hadn't yet been A/B'd against the live `d05_r63 + PEAD` config,
validated each on the 2024-2026 + 2022-2024 stress snapshots, and
shipped what survived.

## Candidate slate

| # | Candidate                  | Type        | Verdict |
|---|----------------------------|-------------|---------|
| 1 | Residual momentum (Blitz)  | smartness   | REJECT — see report |
| 2 | Hysteresis (turnover stickiness) | smartness + cost | **ADOPT 0.75** |
| 3 | Drift detection guards     | reliability | SHIP |
| (4) | IC-weighted combiner      | smartness   | dropped — regime weighting already proved -3.93pp α; unconditional IC-weighting risks the same failure mode without strong upside evidence |

## What survived

### Hysteresis bonus = 0.75 (default ON)

Held names get composite rank reduced by `0.75 × top_n` slots before
selection. Held shorts symmetrically pushed DOWN to stay shorts.
Selection then takes top-N / bottom-N of the adjusted frame.

Cross-window α uplift vs no-hysteresis baseline:

| Window       | Baseline α | Hyst 0.75 α | Δ        |
|--------------|------------|-------------|----------|
| 2024-2026    | +24.41%    | **+25.86%** | +1.45pp  |
| 2022-2024    | -15.41%    | **-8.24%**  | +7.17pp  |
| **Average**  | +4.50%     | **+8.81%**  | **+4.31pp** |

Stress-window max DD improves -12.04% → -11.29%. WF gate posture
unchanged. Wired into `src/factors/pipeline.py` and made the default
in `scripts/daily_factor_picks.py`. Yesterday's picks load
automatically from `data/daily_picks/` so the daily flow needs no
new state.

Validated against `reports/ab_hyst*_be2f46.json` and `*_234de3.json`.

### Drift detection guards

Pre-paper-trade canary: `scripts/check_picks_drift.py` exits 2 on
FAIL so a wrapper can short-circuit the trade. Checks:

- **universe_size_drift** — -20% from trailing mean → FAIL
- **factor_coverage_{momentum,quality,value,pead}** — -20% from
  trailing mean → FAIL. Treats `NaN` and `None` identically (caught
  a real ingest-bug-masking issue on first run)
- **sector_concentration** — >50% any sector → FAIL (sector cap is
  broken)
- **composite_z_top** — >3σ from rolling mean → FAIL
- **hysteresis_carry_rate** — <10% (off) or >95% (frozen) → WARN

On first real run against today's picks it FAILED on value coverage:
17/24 vs baseline 24/24 (-29.2%). Investigation showed today's
hysteresis-driven selection introduced 7 names without value scores
— a legitimate composition shift, not a bug. The detector is doing
exactly the job intended: surfacing unusual compositions before
they get traded.

12 tests at `tests/factors/test_drift_detector.py`.

## What got shelved (and why it's still in the codebase)

### Residual momentum

Blitz-Huij-Martens 2011 implementation at `src/factors/residual_momentum.py`,
opt-in via `--momentum-flavor residual`. **-16pp avg α** in our setup
across both windows. The academic literature reports a strong Sharpe
uplift, but:

1. S&P 500 PIT is already quality-filtered, so high-β-no-α names
   don't dominate selection anyway
2. 2024-2026 was a beta-led tape, exactly the regime where stripping
   beta de-ranks the actual winners
3. Composite blending dilutes any per-factor improvement 3-4×

Code stays so a future test against Russell 3000 / pure-momentum
strategy doesn't re-implement.

## Pattern observed

This is the 5th feature in a row tested-and-shelved (VIX gate, regime
weights, low-vol filter, insider cluster, residual momentum) — and
the 2nd validated as a clean WIN (PEAD earlier today, hysteresis
now). The lesson is stable:

> Academic IC ≠ realized P&L in this setup. Every overlay has to
> clear cross-window α uplift, not just point-in-time correlation.

The composite is parsimonious for a reason: every signal that survives
the gauntlet is genuinely additive.

## Test footprint

Before this pass: 1043 tests passing.
After this pass: 1067 tests passing.
Added: 24 (7 residual momentum, 5 pipeline hysteresis, 12 drift detector).

## Commits in this session

- `5da82da` — yfinance sector cache (fixed pre-existing data gap)
- next — hysteresis + residual momentum + validation reports
- next+1 — drift detector

## What's next (deferred)

- **IC-weighted factor combiner** (#4 above) — held back because the
  regime-weighting null result is recent and adjacent. Worth revisiting
  if the IC structure of momentum / quality / value / PEAD is measured
  unconditionally (not by VIX regime) and shows a clear ordering.
- **Bootstrap confidence intervals on picks** — would surface
  low-conviction picks at sanity-check time
- **Walk-forward as a hard gate, not just a print** — currently a
  diagnostic; could refuse to write the picks file if min_sharpe < 0

None of these are blockers; the current live config is already
materially stronger than this morning.
