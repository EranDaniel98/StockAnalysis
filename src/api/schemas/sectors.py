"""Sector rotation response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SectorMetric(BaseModel):
    ticker: str
    name: str
    last_close: float | None = None
    sma50: float | None = None
    above_sma50: bool | None = None
    return_1d_pct: float | None = None
    return_5d_pct: float | None = None
    return_21d_pct: float | None = None
    history_30d_pct: list[float] = Field(default_factory=list)
    """30 most recent trading days as percent-from-start (so the sparkline
    is comparable across sectors regardless of absolute price). Empty
    when fewer than 30 bars are available."""


class SectorsResponse(BaseModel):
    as_of: datetime
    sectors: list[SectorMetric] = Field(default_factory=list)
