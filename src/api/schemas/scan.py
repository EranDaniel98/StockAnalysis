"""Scan request/response models.

These mirror the legacy recommendation dict shape (src/scoring/recommender.py)
so the existing scan pipeline can emit them without translation. Phase 4 will
narrow these once the ML scorer replaces the hand-tuned composite.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

DEFAULT_STRATEGY = "swing_trading"


class ScanRequest(BaseModel):
    strategy: str = Field(default=DEFAULT_STRATEGY)
    budget: float | None = Field(default=None, gt=0)
    theme: str | None = None
    sector: str | None = None
    top: int | None = Field(default=None, gt=0, le=200)
    fresh: bool = Field(default=False, description="Bypass cache, fetch live data")


class ScanResultItem(BaseModel):
    """One recommendation row in a scan response. Permissive shape — accepts
    the existing recommender dict; web layer narrows what it renders."""

    ticker: str
    action: Literal["STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"]
    composite_score: float = Field(ge=0, le=100)
    confidence: str
    sub_scores: dict[str, float] = Field(default_factory=dict)
    reasoning: list[str] = Field(default_factory=list)
    bullish_signals: int = 0
    bearish_signals: int = 0
    breakdown: list[dict[str, Any]] = Field(default_factory=list)
    risk_management: dict[str, Any] = Field(default_factory=dict)
    sector: str = "Unknown"
    industry: str = "Unknown"
    name: str = ""
    market_cap: Optional[float] = None


class ScanResponse(BaseModel):
    run_id: str
    strategy: str
    scan_timestamp: datetime
    n_candidates: int
    n_results: int
    results: list[ScanResultItem]


class ScanSummary(BaseModel):
    """Lighter representation for the GET /api/scans list view."""

    run_id: str
    strategy: str
    scan_timestamp: datetime
    n_candidates: int
    top_ticker: str | None = None
    top_score: float | None = None
