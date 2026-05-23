"""Scan-surface schemas.

After the 5-engine → factor-pipeline migration the only schema the API
still emits here is ``BuySignal`` (returned by ``GET /api/scans/factor-picks``).
The legacy ``ScanRequest`` / ``ScanResponse`` / ``ScanResultItem`` /
``ScanSummary`` / ``SanityCheckTriggerRequest`` models were tied to the
deleted ``POST /api/scans`` route and went with it 2026-05-23.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from src.api.schemas.sanity import SanityCheck


class BuySignal(BaseModel):
    """One ticker with a current BUY+ signal from today's factor picks.

    Returned by ``GET /api/scans/factor-picks`` after the picks-reader
    maps ``data/daily_picks/YYYY-MM-DD.json`` into a UI-friendly shape.
    ``consensus_count`` is always ``1`` after the legacy cross-strategy
    pooling was removed; the field is kept for FE component compatibility.
    """

    ticker: str
    name: str = ""
    sector: str = "Unknown"
    industry: str = "Unknown"
    market_cap: Optional[float] = None

    action: Literal["STRONG BUY", "BUY"]
    composite_score: float = Field(ge=0, le=100)
    confidence: str

    strategy: str
    scan_timestamp: datetime
    run_id: str

    consensus_count: int = Field(ge=1)
    consensus_strategies: list[str] = Field(default_factory=list)

    sub_scores: dict[str, float] = Field(default_factory=dict)

    earnings_announcement_ts: Optional[float] = None
    earnings_call_ts: Optional[float] = None

    sanity_check: Optional[SanityCheck] = None
