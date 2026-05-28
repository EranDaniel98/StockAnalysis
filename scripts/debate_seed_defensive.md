# Discovery loop iter 2 — THEME A: defensive / low-beta quality (pays in down regimes)

> Candidates tested in scripts/factor_lab.py (forward-IC + permutation null, 5 datasets
> incl 2000-name broad universe), survivors escalated to the portfolio CAPM-α test
> (phase_envelope). Propose CONCRETE formulas on available fields; we test immediately.

## CRITICAL LESSON (iter 1) — IC is necessary but NOT sufficient

PEAD + risk-managed-momentum had STRONG cross-sectional IC (+0.04, breadth-robust) but
**NEGATIVE ungated portfolio CAPM-α (−3.7%)** — because its top names load market beta,
leaving no residual alpha after beta adjustment. The bar is **portfolio Jensen's α > +3%/yr
across regimes**, NOT IC. So propose signals whose edge is **LOW-BETA / market-neutral or
DEFENSIVE** — they should be *positive-CAPM-α in the COVID/2022 bear cells*, the regimes the
bull-biased momentum book fails.

## Available fields (offline only)
Polygon EOD OHLCV; EDGAR PIT fundamentals (revenue, gross/operating/profit margins, roe, roa,
fcf, debt_to_equity, current_ratio, dividend_yield, payout_ratio, growth) + raw NI/CFO/
total_assets (accruals sidecar) WITH filing history (trends computable); earnings surprise/dates;
VIX/SPY. NO dark-pool/options/intraday/short-interest/insider.

## Already falsified — do NOT propose
gross-profitability (broad-dead), multi-leg composites (QGF6), multiplicative interactions
(Mirage), standalone PEAD+RM-MOM portfolio, raw momentum (regime-fragile), low-vol & asset-growth
(beta/era tilts, not alpha).

## THEME A — defensive quality that generates CAPM-α, not beta
The book lacks a LOW-BETA alpha source that pays when the market is flat/down. Propose 3-5
concrete signals from: earnings stability (low variance of YoY earnings growth over trailing
filings), conservative financing (debt reduction trend, low/declining debt_to_equity), margin
durability (low volatility of operating_margin across filings), dividend-growth/payout discipline,
FCF stability. For each: formula, lookback, sign, and WHY it should produce positive Jensen's α
that a long-only top-N portfolio captures (i.e., the long leg outperforms its beta), especially
in bear/high-VIX regimes. Rank by expected low-beta portfolio alpha. Name the persistence mechanism.
