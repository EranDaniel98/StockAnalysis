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
from src.scoring.catalyst_anchors import anchor_keys
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

# Narrative features merged in as_of-backward from insider_narrative_snapshots.
# ``sim_<anchor>`` columns are imputed to 0.0 when no recent cluster exists;
# ``has_recent_narrative`` distinguishes "no signal" (False, sims=0) from
# "low-similarity signal" (True, sims close to 0). Tree models gain
# discriminative power from the flag even when the sims are imputed.
NARRATIVE_SIM_COLUMNS = [f"sim_{k}" for k in anchor_keys()]
NARRATIVE_AUX_COLUMNS = [
    "has_recent_narrative",
    "has_recent_8k",
    "narrative_age_days",
    "days_to_filing",
    "narrative_skew",
]
NARRATIVE_FEATURE_COLUMNS = NARRATIVE_SIM_COLUMNS + NARRATIVE_AUX_COLUMNS

# Max age (calendar days) between a narrative snapshot's cluster_end_date
# and a training row's as_of for the merge to be considered "recent."
# CMP-2012 found the insider-cluster drift extends 6-12 months; 60 days is
# the conservative end of that range — far enough that we have signal on
# every reasonable horizon, short enough that the most recent buy still
# dominates a stale older one.
DEFAULT_NARRATIVE_MAX_AGE_DAYS = 60


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


async def load_insider_narrative_snapshots(
    session: AsyncSession,
    *,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    tickers: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Load insider_narrative_snapshots into a long-form DataFrame.

    Columns: ``ticker``, ``cluster_end_date`` (timestamp), plus every
    ``sim_<anchor>`` and the aux fields ``has_recent_8k``,
    ``days_to_filing``, ``narrative_skew``. Caller does the as-of merge
    against the training rows.
    """
    from sqlalchemy import select

    from src.db.models import InsiderNarrativeSnapshot

    stmt = select(InsiderNarrativeSnapshot)
    if start:
        stmt = stmt.where(InsiderNarrativeSnapshot.cluster_end_date >= start)
    if end:
        stmt = stmt.where(InsiderNarrativeSnapshot.cluster_end_date <= end)
    if tickers:
        stmt = stmt.where(
            InsiderNarrativeSnapshot.ticker.in_([t.upper() for t in tickers])
        )
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return pd.DataFrame(
            columns=["ticker", "cluster_end_date"] + NARRATIVE_FEATURE_COLUMNS
        )

    records: list[dict[str, Any]] = []
    for r in rows:
        record: dict[str, Any] = {
            "ticker": r.ticker,
            "cluster_end_date": pd.Timestamp(r.cluster_end_date),
            "has_recent_8k": bool(r.has_recent_8k),
            "days_to_filing": r.days_to_filing,
            "narrative_skew": r.narrative_skew,
        }
        for k in anchor_keys():
            record[f"sim_{k}"] = getattr(r, f"sim_{k}", None)
        records.append(record)
    return pd.DataFrame.from_records(records).sort_values(
        ["ticker", "cluster_end_date"]
    )


def _merge_narrative_asof(
    snapshots: pd.DataFrame,
    narratives: pd.DataFrame,
    *,
    max_age_days: int = DEFAULT_NARRATIVE_MAX_AGE_DAYS,
) -> pd.DataFrame:
    """Per-row as-of-backward merge: for each training row (ticker,
    as_of), attach the most recent narrative snapshot with
    cluster_end_date <= as_of, within ``max_age_days`` calendar days.

    Pure-function over DataFrames — no DB. Designed to be testable with
    hand-built inputs. Returns a new DataFrame with the narrative
    columns spliced in; ``has_recent_narrative`` is True iff a snapshot
    landed in the tolerance window. Sims default to 0.0, aux fields to
    None when no snapshot matched.
    """
    if snapshots.empty:
        return snapshots.copy()

    out = snapshots.copy()
    # Defaults for rows where the merge finds nothing — set up here so
    # the post-merge fill is a simple ``combine_first`` instead of
    # column-by-column conditional writes.
    for col in NARRATIVE_SIM_COLUMNS:
        out[col] = 0.0
    out["has_recent_narrative"] = False
    out["has_recent_8k"] = False
    out["days_to_filing"] = None
    out["narrative_age_days"] = None
    out["narrative_skew"] = None

    if narratives.empty:
        return out

    # ``merge_asof`` requires both sides sorted by the on-key; merge is
    # backward (find latest <= as_of) with a calendar-day tolerance.
    snaps_sorted = out[["ticker", "as_of"]].copy()
    snaps_sorted["_orig_idx"] = snaps_sorted.index
    snaps_sorted = snaps_sorted.sort_values("as_of")
    nars_sorted = narratives.sort_values("cluster_end_date")

    merged = pd.merge_asof(
        snaps_sorted,
        nars_sorted,
        left_on="as_of",
        right_on="cluster_end_date",
        by="ticker",
        direction="backward",
        tolerance=pd.Timedelta(days=max_age_days),
    )
    merged = merged.set_index("_orig_idx").reindex(out.index)

    matched_mask = merged["cluster_end_date"].notna()
    out.loc[matched_mask, "has_recent_narrative"] = True
    for col in NARRATIVE_SIM_COLUMNS:
        out.loc[matched_mask, col] = merged.loc[matched_mask, col].astype(float)
    # has_recent_8k from snapshot when matched; else False (already set).
    out.loc[matched_mask, "has_recent_8k"] = (
        merged.loc[matched_mask, "has_recent_8k"].astype(bool)
    )
    out.loc[matched_mask, "days_to_filing"] = merged.loc[matched_mask, "days_to_filing"]
    out.loc[matched_mask, "narrative_skew"] = merged.loc[matched_mask, "narrative_skew"]
    out.loc[matched_mask, "narrative_age_days"] = (
        (out.loc[matched_mask, "as_of"] - merged.loc[matched_mask, "cluster_end_date"])
        .dt.days
    )
    return out


async def build_training_matrix(
    session: AsyncSession,
    *,
    horizon: int = 5,
    factor_set: str = DEFAULT_FACTOR_SET,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    tickers: Optional[list[str]] = None,
    price_repo: Optional[ParquetPriceRepository] = None,
    include_narrative: bool = True,
    narrative_max_age_days: int = DEFAULT_NARRATIVE_MAX_AGE_DAYS,
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
    feature_cols = list(FACTOR_COLUMNS + Z_FACTOR_COLUMNS)
    if include_narrative:
        feature_cols = feature_cols + list(NARRATIVE_FEATURE_COLUMNS)
    if snapshots.empty:
        return TrainingMatrix(
            df=pd.DataFrame(),
            horizon=horizon,
            feature_cols=feature_cols,
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
            feature_cols=feature_cols,
        )

    merged = pd.concat(enriched, ignore_index=True)
    merged = merged.dropna(subset=["forward_return"])
    merged = merged.replace([np.inf, -np.inf], np.nan).dropna(
        subset=FACTOR_COLUMNS + ["forward_return"]
    )

    # Splice insider-narrative features in via as-of-backward merge.
    # Skipped when include_narrative=False (legacy callers) or when the
    # snapshots table is empty (e.g. fresh dev DB without backfill).
    if include_narrative:
        narratives = await load_insider_narrative_snapshots(
            session,
            start=start,
            end=end,
            tickers=tickers,
        )
        merged = _merge_narrative_asof(
            merged, narratives, max_age_days=narrative_max_age_days
        )

    merged["forward_horizon_days"] = horizon
    merged = merged.sort_values(["as_of", "ticker"]).reset_index(drop=True)

    return TrainingMatrix(
        df=merged,
        horizon=horizon,
        feature_cols=feature_cols,
    )
