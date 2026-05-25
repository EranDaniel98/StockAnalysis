"""Jegadeesh-Titman 12-1 month momentum factor.

For each ticker at ``as_of_date``:

  raw = price(as_of - 21 trading days) / price(as_of - 252 trading days) - 1

The "skip-the-most-recent-month" convention (-21d to -252d, not 0 to
-252d) is the canonical academic form — it controls for short-term
mean reversion that contaminates the prior-month return.

Why this factor:

- Documented in literature back to 1993. The "momentum premium" has
  one of the largest published Sharpe ratios of any single factor
  (~0.5-0.8 long-short, ~3-5% alpha long-only).
- Survives multiple decades of out-of-sample testing (FF 2018 update).
- Mechanism is behavioral (underreaction to news / herding) and
  structural (window-dressing), so it's robust to regime change.
- Long-only momentum has a known weakness: catastrophic 2008-style
  crashes when leadership flips. We mitigate with the SPY trend
  filter in ``src.factors.regime``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)

# Trading-day conventions (matches academic standard). These are
# COUNTS of trading rows, not calendar days. Prices are assumed to be
# indexed at trading-day granularity (one row per market session).
LOOKBACK_DAYS = 252  # 12 months
SKIP_DAYS = 21       # 1 month


@dataclass(frozen=True)
class FactorScore:
    """One row of a factor output table."""

    ticker: str
    raw: float
    rank: int  # 1 = strongest (highest raw); ties get same rank
    z_score: float


def _close_at_offset(
    prices: pd.DataFrame, as_of: pd.Timestamp, offset: int,
) -> float | None:
    """The Close ``offset`` trading rows before the last row at-or-before as_of.

    offset=0 → most recent close ≤ as_of.
    offset=21 → 21 trading sessions before that one.

    Returns None if the price frame doesn't have enough history.
    """
    if prices is None or prices.empty or "Close" not in prices.columns:
        return None
    idx = prices.index
    if not isinstance(idx, pd.DatetimeIndex):
        return None
    eligible = prices[prices.index <= as_of]
    if len(eligible) <= offset:
        return None
    close = eligible["Close"].iloc[-(offset + 1)]
    if pd.isna(close):
        return None
    return float(close)


def momentum_12_1(
    prices: Mapping[str, pd.DataFrame],
    as_of: pd.Timestamp | str,
    *,
    min_history_days: int = LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Compute cross-sectional 12-1 month momentum for each ticker.

    Parameters
    ----------
    prices : mapping ticker -> OHLCV DataFrame (DatetimeIndex,
        column 'Close'). Frames may have extra columns; only 'Close'
        is read.
    as_of : the as-of date. Tickers without ``min_history_days`` of
        history before ``as_of`` are dropped.

    Returns
    -------
    DataFrame with columns ``ticker, raw, rank, z_score``.
    Sorted ascending by rank (rank 1 = highest momentum).

    Lookahead safety
    ----------------
    Only reads prices indexed on or before ``as_of - SKIP_DAYS``. Even
    a price dated ``as_of`` exactly is not used (the skip window
    explicitly excludes the most recent month).
    """
    as_of_ts = pd.Timestamp(as_of)

    rows: list[dict] = []
    for ticker, df in prices.items():
        if df is None or df.empty:
            continue
        eligible = df[df.index <= as_of_ts]
        if len(eligible) < min_history_days:
            continue

        # The skip-month anchor (price at as_of - 21 trading sessions).
        recent = _close_at_offset(df, as_of_ts, SKIP_DAYS)
        # The 12-month anchor (price at as_of - 252 trading sessions).
        old = _close_at_offset(df, as_of_ts, LOOKBACK_DAYS)
        if recent is None or old is None or old <= 0:
            continue

        raw = recent / old - 1.0
        rows.append({"ticker": ticker, "raw": raw})

    if not rows:
        return pd.DataFrame(columns=["ticker", "raw", "rank", "z_score"])

    out = pd.DataFrame(rows)
    # Rank 1 = highest raw return (best momentum).
    out["rank"] = out["raw"].rank(ascending=False, method="min").astype(int)
    mu = float(out["raw"].mean())
    sigma = float(out["raw"].std(ddof=0))
    if sigma > 0:
        out["z_score"] = (out["raw"] - mu) / sigma
    else:
        out["z_score"] = 0.0
    out = out.sort_values("rank").reset_index(drop=True)
    logger.debug(
        "momentum_12_1 as_of=%s: %d names, mean raw=%.4f, sigma=%.4f",
        as_of_ts.date(), len(out), mu, sigma,
    )
    return out
