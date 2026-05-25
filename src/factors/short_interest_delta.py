"""Short-interest delta factor (scaffold).

The idea: rapid INCREASES in short interest are a bearish signal
(smart-money shorts piling in); rapid DECREASES suggest a squeeze
risk (shorts covering, often a contrarian buy). The classic Asquith-
Pathak-Ritter 2005 result says high short-interest names underperform,
but the marginal information lives in the CHANGE not the level.

Status as of 2026-05-18: the FINRA daily-short data is loaded but only
covers ~1 year (2025-05 → 2026-05) — not enough history for a credible
3-window backtest A/B. The factor + CLI plumbing ship here so the
moment the ingest catches up, the validation is one command away.

When activated:
* For each (ticker, as_of) compute trailing 30d cumulative short volume.
* Compute the prior 30d window (60-30d ago) as baseline.
* delta = (current_30d - baseline_30d) / baseline_30d, signed.
* High DECREASE (squeeze territory) → high raw → high rank.
* Couple with the existing short_interest analyzer's days-to-cover.

Wired into the backtest via ``--include-short-interest``; off by default.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Sequence

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 30
MIN_HISTORY_DAYS = 60  # need 2 windows of history for a delta computation


async def fetch_short_delta(
    session: AsyncSession,
    *,
    tickers: Sequence[str],
    as_of: pd.Timestamp,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> pd.DataFrame:
    """Cumulative short-volume delta per ticker over the trailing
    ``window_days`` vs the prior window.

    Returns columns: ticker, current_window_vol, prior_window_vol,
    delta_pct. Empty when the FINRA short_interest table lacks
    coverage for the as_of date.
    """
    if not tickers:
        return pd.DataFrame(
            columns=[
                "ticker", "current_window_vol", "prior_window_vol", "delta_pct"
            ]
        )
    as_of_date = as_of.date() if hasattr(as_of, "date") else as_of
    current_start = pd.Timestamp(as_of_date) - timedelta(days=window_days)
    prior_end = current_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=window_days)

    stmt = text(
        """
        SELECT
            ticker,
            SUM(CASE WHEN settlement_date BETWEEN :curr_start AND :as_of
                     THEN short_volume ELSE 0 END)::float AS current_window_vol,
            SUM(CASE WHEN settlement_date BETWEEN :prior_start AND :prior_end
                     THEN short_volume ELSE 0 END)::float AS prior_window_vol
        FROM short_interest
        WHERE ticker = ANY(:tickers)
          AND settlement_date BETWEEN :prior_start AND :as_of
        GROUP BY ticker
        HAVING SUM(short_volume) > 0
        """
    )
    res = await session.execute(
        stmt,
        {
            "tickers": list(tickers),
            "as_of": as_of_date,
            "curr_start": current_start.date(),
            "prior_start": prior_start.date(),
            "prior_end": prior_end.date(),
        },
    )
    rows = res.fetchall()
    if not rows:
        return pd.DataFrame(
            columns=[
                "ticker", "current_window_vol", "prior_window_vol", "delta_pct"
            ]
        )
    df = pd.DataFrame(
        rows, columns=["ticker", "current_window_vol", "prior_window_vol"]
    )
    # delta_pct is signed. Positive = MORE shorts piling in (bearish);
    # negative = covering (squeeze potential / contrarian buy).
    df["delta_pct"] = (
        (df["current_window_vol"] - df["prior_window_vol"])
        / df["prior_window_vol"].replace(0, pd.NA)
    )
    df = df.dropna(subset=["delta_pct"])
    return df


def short_delta_factor(panel: pd.DataFrame) -> pd.DataFrame:
    """Rank panel as a factor frame.

    Convention: higher raw = better picks. We rank by NEGATIVE delta
    (largest covers / smallest increases come first) so the top of
    the frame represents names where the short bid is releasing —
    typical contrarian-long setups.
    """
    if panel.empty:
        return pd.DataFrame(columns=["ticker", "raw", "rank", "z_score"])
    sorted_panel = panel.sort_values("delta_pct").reset_index(drop=True)
    sorted_panel["raw"] = -sorted_panel["delta_pct"].astype(float)
    sorted_panel["rank"] = sorted_panel.index + 1
    mu = sorted_panel["raw"].mean()
    sigma = sorted_panel["raw"].std(ddof=0)
    sorted_panel["z_score"] = (
        (sorted_panel["raw"] - mu) / sigma if sigma > 0 else 0.0
    )
    return sorted_panel[["ticker", "raw", "rank", "z_score"]]


async def short_interest_delta_factor(
    session: AsyncSession,
    *,
    tickers: Sequence[str],
    as_of: pd.Timestamp,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> pd.DataFrame:
    """End-to-end: fetch + rank. Returns empty frame when data isn't
    loaded yet for the requested as_of window."""
    panel = await fetch_short_delta(
        session, tickers=tickers, as_of=as_of, window_days=window_days,
    )
    return short_delta_factor(panel)


__all__ = [
    "fetch_short_delta",
    "short_delta_factor",
    "short_interest_delta_factor",
    "DEFAULT_WINDOW_DAYS",
    "MIN_HISTORY_DAYS",
]
