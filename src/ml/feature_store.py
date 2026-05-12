"""Daily factor snapshot job.

For each ticker in the requested universe, run every analyzer at ``as_of``
(price history sliced to ``df.loc[:as_of]`` to enforce point-in-time
correctness) and persist the resulting sub-scores to ``factor_snapshots``.

Snapshot rows are one-per-(ticker, as_of, factor_set):
  values   {technical, fundamental, pattern, statistical, trend, alpha158}
  z_scores values minus universe mean / universe std at the same as_of date

The cross-sectional z-scores are computed here (not at training time) so
each snapshot is self-describing — a downstream model can train on either
raw values or z-scores without redoing the math.

This is intentionally a separate job from the scoring CLI. The CLI cares
about "what should I trade today"; the feature store cares about "give me
the same factors I would have computed every day for the last two years
so I can train on real out-of-sample data". They share analyzer code but
not orchestration.
"""

from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import FactorSnapshot
from src.scoring.analyzers import (
    alpha158,
    fundamental,
    patterns,
    statistical,
    technical,
)
from src.scoring.analyzers.trend_detector import analyze_stock_trend

logger = logging.getLogger(__name__)


DEFAULT_FACTOR_SET = "sub_scores_v1"
MIN_HISTORY_BARS = 260


@dataclass
class SnapshotRow:
    """In-memory snapshot before z-scoring + persistence."""

    ticker: str
    as_of: pd.Timestamp
    values: dict[str, float] = field(default_factory=dict)


def _score_at_as_of(
    ticker: str,
    df: pd.DataFrame,
    fund: dict,
    config,
    as_of: pd.Timestamp,
) -> SnapshotRow | None:
    """Slice price history at as_of and run every analyzer.

    Returns None when there's insufficient history for the analyzer pass
    (e.g. <260 bars rules out alpha158). Skipping silently is fine — the
    caller logs a count of misses.
    """
    if df is None or df.empty:
        return None

    # df.loc[:as_of] is INCLUSIVE on Pandas — and the analyzer reads the
    # last row, which means as_of itself is observable. That's correct
    # for a same-day factor signal (close-of-day → next-day trade).
    #
    # Price data may come back tz-aware (yfinance default) or tz-naive
    # (Parquet store post-migration). Normalize both sides to naive UTC.
    idx = df.index
    if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
        df = df.copy()
        df.index = idx.tz_localize(None)
    if as_of.tz is not None:
        as_of = as_of.tz_localize(None)
    df_sliced = df.loc[df.index <= as_of]
    if len(df_sliced) < MIN_HISTORY_BARS:
        return None

    try:
        tech = technical.analyze(df_sliced, config)
        fund_r = fundamental.analyze(fund or {}, config)
        pat = patterns.analyze(df_sliced, config)
        stat = statistical.analyze(df_sliced, config)
        trnd = analyze_stock_trend(df_sliced, fund or {}, config)
        a158 = alpha158.analyze(df_sliced, config)
    except Exception as e:  # noqa: BLE001 — analyzer crashes shouldn't poison the whole job
        logger.warning("analyzer failure for %s @ %s: %s", ticker, as_of.date(), e)
        return None

    def _coerce(score: Any) -> float:
        # Analyzers occasionally return NaN when their inputs are degenerate.
        # JSONB can't store NaN; treat as 0 (neutral) and let z-scoring sort it out.
        try:
            f = float(score)
        except (TypeError, ValueError):
            return 0.0
        return 0.0 if math.isnan(f) or math.isinf(f) else f

    values = {
        "technical": _coerce(tech.get("score", 0.0)),
        "fundamental": _coerce(fund_r.get("score", 0.0)),
        "pattern": _coerce(pat.get("score", 0.0)),
        "statistical": _coerce(stat.get("score", 0.0)),
        "trend": _coerce(trnd.get("score", 0.0)),
        "alpha158": _coerce(a158.get("score", 0.0)),
    }
    return SnapshotRow(ticker=ticker, as_of=as_of, values=values)


def _zscore_universe(
    rows: list[SnapshotRow],
) -> list[tuple[SnapshotRow, dict[str, float]]]:
    """Cross-sectional z-score each value across the universe at as_of.

    Returns list of (row, z_scores) tuples. Z-score uses sample std with
    ddof=1; when std is 0 (degenerate universe), z-score is 0 for that
    factor — the alternative is NaN, and JSONB can't store that cleanly.
    """
    if not rows:
        return []

    keys = sorted(rows[0].values.keys())
    matrix = pd.DataFrame([r.values for r in rows], columns=keys)
    means = matrix.mean()
    stds = matrix.std(ddof=1).replace(0, pd.NA)
    zscores = (matrix - means) / stds
    zscores = zscores.fillna(0.0)

    return [
        (row, {k: float(zscores.iloc[i][k]) for k in keys})
        for i, row in enumerate(rows)
    ]


@dataclass
class SnapshotResult:
    as_of: datetime
    n_universe: int
    n_persisted: int
    n_skipped: int


async def compute_and_persist_snapshot(
    session: AsyncSession,
    *,
    as_of: datetime,
    price_data: dict[str, pd.DataFrame],
    fundamentals: dict[str, dict],
    config,
    factor_set: str = DEFAULT_FACTOR_SET,
    workers: int = 8,
) -> SnapshotResult:
    """Compute snapshots for the supplied universe at as_of and upsert.

    Caller supplies ``price_data`` and ``fundamentals`` — keeps this function
    free of the DataFetcher dependency so it's drop-in usable from both the
    CLI command and the FastAPI lifespan-bound session.

    Uses ON CONFLICT DO UPDATE so re-running the same job overwrites,
    which is what we want when fixing an analyzer bug and regenerating
    history.
    """
    as_of_ts = pd.Timestamp(as_of)
    rows: list[SnapshotRow] = []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(
                _score_at_as_of, ticker, df, fundamentals.get(ticker, {}), config, as_of_ts
            ): ticker
            for ticker, df in price_data.items()
        }
        for fut in as_completed(futures):
            row = fut.result()
            if row is not None:
                rows.append(row)

    zscored = _zscore_universe(rows)

    if not zscored:
        return SnapshotResult(
            as_of=as_of,
            n_universe=len(price_data),
            n_persisted=0,
            n_skipped=len(price_data),
        )

    # Single bulk upsert keeps the round-trips at O(1).
    as_of_utc = (
        as_of if isinstance(as_of, datetime) and as_of.tzinfo else as_of_ts.tz_localize(timezone.utc).to_pydatetime()
    )
    payload = [
        {
            "ticker": row.ticker,
            "as_of": as_of_utc,
            "factor_set": factor_set,
            "values": row.values,
            "z_scores": z,
        }
        for row, z in zscored
    ]
    stmt = pg_insert(FactorSnapshot).values(payload)
    # stmt.excluded.values would resolve to the dict-like proxy's .values() method,
    # not the column — use bracket access to disambiguate.
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker", "as_of", "factor_set"],
        set_={
            "values": stmt.excluded["values"],
            "z_scores": stmt.excluded["z_scores"],
        },
    )
    await session.execute(stmt)
    await session.commit()

    return SnapshotResult(
        as_of=as_of,
        n_universe=len(price_data),
        n_persisted=len(zscored),
        n_skipped=len(price_data) - len(zscored),
    )


async def list_snapshot_dates(
    session: AsyncSession,
    *,
    ticker: Optional[str] = None,
    factor_set: str = DEFAULT_FACTOR_SET,
) -> list[datetime]:
    """Distinct as_of dates already present, oldest first. Useful to figure
    out where a backfill should resume."""
    from sqlalchemy import select

    stmt = (
        select(FactorSnapshot.as_of)
        .where(FactorSnapshot.factor_set == factor_set)
        .distinct()
        .order_by(FactorSnapshot.as_of)
    )
    if ticker:
        stmt = stmt.where(FactorSnapshot.ticker == ticker.upper())
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def load_snapshots(
    session: AsyncSession,
    *,
    factor_set: str = DEFAULT_FACTOR_SET,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    tickers: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Load snapshots into a long-form DataFrame.

    Columns: [ticker, as_of, <factor names…>, <z_factor names…>].
    Suitable for joining against forward returns in src/ml/dataset.py.
    """
    from sqlalchemy import select

    stmt = select(FactorSnapshot).where(FactorSnapshot.factor_set == factor_set)
    if start:
        stmt = stmt.where(FactorSnapshot.as_of >= start)
    if end:
        stmt = stmt.where(FactorSnapshot.as_of <= end)
    if tickers:
        stmt = stmt.where(FactorSnapshot.ticker.in_([t.upper() for t in tickers]))
    rows = (await session.execute(stmt)).scalars().all()

    if not rows:
        return pd.DataFrame()

    records: list[dict[str, Any]] = []
    for r in rows:
        record: dict[str, Any] = {"ticker": r.ticker, "as_of": r.as_of}
        for k, v in (r.values or {}).items():
            record[k] = v
        for k, v in (r.z_scores or {}).items():
            record[f"z_{k}"] = v
        records.append(record)
    return pd.DataFrame.from_records(records).sort_values(["as_of", "ticker"])
