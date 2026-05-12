"""/api/ml — registered ML models, training history, drift status.

Powers the /ml frontend page. Drift is computed on the fly from the
latest ensemble run vs realized forward returns — no separate alerts
table; the frontend polls.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db_session
from src.api.schemas.ml import (
    FoldMetric,
    MLModelsResponse,
    ModelDriftSnapshot,
    ModelSummaryMetrics,
    ModelVersionRow,
)
from src.db.models import ModelVersion
from src.ml.dataset import build_training_matrix
from src.ml.drift import DriftSnapshot, detect_drift
from src.ml.ensemble import Ensemble
from src.ml.registry import latest_per_name, list_models

logger = logging.getLogger(__name__)
router = APIRouter()


def _row_to_schema(row: ModelVersion) -> ModelVersionRow:
    metrics = row.metrics or {}
    summary = metrics.get("summary") or {}
    folds = metrics.get("folds") or []
    return ModelVersionRow(
        id=row.id,
        model_name=row.model_name,
        version=row.version,
        trained_at=row.trained_at,
        train_window_start=row.train_window_start,
        train_window_end=row.train_window_end,
        horizon_days=row.horizon_days,
        factor_set=row.factor_set,
        artifact_path=row.artifact_path,
        notes=row.notes,
        summary=ModelSummaryMetrics(**{k: float(v) for k, v in summary.items()}),
        folds=[FoldMetric(**f) for f in folds],
    )


def _drift_to_schema(snap: DriftSnapshot) -> ModelDriftSnapshot:
    return ModelDriftSnapshot(
        model_name=snap.model_name,
        version=snap.version,
        training_ic_mean=snap.training_ic_mean,
        training_ic_std=snap.training_ic_std,
        rolling_ic=snap.rolling_ic,
        z_score=snap.z_score,
        is_drifting=snap.is_drifting,
        window_days=snap.window_days,
        n_observations=snap.n_observations,
    )


async def _compute_drift(
    db: AsyncSession,
    latest_rows: list[ModelVersion],
    *,
    window_days: int,
) -> list[ModelDriftSnapshot]:
    """For each latest-per-model row, score the ensemble against realized
    forward returns over the most recent window and detect drift.

    If the registry is empty or no factor snapshots have forward returns
    yet (early backfill), we silently return an empty list — the page
    renders the "no drift data yet" state rather than 500ing."""
    if not latest_rows:
        return []

    horizon = max(r.horizon_days for r in latest_rows)
    try:
        matrix = await build_training_matrix(db, horizon=horizon)
    except Exception as e:  # noqa: BLE001 — backfills can be partial; don't 500 the page
        logger.warning("drift: failed to build matrix (%s)", e)
        return []
    if matrix.df.empty:
        return []

    df = matrix.df.copy()
    df["as_of"] = pd.to_datetime(df["as_of"])
    cutoff = df["as_of"].max() - pd.Timedelta(days=window_days * 2)
    df = df[df["as_of"] >= cutoff]
    if df.empty:
        return []

    snapshots: list[ModelDriftSnapshot] = []
    for row in latest_rows:
        try:
            ensemble = Ensemble.from_rows([row])
            preds = ensemble.predict(df).preds
        except Exception as e:  # noqa: BLE001 — missing artifact, predict-time mismatch
            logger.warning(
                "drift: cannot score %s v%d (%s)", row.model_name, row.version, e
            )
            continue
        realized = df.copy()
        realized["prediction"] = preds
        snap = detect_drift(row, realized, window_days=window_days)
        snapshots.append(_drift_to_schema(snap))
    return snapshots


@router.get("/models", response_model=MLModelsResponse)
async def list_ml_models(
    model_name: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    window_days: int = Query(default=30, ge=7, le=180),
    db: AsyncSession = Depends(get_db_session),
) -> MLModelsResponse:
    """List registered model versions + drift status for the latest of each name.

    Filter to a single ``model_name`` to see its history. Without a filter,
    you get the full registry (newest first) plus a "latest per name" view
    that mirrors what the ensemble would use right now.
    """
    all_rows = await list_models(db, model_name=model_name, limit=limit)
    latest = await latest_per_name(db)
    drift = await _compute_drift(db, latest, window_days=window_days)
    return MLModelsResponse(
        models=[_row_to_schema(r) for r in all_rows],
        latest=[_row_to_schema(r) for r in latest],
        drift=drift,
    )
