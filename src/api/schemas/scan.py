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


Universe = Literal["themes", "russell_1000", "value_cohort", "watchlist"]


class ScanRequest(BaseModel):
    strategy: str = Field(default=DEFAULT_STRATEGY)
    budget: float | None = Field(default=None, gt=0)
    universe: Universe | None = Field(
        default=None,
        description=(
            "Ticker universe. 'themes' (default) uses the configured theme "
            "set (~67 tickers, fast). 'russell_1000' scans the full "
            "Russell-1000 holdings (~1000 tickers, slow — ~15-30min with "
            "live_signals=True). 'value_cohort' / 'watchlist' use the "
            "configured lists. When omitted, falls back to 'themes' OR a "
            "theme/sector filter if provided."
        ),
    )
    theme: str | None = None
    sector: str | None = None
    top: int | None = Field(default=None, gt=0, le=200)
    fresh: bool = Field(default=False, description="Bypass cache, fetch live data")
    live_signals: bool = Field(
        default=True,
        description=(
            "Fetch yfinance-backed analyst_revisions + options_skew. "
            "Disable on large universes (russell_1000) for speed."
        ),
    )


class ScanResultItem(BaseModel):
    """One recommendation row in a scan response. Permissive shape — accepts
    the existing recommender dict; web layer narrows what it renders.

    Integrity fields (``score_valid``, ``error_count``, ``error_slots``,
    ``analyzer_status``, ``instrument_warning``, ``insufficient_history``)
    are surfaced so the FE can render a Data-Quality warning when the
    composite was built from a degraded analyzer chain, a leveraged /
    inverse ETF, or a ticker with too little history. The recommender
    already forces ``action="HOLD"``/``confidence="None"`` in those
    cases — these fields tell the operator WHY.
    """

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
    # Integrity flags — see docstring above.
    score_valid: bool = True
    error_count: int = 0
    error_slots: list[str] = Field(default_factory=list)
    analyzer_status: dict[str, str] = Field(default_factory=dict)
    instrument_warning: Optional[str] = None
    instrument_warning_reason: Optional[str] = None
    insufficient_history: bool = False
    history_bars_available: Optional[int] = None
    history_bars_required: Optional[int] = None


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
