"""Trade journal request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PaperTradeItem(BaseModel):
    id: int
    ticker: str
    qty: float
    entry_price: float
    exit_price: float
    entry_at: datetime
    exit_at: datetime
    hold_days: int | None = None
    pnl: float
    pnl_pct: float
    exit_reason: Optional[str] = None
    composite_score: float | None = None
    notes: Optional[str] = None


class TradeNotesUpdate(BaseModel):
    notes: Optional[str] = Field(
        default=None,
        description="Set to null/omit to clear; otherwise replaces the journal entry.",
    )
