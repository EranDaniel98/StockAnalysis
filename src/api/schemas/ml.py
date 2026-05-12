"""Pydantic schemas for the /api/ml surface."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class FoldMetric(BaseModel):
    model_config = ConfigDict(frozen=True)

    fold: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    n_train: int
    n_test: int
    ic_pearson: float
    ic_spearman: float
    hit_rate: float


class ModelSummaryMetrics(BaseModel):
    """Headline aggregates over the walk-forward folds."""

    model_config = ConfigDict(frozen=True)

    mean_ic_pearson: float = 0.0
    mean_ic_spearman: float = 0.0
    mean_hit_rate: float = 0.0
    n_folds: float = 0.0
    total_test_rows: float = 0.0


class ModelVersionRow(BaseModel):
    """One row from ``model_versions`` — for the API list view + /ml page."""

    model_config = ConfigDict(frozen=True)

    id: int
    model_name: str
    version: int
    trained_at: datetime
    train_window_start: datetime
    train_window_end: datetime
    horizon_days: int
    factor_set: str
    artifact_path: str
    notes: Optional[str] = None
    summary: ModelSummaryMetrics
    folds: list[FoldMetric] = Field(default_factory=list)


class ModelDriftSnapshot(BaseModel):
    """Latest drift status for one registered model."""

    model_config = ConfigDict(frozen=True)

    model_name: str
    version: int
    training_ic_mean: float
    training_ic_std: float
    rolling_ic: float
    z_score: float
    is_drifting: bool
    window_days: int
    n_observations: int


class MLModelsResponse(BaseModel):
    """List view at /api/ml/models."""

    model_config = ConfigDict(frozen=True)

    models: list[ModelVersionRow] = Field(default_factory=list)
    latest: list[ModelVersionRow] = Field(
        default_factory=list,
        description="One row per distinct model_name — the version the ensemble would use right now.",
    )
    drift: list[ModelDriftSnapshot] = Field(default_factory=list)
