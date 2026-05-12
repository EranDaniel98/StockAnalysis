"""Market regime + macro indicator response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RegimeLabel = Literal["bull", "bear", "chop", "unknown"]


class MarketRegime(BaseModel):
    """Snapshot of the broader-market regime indicators a swing trader cares
    about. Classification is intentionally crude — the user makes the call;
    this just surfaces the inputs."""

    as_of: datetime
    label: RegimeLabel
    spy_price: float | None = None
    spy_sma200: float | None = None
    spy_above_sma200: bool | None = None
    spy_pct_from_sma200: float | None = None
    vix_level: float | None = None
    vix_avg_20d: float | None = None
    notes: list[str] = Field(default_factory=list)
