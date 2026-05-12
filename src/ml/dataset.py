"""Build the (factors → forward return) training matrix.

Joins ``factor_snapshots`` rows against actual realized forward returns
computed from the Parquet OHLCV store. Output is a long-form DataFrame
ready for sklearn / lightgbm:

  columns: [as_of, ticker, <factor names>, <z_factor names>, forward_return,
            forward_horizon_days, regime_label?]
  one row per (as_of, ticker) snapshot.

Point-in-time semantics: the forward return for (ticker, as_of) uses
close on as_of as entry and close on (as_of + horizon trading days) as
exit. Snapshots whose forward window extends past the available price
data are dropped — there's no label to learn against.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.ml.feature_store import DEFAULT_FACTOR_SET, load_snapshots
from src.storage.parquet_ohlcv import ParquetPriceRepository

logger = logging.getLogger(__name__)


FACTOR_COLUMNS = [
    "technical",
    "fundamental",
    "pattern",
    "statistical",
    "trend",
    "alpha158",
]
Z_FACTOR_COLUMNS = [f"z_{c}" for c in FACTOR_COLUMNS]


@dataclass
class TrainingMatrix:
    df: pd.DataFrame
    """Long-form rows: see module docstring."""

    horizon: int
    """Forward-return horizon in trading days."""

    feature_cols: list[str]
    """Column names a model should treat as inputs."""

    label_col: str = "forward_return"


def _compute_forward_return(prices: pd.DataFrame, as_of: pd.Timestamp, horizon: int) -> float | None:
    """Realized total return from the close on as_of to the close N trading
    days later. Returns None if either anchor is missing — the caller drops
    those rows so the model never sees half-formed labels."""
    if prices is None or prices.empty:
        return None
    if as_of.tz is not None:
        as_of = as_of.tz_localize(None)
    idx = prices.index
    if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
        prices = prices.copy()
        prices.index = idx.tz_localize(None)

    after = prices[prices.index >= as_of]
    if len(after) <= horizon:
        return None
    entry = float(after["Close"].iloc[0])
    exit_price = float(after["Close"].iloc[horizon])
    if entry <= 0:
        return None
    return (exit_price / entry - 1.0) * 100.0


async def build_training_matrix(
    session: AsyncSession,
    *,
    horizon: int = 5,
    factor_set: str = DEFAULT_FACTOR_SET,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    tickers: Optional[list[str]] = None,
    price_repo: Optional[ParquetPriceRepository] = None,
) -> TrainingMatrix:
    """Load all snapshots in [start, end], compute forward returns, return
    a DataFrame ready for ``model.fit(df[feature_cols], df[label_col])``.

    ``horizon`` is in **trading** days (i.e. positions in the price-data
    DataFrame, not calendar days), because that's what we'd execute on.

    ``price_repo`` is optional — when omitted, we build one. Pass an
    existing instance from the FastAPI lifespan to avoid re-reading the
    same Parquet pages.
    """
    snapshots = await load_snapshots(
        session, factor_set=factor_set, start=start, end=end, tickers=tickers
    )
    if snapshots.empty:
        return TrainingMatrix(
            df=pd.DataFrame(),
            horizon=horizon,
            feature_cols=FACTOR_COLUMNS + Z_FACTOR_COLUMNS,
        )

    repo = price_repo or ParquetPriceRepository()

    # Group by ticker so we only load each Parquet file once.
    enriched: list[pd.DataFrame] = []
    for ticker, ticker_snaps in snapshots.groupby("ticker"):
        min_ts = pd.Timestamp(ticker_snaps["as_of"].min())
        max_ts = pd.Timestamp(ticker_snaps["as_of"].max())
        if min_ts.tz is not None:
            min_ts = min_ts.tz_localize(None)
        if max_ts.tz is not None:
            max_ts = max_ts.tz_localize(None)
        # Pad the end so we always have horizon+buffer days past the latest snapshot.
        prices = repo._read_sync(  # noqa: SLF001 — internal helper, kept here until repo grows a typed public API
            ticker,
            min_ts.to_pydatetime(),
            (max_ts + pd.Timedelta(days=horizon * 3 + 30)).to_pydatetime(),
        )
        if prices is None or prices.empty:
            logger.debug("no price history for %s — skipping", ticker)
            continue

        ticker_snaps = ticker_snaps.copy()
        ticker_snaps["forward_return"] = [
            _compute_forward_return(prices, pd.Timestamp(ts), horizon)
            for ts in ticker_snaps["as_of"]
        ]
        enriched.append(ticker_snaps)

    if not enriched:
        return TrainingMatrix(
            df=pd.DataFrame(),
            horizon=horizon,
            feature_cols=FACTOR_COLUMNS + Z_FACTOR_COLUMNS,
        )

    merged = pd.concat(enriched, ignore_index=True)
    merged = merged.dropna(subset=["forward_return"])
    merged = merged.replace([np.inf, -np.inf], np.nan).dropna(
        subset=FACTOR_COLUMNS + ["forward_return"]
    )
    merged["forward_horizon_days"] = horizon
    merged = merged.sort_values(["as_of", "ticker"]).reset_index(drop=True)

    return TrainingMatrix(
        df=merged,
        horizon=horizon,
        feature_cols=FACTOR_COLUMNS + Z_FACTOR_COLUMNS,
    )
