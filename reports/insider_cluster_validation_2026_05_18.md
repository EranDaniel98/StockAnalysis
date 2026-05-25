# Insider Cluster Factor Validation — 2026-05-18

Adds the Cohen-Malloy-Pomorski cluster-buy signal as a 4th rank frame
in the composite. Counts distinct insiders who made open-market BUYS
(transaction_code='P', acquired_disposed='A') in the trailing 90 days,
PIT-filtered by filing_date <= as_of. Min 2 distinct insiders to
count as a cluster.

## Numbers

| Window | Baseline α | +insider α | Δ |
|---|---|---|---|
| 2020-2022 (COVID) | +1.21% | +1.21% | 0pp (signal too sparse on the PIT 2020 universe) |
| 2022-2024 | +14.32% | +15.19% | +0.87pp |
| 2024-2026 | +16.93% | +14.63% | -2.30pp |
| **3-window avg** | **+10.82%** | **+10.34%** | **-0.48pp** |

Walk-forward unchanged: 2020-2022 still FAILs, 2022-2024 / 2024-2026
PASS in both variants.

## Reading

**Net-neutral on average.** The insider cluster factor doesn't dominate
m+q+v on this universe — slight win on 2022-2024, slight loss on
2024-2026, identical on 2020-2022. The cluster signal is sparse
(typically <100 of 500 S&P 500 names have a 2+ insider cluster in any
given quarter), so the rank frame contributes a smaller fraction of
the composite than momentum/quality/value.

This roughly matches the `project_insider_r1000_finding.md` memory
("R1000 inconclusive on 173 buys / 28 tickers"). The denser SP500 PIT
universe didn't unlock more signal — same density problem.

Plausible reasons the published CMP alpha doesn't show here:

1. **Universe.** CMP-2012 studied the broad Russell universe. SP500
   names have fewer insider buys because insiders are wealthier and
   plans are pre-scheduled (10b5-1). The high-N insider signal is in
   the small/mid-cap names we explicitly excluded.
2. **Horizon.** Original CMP measured alpha over 12-month holding.
   Our backtest holds 63d. The signal may need longer to play out.
3. **Modern shift.** Pre-scheduled 10b5-1 plans dampen the "I know
   something" signal that CMP captured pre-2003 SOX-era.

## Verdict for production

**Opt-in, off by default.** The `--include-insider` flag adds the
factor; the daily pipeline does NOT enable it. Code stays for future
research (especially if the universe is broadened beyond SP500 PIT).

## What MIGHT work (deferred)

* **Smaller universe.** Re-test on small-caps if/when we ingest one.
  The original CMP edge is concentrated there.
* **Longer hold.** Run d10_r252 (top-10%, annual rebalance) with
  insider — the natural CMP horizon — and see if the marginal lift is
  bigger.
* **Net flow per market cap.** Replace cluster count with net-buy
  $-volume normalized by market cap. Captures conviction size rather
  than just the count of distinct names. The data is in
  `insider_transactions.value_usd`.

Source files:
- `data/backtests/d05_r63_{window}_{baseline,insider}.json` × 3
- Code in `src/factors/insider_cluster.py`, `--include-insider` flag.
