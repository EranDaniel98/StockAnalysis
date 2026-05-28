# Discovery loop iter 2 — THEME B: short-horizon reversal & EOD liquidity (broad universe)

> Candidates tested in scripts/factor_lab.py (forward-IC + permutation null, 5 datasets
> incl 2000-name broad universe), survivors escalated to the portfolio CAPM-α test
> (phase_envelope). Propose CONCRETE formulas on available fields; we test immediately.

## CRITICAL LESSON (iter 1) — IC is necessary but NOT sufficient
PEAD + risk-managed-momentum had STRONG IC but NEGATIVE ungated portfolio CAPM-α (−3.7%) —
its top names load market beta. The bar is **portfolio Jensen's α > +3%/yr across regimes**,
NOT IC. Favor signals that are **market-neutral / low-beta** by construction.

## Available fields (offline only)
Polygon EOD OHLCV (the broad universe is 2000 names — small/mid-caps included); EDGAR PIT
fundamentals + raw NI/CFO/total_assets; earnings; VIX/SPY. NO dark-pool/options/intraday/
short-interest/insider — only EOD daily bars.

## Already falsified — do NOT propose
gross-profitability, multi-leg composites, multiplicative interactions (Mirage), standalone
PEAD+RM-MOM, raw momentum, low-vol & asset-growth (beta/era tilts).

## THEME B — short-horizon reversal & liquidity, where it's strongest (smaller names)
Short-term reversal and illiquidity premia are LESS beta-driven than momentum and strongest in
the broad/small-cap universe — a natural market-neutral alpha. Propose 3-5 concrete signals from:
1-week / 1-month cross-sectional reversal (−recent return), EOD Amihud illiquidity (|ret|/$vol,
rolling), volume-shock mean-reversion (return after an abnormal-volume day), reversal conditioned
on illiquidity (illiquid names reverse harder), gap-fade. For each: formula, lookback, sign,
mechanism (limits-to-arbitrage / liquidity provision), and turnover estimate (reversal is high-
turnover — must survive 30bps costs). Rank by expected market-neutral portfolio alpha net of costs.
Flag which need a turnover cap to be tradeable.
