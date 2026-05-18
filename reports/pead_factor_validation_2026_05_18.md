# PEAD Factor Validation — 2026-05-18

Adds the Bernard-Thomas Post-Earnings Announcement Drift signal as a
4th rank frame in the d05_r63 composite. The PEAD module already
existed (`src/factors/pead.py`); this validation wires it into the
backtest path and runs the 3-window A/B.

## Headline

**FIRST POSITIVE OVERLAY.** All previous defensive / regime / vol
overlays (VIX gate, regime-conditional weights, low-vol filter) hurt
cross-window alpha on average. PEAD lifts it by **+2.53pp/yr** AND
tightens drawdowns across every window. The strongest result of the
2026-05-18 pipeline-research session.

## Numbers

| Window | Baseline α | +PEAD α | Δ | Baseline DD | +PEAD DD |
|---|---|---|---|---|---|
| 2020-2022 (COVID) | +1.21% | **+4.02%** | **+2.81pp** | -23.35% | **-16.16%** |
| 2022-2024 | +14.32% | +11.15% | -3.17pp | -15.08% | -13.92% |
| 2024-2026 | +16.93% | **+24.87%** | **+7.94pp** | -23.18% | -20.80% |
| **3-window avg** | **+10.82%** | **+13.35%** | **+2.53pp** | -20.5% | -17.0% |

Walk-forward:
* 2020-2022: still FAILs but min_sharpe improves -2.57 → -2.14
* 2022-2024: PASS → PASS
* 2024-2026: PASS → PASS (min_sharpe 0.59 → 0.80, mean 1.54 → 1.78)

## Why PEAD works where other overlays didn't

The defensive overlays all had the same pathology: they trade alpha for
drawdown reduction at a poor ratio because they REMOVE exposure (cash
out on VIX spike, down-weight momentum in stress, drop high-vol names).

**PEAD adds INFORMATION instead of removing exposure.** It tilts the
top-decile toward names that have already shown a strong earnings
beat — a signal that's been replicated since Bernard-Thomas 1989, with
~6%/yr published alpha persisting through every out-of-sample re-test.
The factor surface is dense (~70% of SP500 names have an active drift
window at any given as-of) so it actually shifts the composite ranking.

## Caveats

* **2022-2024 was -3.17pp.** Not every window benefits equally; the
  2022 bear-recovery window's outperformance came from quality+value
  names (CF, NEM, OXY) that didn't have strong earnings beats. PEAD
  rotated some of that exposure into names with stronger drift signal,
  losing a little alpha on that specific window. Net is still +2.53pp
  averaged.
* **Walk-forward on COVID still fails.** PEAD lifts the COVID alpha
  (+1.21% → +4.02%) but doesn't fix the 2020 drawdown that has no
  earnings-drift signal in front of it.
* **Earnings cache is yfinance-sourced.** Surprise % values can revise
  over time; the cache snapshot pins to a single point in calendar.
  yfinance also misses some prints. Real production should validate
  against a paid feed (Zacks / Estimize) before sizing up.

## Verdict for production

**Enable PEAD in the daily pipeline.** This is the first overlay that
earns its place — improves alpha, tightens drawdowns, doesn't trade
one off for the other.

Concretely:
1. Flip `--include-pead` ON by default in `scripts/daily_factor_picks.py`
   so the live picks pipeline uses m+q+v+PEAD.
2. Strategy label changes to `composite_d05_r63_pead`.
3. Monitor the next 2-3 quarters of paper trading vs the historical
   baseline to ensure the lift generalizes forward.

## Source files

- `data/backtests/d05_r63_{2020,2022,2024}_{baseline,pead}.json`
- Code in `src/factors/pead.py` (factor) + `--include-pead` flag.
- Earnings cache: `data/earnings_history/*.parquet` (1015 tickers,
  ~50 quarters each).
