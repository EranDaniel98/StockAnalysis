"""Model-version registry helpers.

Inserts a row in ``model_versions`` after a trainer drops an artifact on
disk. Picks the next ``version`` per ``model_name`` so trainers don't
have to think about collisions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ModelVersion
from src.ml.feature_store import DEFAULT_FACTOR_SET
from src.ml.models.lightgbm_trainer import TrainResult

logger = logging.getLogger(__name__)


def _to_pg_ts(value: str | datetime | pd.Timestamp) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    ts = pd.Timestamp(value)
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    return ts.to_pydatetime()


async def _next_version(session: AsyncSession, model_name: str) -> int:
    stmt = select(func.max(ModelVersion.version)).where(
        ModelVersion.model_name == model_name
    )
    current = (await session.execute(stmt)).scalar_one_or_none()
    return (current or 0) + 1


async def register_run(
    session: AsyncSession,
    result: TrainResult,
    *,
    factor_set: str = DEFAULT_FACTOR_SET,
    notes: str | None = None,
) -> ModelVersion:
    """Insert + return a new ``model_versions`` row for this training run."""
    if result.artifact_path is None:
        raise ValueError("TrainResult.artifact_path is unset; trainer must persist first")

    version = await _next_version(session, result.model_name)
    row = ModelVersion(
        model_name=result.model_name,
        version=version,
        trained_at=datetime.now(timezone.utc),
        train_window_start=_to_pg_ts(result.train_window_start),
        train_window_end=_to_pg_ts(result.train_window_end),
        horizon_days=result.horizon_days,
        factor_set=factor_set,
        params=result.params,
        metrics={
            "summary": result.summary_metrics,
            "folds": [vars(f) for f in result.fold_metrics],
            "n_rows_final_fit": result.final_n_rows,
        },
        artifact_path=str(result.artifact_path),
        notes=notes,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    logger.info(
        "registered %s v%d (id=%d) mean_ic=%.3f",
        row.model_name,
        row.version,
        row.id,
        result.summary_metrics.get("mean_ic_pearson", 0.0),
    )
    return row
