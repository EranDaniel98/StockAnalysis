"""Analytics response models (calibration, etc.)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CalibrationBucket(BaseModel):
    label: str
    """Human-readable band label (e.g. '60-70')."""
    lower: float
    upper: float
    n_trades: int
    avg_pnl_pct: float | None = None
    median_pnl_pct: float | None = None
    win_rate: float | None = None
    """Fraction of trades with pnl_pct > 0 in [0, 1]."""


class ScoreCalibration(BaseModel):
    as_of: datetime
    n_total_trades: int
    buckets: list[CalibrationBucket] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
