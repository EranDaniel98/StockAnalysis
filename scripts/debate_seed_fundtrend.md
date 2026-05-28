# Discovery loop iter 2 — THEME C: fundamental-trend / earnings-revision (price-orthogonal)

> Candidates tested in scripts/factor_lab.py (forward-IC + permutation null, 5 datasets
> incl 2000-name broad universe), survivors escalated to the portfolio CAPM-α test
> (phase_envelope). Propose CONCRETE formulas on available fields; we test immediately.

## CRITICAL LESSON (iter 1) — IC is necessary but NOT sufficient
PEAD + risk-managed-momentum had STRONG IC but NEGATIVE ungated portfolio CAPM-α (−3.7%) —
its top names load market beta. The bar is **portfolio Jensen's α > +3%/yr across regimes**,
NOT IC. Fundamental-trend signals are attractive because they're PRICE-ORTHOGONAL (don't
mechanically load price beta the way momentum does).

## Available fields (offline only)
EDGAR PIT fundamentals WITH filing history (so QoQ / YoY trends + accelerations are computable):
revenue, revenue_growth_yoy, earnings_growth_yoy, gross/operating/profit margins, roe, roa, fcf,
debt; raw NI/CFO/total_assets (accruals sidecar). Polygon EOD; earnings surprise/dates; VIX/SPY.
NO dark-pool/options/intraday/short-interest/insider.

## Already falsified — do NOT propose
gross-profitability (level), multi-leg composites (QGF6), multiplicative interactions (Mirage),
standalone PEAD+RM-MOM, raw momentum, low-vol/asset-growth. NOTE: ΔOpMargin showed 4/8 S&P signif
(promising), earnings-growth-acceleration was weak alone — refine, don't just restate.

## THEME C — ONE clean, low-turnover, price-orthogonal fundamental-trend signal
Markets underreact to slow-moving fundamental TRENDS (not levels). Propose 3-5 concrete signals
from: operating-margin acceleration (ΔΔ over 3-4 filings), revenue-growth acceleration, ROE/ROA
improvement trend, FCF-margin trend, accrual-trend (improving cash conversion), earnings-revision
proxy (change in earnings_growth_yoy). For each: exact formula across the filing history, lookback
(# filings), sign, mechanism (slow diffusion of fundamental news), and why it should produce
LOW-BETA Jensen's α. Then propose the single best 2-leg low-turnover combo (one fundamental-trend
leg + PEAD as the event anchor) that could clear portfolio CAPM-α +3% across regimes WITHOUT
loading beta. Rank by expected portfolio alpha; name each persistence mechanism.
