"""Scan request/response models.

These mirror the legacy recommendation dict shape (src/scoring/recommender.py)
so the existing scan pipeline can emit them without translation. Phase 4 will
narrow these once the ML scorer replaces the hand-tuned composite.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from src.api.schemas.risk import RiskManagement
from src.scoring.instrument_classifier import InstrumentWarning

DEFAULT_STRATEGY = "swing_trading"


# Unix epoch seconds for years 2000-2100. Used by the earnings-calendar
# field validators below to catch the "yfinance returned milliseconds
# instead of seconds" footgun before a "Reports in 19000d" reaches the
# user's screen.
_EPOCH_SECONDS_MIN = 946_684_800        # 2000-01-01 UTC
_EPOCH_SECONDS_MAX = 4_102_444_800      # 2100-01-01 UTC


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
    # Replaces the previous dict[str, Any] shape. Defaulted to an empty
    # RiskManagement (all fields None) so the refusal-gate code in the
    # recommender can still emit ``risk_management={}`` and parse cleanly
    # — pydantic coerces the empty dict.
    risk_management: RiskManagement = Field(default_factory=RiskManagement)
    sector: str = "Unknown"
    industry: str = "Unknown"
    name: str = ""
    market_cap: Optional[float] = None
    # Integrity flags — see docstring above.
    score_valid: bool = True
    error_count: int = 0
    error_slots: list[str] = Field(default_factory=list)
    analyzer_status: dict[str, str] = Field(default_factory=dict)
    instrument_warning: Optional[InstrumentWarning] = None
    instrument_warning_reason: Optional[str] = None
    insufficient_history: bool = False
    history_bars_available: Optional[int] = None
    history_bars_required: Optional[int] = None
    # Earnings calendar (unix epoch seconds, UTC). FE formats per the
    # user's locale; earnings_call_ts is the management conference
    # call (~1 h after the post-close release). Range-validated so a
    # yfinance ms-instead-of-seconds bug surfaces as None (skip the
    # field) rather than "Reports in 19000d".
    earnings_announcement_ts: Optional[float] = None
    earnings_call_ts: Optional[float] = None
    earnings_window_start: Optional[float] = None
    earnings_window_end: Optional[float] = None

    @field_validator(
        "earnings_announcement_ts",
        "earnings_call_ts",
        "earnings_window_start",
        "earnings_window_end",
        mode="before",
    )
    @classmethod
    def _validate_unix_seconds_range(cls, v: object) -> Optional[float]:
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if not _EPOCH_SECONDS_MIN <= f <= _EPOCH_SECONDS_MAX:
            # Most common cause: yfinance handed back milliseconds
            # (10^12-ish) instead of seconds (10^9-ish). Nullify
            # rather than crashing the whole scan response.
            return None
        return f


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


class BuySignal(BaseModel):
    """One ticker with a current BUY+ signal from the latest scan per strategy.

    Deduped across strategies: each ticker appears once, attributed to the
    strategy that produced its highest composite_score. ``consensus_count``
    counts how many strategies' latest runs all flagged this ticker as
    BUY+ — high consensus = stronger conviction.
    """

    ticker: str
    name: str = ""
    sector: str = "Unknown"
    industry: str = "Unknown"
    market_cap: Optional[float] = None

    action: Literal["STRONG BUY", "BUY"]
    composite_score: float = Field(ge=0, le=100)
    confidence: str

    # Provenance: which scan this row came from.
    strategy: str
    scan_timestamp: datetime
    run_id: str

    # Cross-strategy agreement on this ticker.
    consensus_count: int = Field(ge=1)
    consensus_strategies: list[str] = Field(default_factory=list)

    # Sub-score breakdown from the *best* strategy's run for this ticker
    # (the one whose composite_score won attribution above). Surfaced so
    # the FE can filter "find me BUY signals where alpha158 ≥ 70" or
    # "fundamental ≥ 60 AND technical ≥ 50" without an extra API call.
    # Different strategies weight analyzers differently, so the same
    # ticker's sub-scores can vary across runs — this is the slice
    # corresponding to ``strategy`` above.
    sub_scores: dict[str, float] = Field(default_factory=dict)

    # Earnings calendar (passthrough — see ScanResultItem).
    earnings_announcement_ts: Optional[float] = None
    earnings_call_ts: Optional[float] = None
