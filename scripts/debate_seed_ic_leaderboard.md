# Co-design goal — beat the durable cores, grounded in REAL IC results

> "Keep trying until we find something useful. Use all the data." We now have a
> fast tester (`scripts/factor_lab.py`: cross-sectional forward-IC + permutation
> null across regimes), so propose CONCRETE, computable signals and we test them
> immediately. No hand-waving — every proposal must be a formula on the fields below.

## What the data actually contains (hard constraint — propose nothing else)

Per-ticker, point-in-time, offline:
- **Prices (Polygon EOD):** OHLCV daily, 2018-2026, ~500-name S&P PIT per snapshot
  (plus a 2000-name broad universe for 2024-26). Any technical/vol/return signal.
- **EDGAR PIT fundamentals (derived, per filing):** pe_ratio, pb_ratio, ps_ratio,
  ev_to_ebitda, revenue, revenue_growth_yoy, earnings_growth_yoy, eps_diluted,
  gross_margin, operating_margin, profit_margin, roe, roa, debt_to_equity,
  current_ratio, free_cash_flow, total_cash, total_debt, dividend_yield,
  payout_ratio, sector, industry, market_cap. **Multiple filings per ticker** →
  trends/accelerations are computable.
- **EDGAR raw (new accruals sidecar):** quarterly net_income, operating_cash_flow,
  total_assets (YTD-unpacked, PIT) → Sloan accruals + asset growth, etc.
- **Earnings (yfinance):** announce dates + surprise%, for PEAD/attention signals.
- **VIX + SPY:** regime/market context.
- **NOT available:** short interest, insider/13F (Postgres offline), dark pool,
  options/dealer-gamma, intraday/L2, analyst estimates beyond EPS surprise.

## What we already measured (forward-IC, 4 regimes x 2 horizons = 8 cells)

`signif` = permutation p<0.05 AND |IC|>0.01; `sign_cons` = % cells agreeing on sign.

| signal | avg_IC | signif | sign_cons | note |
|---|---|---|---|---|
| lowvol_60 | −0.031 | 7/8 | 88% | strongest but it's BETA-timing (high-vol wins up-markets), not alpha |
| quality | +0.015 | 3/8 | **100%** | small but NEVER flips sign — durable core |
| pead | +0.015 | 2/8 | **100%** | small but NEVER flips sign — durable core |
| mom_6_1 / mom_12_1 | +0.015/+0.012 | 2-4/8 | 62-75% | strong but regime-fragile (2022 momentum crash) |
| value | +0.003 | 5/8 | 50% | weak + inconsistent (EPS-period bug caveat) |
| accruals | +0.008 | 3/6 | 50% | inconsistent (Mirage interaction was NULL) |
| ALL interactions (qual×value, mom×quality, accr×value, pead×quality, ...) | ~0 | ≤2/8 | ≤75% | **add nothing over base legs** |

## Findings to build on / not repeat

1. **Interactions are a dead end here** — Mirage (accruals×PEAD) was null, and no
   product-interaction beats its legs. Stop proposing multiplicative gates.
2. **The only sign-stable market-neutral edges are quality and PEAD** (small, +0.015).
3. **lowvol/momentum carry beta/regime risk**, not clean alpha.
4. Single-window results are untrustworthy (phase-luck) — we judge on cross-regime
   consistency + permutation p.

## The ask (be concrete; we test within the hour)

Propose the highest-expected-value CANDIDATES, each as: name, exact formula on the
fields above, lookback, sign, and the PERSISTENCE MECHANISM. Prioritize UNTESTED
EDGAR-derived ideas and robust *combination* methods over new interactions. Seeds
worth arguing about (add/cut/improve):
- **Gross profitability (Novy-Marx):** gross_margin·revenue / total_assets — a
  known robust quality variant we haven't tested (we only tested gross_margin-free
  quality composite).
- **Asset growth (Cooper-Gulen-Schill):** −(total_assets_t / total_assets_{t-4q} − 1)
  — strong known anomaly, untested, computable from the accruals sidecar.
- **Fundamental momentum:** ΔROE / Δprofit_margin / revenue-growth acceleration over
  the last 2-4 filings (improving fundamentals predict drift).
- **Earnings-revision drift:** earnings_growth_yoy level/change as a standalone.
- **Robust combination:** the best way to combine the two sign-stable cores
  (quality+PEAD) — equal-weight rank, sign-agreement gating, vol-scaled — to LIFT IC
  and consistency above either alone. This is probably the real win.

End state: a ranked list of 4-8 concrete signals to add to `factor_lab.py`, each
testable on the fields above, plus the single best combination to try. A signal
that only restates quality/PEAD is not interesting; we want lift or genuine novelty.
