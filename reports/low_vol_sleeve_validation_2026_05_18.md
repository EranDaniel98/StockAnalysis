# Low-Vol Quality Sleeve Validation — 2026-05-18

Tests a post-composite filter that excludes the top-20% most-volatile
names from the m+q+v top-decile picks. Vol is annualized stdev of log
returns over 63 trading days (matches the d05_r63 rebalance cadence).

## Numbers

| Window | Baseline α | low-vol(0.80) α | Δ | Baseline DD | low-vol DD |
|---|---|---|---|---|---|
| 2020-2022 (COVID) | +1.21% | **+3.29%** | **+2.08pp** | -23.35% | -19.43% |
| 2022-2024 | +14.32% | +3.32% | -11.00pp | -15.08% | -13.30% |
| 2024-2026 | +16.93% | +1.82% | -15.11pp | -23.18% | -19.12% |
| **3-window avg** | **+10.82%** | **+2.81%** | **-8.01pp** | -20.5% | -17.3% |

Walk-forward:
* 2020-2022 baseline FAIL → low-vol FAIL (min_sharpe -2.57 → -2.27)
* 2022-2024 baseline PASS → low-vol PASS
* 2024-2026 baseline PASS → low-vol PASS (improves min_sharpe 0.59 → 0.75)

## Reading

**The filter improves drawdown across every window** (~3pp tighter
max DD on average) and **provides modest alpha protection in the
COVID drawdown** (+2.08pp lift on 2020-2022). But it **caps upside
hard** in the two recent recovery / bubble windows — net 3-window
average alpha drops from +10.82% to +2.81%.

This is the same shape we saw with the VIX gate and the regime-
weighted composite: defensive overlays consistently trade alpha for
risk reduction at a poor ratio. The d05_r63 strategy is **already
defensive** by construction (top-decile composite + quarterly hold +
sector cap); adding more defense hits diminishing returns fast.

## What we learned

* The d05_r63 strategy's edge sits in factor exposure, not in vol
  exposure. Dropping high-vol names drops some of the picks that
  *carry the factor signal*. The low-vol filter and the m+q+v composite
  are slightly correlated; you can't add the filter without losing
  some of the composite's bite.
* Drawdown protection is real (~3pp tighter DD on average), but the
  Sharpe-adjusted trade is roughly even — slightly better Sharpe on
  COVID, slightly worse on the others.

## Verdict for production

**Opt-in, off by default.** The flag exists (`--low-vol-keep-pct` on
the backtest CLI) and the module ships (`src/factors/volatility.py`).
The daily pipeline does NOT apply it. Users who optimize for
drawdown rather than absolute alpha can enable it; the default
strategy stays alpha-maximizing.

## What MIGHT work (deferred)

* **Per-position vol scaling** instead of a binary drop. Allocate by
  1/vol weight inside the top decile so the highest-vol names still
  participate but at smaller size. This keeps factor exposure intact
  while controlling realized portfolio vol.
* **Pair with VIX gate** — when VIX is high AND a name is in the top
  vol decile, drop it; otherwise keep. Combines two weak signals.
* **Trailing stop on vol expansion** — exit positions whose realized
  vol doubles relative to entry vol, rather than filtering ex-ante.

Source files:
- `data/backtests/d05_r63_{window}_{baseline,lowvol}.json` × 3
- Code in `src/factors/volatility.py`, `--low-vol-keep-pct` flag.
