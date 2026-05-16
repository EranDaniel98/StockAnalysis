"""Value factor — earnings yield + revenue yield from EDGAR PIT data.

EDGAR populates raw fundamentals (revenue, eps_diluted, gross_margin,
roe, debt_to_equity, etc.) but NOT price-derived ratios (P/E, P/B,
EV/EBITDA, FCF yield) — those need point-in-time market cap and
price information that the SEC filing doesn't carry.

So the value factor here computes price-aware ratios FROM SCRATCH at
each as_of date, combining:

  1. earnings_yield = EPS_TTM / current_price
     EPS_TTM = sum of last 4 quarterly EPS via FundamentalsPITLoader

  2. revenue_yield  = (revenue_TTM ÷ shares_outstanding_est) / current_price
     Since shares aren't in EDGAR schema, we use a proxy:
     revenue ÷ (current_price × <unknown_shares>) — i.e., we use
     the ratio (revenue / price) as a rank-only signal. It's
     dimensionally wrong but cross-sectionally informative IF the
     universe's share counts are roughly proportional to revenue
     (true on average for large-cap U.S. equities; sector-relative
     scoring would do better, deferred).

Rationale
---------
Earnings yield is the most decision-useful single value signal
(Fama-French; Greenblatt 2006). Without market cap, we can't compute
the cleaner FCF/EV ratios; what we CAN compute is robust enough for
the rank-blend used in the composite.

Future improvement: ingest shares_outstanding from EDGAR (it's in
the cover-page facts of 10-Q/10-K) and compute proper P/E + FCF yield.
Tracked as future-EDGAR-enhancement (Phase 2 follow-up).

Rows with fewer than 1 component present are dropped.
"""

from __future__ import annotations

import logging
from typing import Iterable, Mapping

import pandas as pd

from src.scoring.fundamentals_pit_loader import FundamentalsPITLoader

logger = logging.getLogger(__name__)


_MIN_COMPONENTS_REQUIRED = 1


def _price_on(
    prices: Mapping[str, pd.DataFrame], ticker: str,
    as_of: pd.Timestamp,
) -> float | None:
    df = prices.get(ticker)
    if df is None or df.empty:
        return None
    eligible = df[df.index <= as_of]
    if eligible.empty:
        return None
    px = eligible["Close"].iloc[-1]
    return None if pd.isna(px) else float(px)


def value_factor(
    loader: FundamentalsPITLoader,
    prices: Mapping[str, pd.DataFrame],
    tickers: Iterable[str],
    as_of: pd.Timestamp,
) -> pd.DataFrame:
    """Cross-sectional value ranking at ``as_of``.

    Needs both the PIT fundamentals loader (FCF, EPS, EV/EBITDA, P/B)
    and the current price (to compute FCF yield from market cap that
    the snapshot's stale yfinance ``market_cap`` field doesn't track
    over time).
    """
    as_of_ts = pd.Timestamp(as_of)
    as_of_dt = as_of_ts.to_pydatetime()
    if as_of_dt.tzinfo is None:
        import datetime as _dt
        as_of_dt = as_of_dt.replace(tzinfo=_dt.timezone.utc)

    rows: list[dict] = []
    for t in tickers:
        snap = loader.lookup(t, as_of_dt)
        if snap is None:
            continue
        price = _price_on(prices, t, as_of_ts)
        if price is None or price <= 0:
            continue

        # earnings_yield = EPS_TTM / price. EPS_TTM is computed by the
        # loader from the trailing 4 quarterly EPS (10-Q rows).
        eps_ttm = loader.compute_eps_ttm(t, as_of_dt)
        earnings_yield = None
        if eps_ttm is not None and eps_ttm > 0:
            # Negative-earnings names get None (not -ve yield) — they
            # don't belong in a "cheap stocks" basket via this metric.
            earnings_yield = eps_ttm / price

        # revenue_to_price: a rank-only proxy for revenue yield.
        # Dimensionally not a yield (since we don't divide by shares),
        # but cross-sectionally informative — within sector-similar
        # large-caps, names with high revenue/price tend to be "cheaper
        # on sales" than names with low ratio. See docstring caveat.
        rev_to_price = None
        if snap.revenue is not None and snap.revenue > 0:
            rev_to_price = snap.revenue / (price * 1_000_000_000.0)

        rows.append({
            "ticker": t,
            "earnings_yield": earnings_yield,
            "rev_to_price": rev_to_price,
        })

    if not rows:
        return pd.DataFrame(columns=["ticker", "raw", "rank", "z_score"])

    df = pd.DataFrame(rows)

    z_cols: list[str] = []
    for col in ("earnings_yield", "rev_to_price"):
        mu = df[col].mean(skipna=True)
        sigma = df[col].std(ddof=0, skipna=True)
        df[f"{col}_z"] = 0.0 if (pd.isna(sigma) or sigma == 0) else (df[col] - mu) / sigma
        z_cols.append(f"{col}_z")

    raw_cols = ["earnings_yield", "rev_to_price"]
    present = df[raw_cols].notna().sum(axis=1)
    df = df[present >= _MIN_COMPONENTS_REQUIRED].copy()
    if df.empty:
        return pd.DataFrame(columns=["ticker", "raw", "rank", "z_score"])

    df["raw"] = df[z_cols].mean(axis=1, skipna=True)
    df["rank"] = df["raw"].rank(ascending=False, method="min").astype(int)
    mu = df["raw"].mean()
    sigma = df["raw"].std(ddof=0)
    if sigma == 0 or pd.isna(sigma):
        df["z_score"] = 0.0
    else:
        df["z_score"] = (df["raw"] - mu) / sigma

    out = df[["ticker", "raw", "rank", "z_score"]].sort_values("rank")
    out = out.reset_index(drop=True)
    logger.debug(
        "value_factor as_of=%s: %d names ranked (from %d input)",
        as_of_ts.date(), len(out), len(rows),
    )
    return out
