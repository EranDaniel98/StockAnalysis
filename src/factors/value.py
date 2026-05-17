"""Value factor — earnings yield from EDGAR PIT data.

Earnings yield (EPS_TTM / price) is the single dimensionally-correct
value signal we can compute from EDGAR + current price without
additional schema work:

  - EPS_TTM comes from FundamentalsPITLoader.compute_eps_ttm — sum of
    the trailing 4 quarterly diluted EPS rows valid on/before as_of.
  - price is the most recent close on/before as_of in the price dict.
  - earnings_yield = EPS_TTM / price → unit = 1/$ × $ = dimensionless,
    interpretable as "what fraction of price the company earns per
    year." Higher = cheaper.

Rationale
---------
Earnings yield is the most decision-useful single value signal
documented in the academic literature (Fama-French 1992; Greenblatt
2006 "Magic Formula"). It does NOT require market cap or shares
outstanding, so it stays clean even when EDGAR doesn't carry those
fields.

The pre-2026-05-17 implementation also blended in a ``rev_to_price``
proxy (``revenue / price``). That proxy was dimensionally wrong (it
omits shares-outstanding from the denominator) and was acknowledged
in the original docstring. The audit flagged it as a bug to fix
before real money; we now ship a clean single-signal value factor.

Future improvement (Phase 2): ingest shares-outstanding from the
EDGAR 10-Q / 10-K cover-page facts (``dei:EntityCommonStockShares
Outstanding``) and add a proper price-to-sales (sales yield) signal
back to the composite.

Rows without EPS_TTM (fewer than 4 quarterly EPS rows on/before
as_of, or any quarter missing diluted EPS) are dropped — they
neither help nor hurt the composite under
``composite.combine(min_overlap=...)``.
"""

from __future__ import annotations

import logging
from typing import Iterable, Mapping

import pandas as pd

from src.scoring.fundamentals_pit_loader import FundamentalsPITLoader

logger = logging.getLogger(__name__)


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


def _empty_result() -> pd.DataFrame:
    return pd.DataFrame(columns=["ticker", "raw", "rank", "z_score"])


def value_factor(
    loader: FundamentalsPITLoader,
    prices: Mapping[str, pd.DataFrame],
    tickers: Iterable[str],
    as_of: pd.Timestamp,
) -> pd.DataFrame:
    """Cross-sectional value ranking at ``as_of`` by earnings yield.

    Parameters
    ----------
    loader : EDGAR PIT loader providing ``lookup`` + ``compute_eps_ttm``.
    prices : mapping ticker → OHLCV DataFrame, used to read the close
        on/before as_of.
    tickers : universe to rank.
    as_of : as-of date. Only EDGAR rows valid on/before this date and
        prices on/before this date contribute (lookahead-safe).

    Returns
    -------
    DataFrame[ticker, raw, rank, z_score] sorted by rank ascending
    (rank 1 = highest earnings yield = cheapest by this metric).
    Tickers without 4 quarters of EDGAR EPS coverage are dropped.
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

        # earnings_yield = EPS_TTM / price. The loader sums the
        # trailing 4 quarterly EPS (10-Q rows) and returns None when
        # fewer than 4 are available — we drop those tickers rather
        # than fabricating partial-year TTM, so the factor stays
        # comparable across the universe.
        eps_ttm = loader.compute_eps_ttm(t, as_of_dt)
        if eps_ttm is None or eps_ttm <= 0:
            # Negative-earnings names don't belong in a "cheap stocks"
            # basket via this metric; dropped (not -ve yield).
            continue
        rows.append({
            "ticker": t,
            "earnings_yield": eps_ttm / price,
        })

    if not rows:
        return _empty_result()

    df = pd.DataFrame(rows)
    df["raw"] = df["earnings_yield"]
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
        "value_factor as_of=%s: %d names ranked", as_of_ts.date(), len(out),
    )
    return out
