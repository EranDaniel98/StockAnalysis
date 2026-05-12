"""Recommendation response models (paper-trading subset)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PaperRecommendationItem(BaseModel):
    id: int
    ticker: str
    strategy: str
    scan_timestamp: datetime
    composite_score: float = Field(ge=0, le=100)
    action: Literal["STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"]
    sub_scores: dict[str, float] = Field(default_factory=dict)
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    sector: str | None = None
    earnings_in_days: int | None = None
    submitted: bool = False
    skip_reason: str | None = None
