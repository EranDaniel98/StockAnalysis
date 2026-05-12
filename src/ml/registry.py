"""Model-version registry helpers.

Two responsibilities:

1. Write side — ``register_run`` inserts a row in ``model_versions`` after
   a trainer drops an artifact on disk. Picks the next ``version`` per
   ``model_name`` so trainers don't have to think about collisions.

2. Read side — ``list_models`` / ``load_latest`` for the API and ensemble.

The artifact is the source of truth for inference; the registry row is
the source of truth for "which artifacts exist and how did they score".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import joblib
import pandas as pd
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ModelVersion
from src.ml.feature_store import DEFAULT_FACTOR_SET
from src.ml.models._base import TrainResult

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


async def list_models(
    session: AsyncSession,
    *,
    model_name: Optional[str] = None,
    limit: int = 50,
) -> list[ModelVersion]:
    """Newest first. Used by the API and the ensemble loader."""
    stmt = select(ModelVersion).order_by(desc(ModelVersion.trained_at)).limit(limit)
    if model_name:
        stmt = stmt.where(ModelVersion.model_name == model_name)
    return list((await session.execute(stmt)).scalars().all())


async def latest_per_name(session: AsyncSession) -> list[ModelVersion]:
    """One row per distinct ``model_name``, picking the most recent
    version. Cheap path for "which models would the ensemble use right now"."""
    sub = (
        select(
            ModelVersion.model_name.label("name"),
            func.max(ModelVersion.version).label("v"),
        )
        .group_by(ModelVersion.model_name)
        .subquery()
    )
    stmt = (
        select(ModelVersion)
        .join(
            sub,
            (ModelVersion.model_name == sub.c.name)
            & (ModelVersion.version == sub.c.v),
        )
        .order_by(ModelVersion.model_name)
    )
    return list((await session.execute(stmt)).scalars().all())


@dataclass
class LoadedModel:
    row: ModelVersion
    artifact: dict[str, Any]
    """The joblib payload — typically {model, feature_cols, horizon_days, params, …}."""


def load_artifact(row: ModelVersion) -> LoadedModel:
    """Read the joblib next to ``row.artifact_path`` into memory.

    The registry row is metadata; the artifact is the actual estimator.
    A missing file is treated as a hard error here — recoverable upstream
    if the caller wants to fall back.
    """
    path = Path(row.artifact_path)
    if not path.exists():
        raise FileNotFoundError(f"missing artifact for {row.model_name} v{row.version}: {path}")
    return LoadedModel(row=row, artifact=joblib.load(path))
