"""Cohen-Malloy-Pomorski-style insider cluster-buy factor.

The CMP-2012 result: when N or more distinct insiders independently
buy a stock on the open market within a short window, that cluster
is a strong forward-return signal (~6-10% alpha over the subsequent
year, persistent across decades, with statistical significance).

This factor scores each ticker on cluster intensity:
* Filter to open-market BUYS (transaction_code='P', acquired_disposed='A').
* PIT-correct: filing_date (when info became public) must be on-or-before
  as_of. The transaction_date can be earlier; we just need the filing to
  have hit EDGAR before our as_of.
* Count distinct owner_ciks in the trailing ``window_days`` (default 90).
* Rank ascending = better. Top names have multi-insider clusters.

Output schema matches the rest of the factor library (ticker, raw, rank,
z_score) so it composes with the m+q+v rank-blend via ``combine``.

Why count distinct owners (not total trades): two independent insiders
buying once is a stronger signal than one insider buying twice. The CMP
paper's "opportunistic insider" filter also dedupes per owner per
window — we match that.
"""

from __future__ import annotations

import logging
from typing import Sequence

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 90
DEFAULT_MIN_CLUSTER = 2


async def fetch_cluster_counts(
    session: AsyncSession,
    *,
    tickers: Sequence[str],
    as_of: pd.Timestamp,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_cluster: int = DEFAULT_MIN_CLUSTER,
) -> pd.DataFrame:
    """Return distinct-insider cluster counts per ticker as of ``as_of``.

    PIT-correct: only counts filings whose ``filing_date <= as_of``.
    Transactions within the trailing ``window_days`` (by transaction_date)
    are eligible.

    Filters:
    * transaction_code = 'P' (open-market purchase; excludes options
      exercises, dividend reinvestments, etc.)
    * acquired_disposed = 'A' (long-side; CMP signal is buys, not sells)
    * shares > 0 (defensive — bad rows can have zeros from amended Form 4s)

    Returns columns: ticker, n_insiders, total_shares, total_value_usd.
    Empty frame when no rows qualify.
    """
    if not tickers:
        return pd.DataFrame(
            columns=["ticker", "n_insiders", "total_shares", "total_value_usd"]
        )
    as_of_date = as_of.date() if hasattr(as_of, "date") else as_of
    window_start = pd.Timestamp(as_of_date) - pd.Timedelta(days=window_days)

    stmt = text(
        """
        SELECT
            ticker,
            COUNT(DISTINCT owner_cik) AS n_insiders,
            SUM(shares)::float AS total_shares,
            COALESCE(SUM(value_usd), 0)::float AS total_value_usd
        FROM insider_transactions
        WHERE ticker = ANY(:tickers)
          AND transaction_code = 'P'
          AND acquired_disposed = 'A'
          AND shares > 0
          AND filing_date <= :as_of
          AND transaction_date >= :window_start
          AND transaction_date <= :as_of
        GROUP BY ticker
        HAVING COUNT(DISTINCT owner_cik) >= :min_cluster
        """
    )
    result = await session.execute(
        stmt,
        {
            "tickers": list(tickers),
            "as_of": as_of_date,
            "window_start": window_start.date(),
            "min_cluster": int(min_cluster),
        },
    )
    rows = result.fetchall()
    if not rows:
        return pd.DataFrame(
            columns=["ticker", "n_insiders", "total_shares", "total_value_usd"]
        )
    return pd.DataFrame(rows, columns=["ticker", "n_insiders", "total_shares", "total_value_usd"])


def cluster_factor(panel: pd.DataFrame) -> pd.DataFrame:
    """Rank cluster-count panel as a factor frame.

    Tie-break ladder: n_insiders (descending) → total_value_usd
    (descending) → total_shares (descending). This lifts the rare
    multi-insider clusters above the more common 2-insider noise.
    """
    if panel.empty:
        return pd.DataFrame(columns=["ticker", "raw", "rank", "z_score"])

    sorted_panel = panel.sort_values(
        ["n_insiders", "total_value_usd", "total_shares"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    # raw = n_insiders so higher = better, matching the factor library
    # "higher raw is good" convention.
    sorted_panel["raw"] = sorted_panel["n_insiders"].astype(float)
    sorted_panel["rank"] = sorted_panel.index + 1
    mu = sorted_panel["raw"].mean()
    sigma = sorted_panel["raw"].std(ddof=0)
    sorted_panel["z_score"] = (
        (sorted_panel["raw"] - mu) / sigma if sigma > 0 else 0.0
    )
    return sorted_panel[["ticker", "raw", "rank", "z_score"]]


async def insider_cluster_factor(
    session: AsyncSession,
    *,
    tickers: Sequence[str],
    as_of: pd.Timestamp,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_cluster: int = DEFAULT_MIN_CLUSTER,
) -> pd.DataFrame:
    """End-to-end: query DB, rank, return factor frame.

    Universe semantics: only tickers that produced a qualifying
    cluster appear in the output. Use min_overlap=2 (or smaller) when
    combining with m+q+v so a ticker without an insider signal still
    gets ranked on the other factors.
    """
    panel = await fetch_cluster_counts(
        session, tickers=tickers, as_of=as_of,
        window_days=window_days, min_cluster=min_cluster,
    )
    return cluster_factor(panel)


__all__ = [
    "fetch_cluster_counts",
    "cluster_factor",
    "insider_cluster_factor",
    "DEFAULT_WINDOW_DAYS",
    "DEFAULT_MIN_CLUSTER",
]
