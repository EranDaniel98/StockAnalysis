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


class SectorsResponse(BaseModel):
    as_of: datetime
    sectors: list[SectorMetric] = Field(default_factory=list)
