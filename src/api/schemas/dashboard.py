"""Schemas for /api/dashboard — the home-page aggregated view.

The dashboard surfaces "what to act on right now" across strategies in
one place, so the user doesn't have to open /scan and re-run per
strategy. It reads the most-recent scan_run per strategy and joins the
latest OOS Sharpe / win-rate from saved sweep battery files.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class DashboardPick(BaseModel):
    """One pick row — flat enough to render in a table without a per-row
    /api/stocks roundtrip. Mirrors a subset of ``ScanResultItem``."""
    ticker: str
    name: str
    sector: str
    action: Literal["STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"]
    composite_score: float = Field(ge=0, le=100)
    strategy: str
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class StrategyCard(BaseModel):
    """Per-strategy summary tile."""
    strategy: str
    description: str
    horizon: str
    last_scan_at: Optional[datetime] = None
    last_scan_run_id: Optional[str] = None
    last_scan_universe: Optional[str] = None
    n_buys: int = 0
    top_picks: list[DashboardPick] = Field(default_factory=list)
    # OOS Sharpe from the most-recent A/B sweep with insider_flow=off (i.e.,
    # the baseline performance, no insider weighting). Null when no sweep
    # has been saved for this strategy yet.
    oos_sharpe: Optional[float] = None
    full_sharpe: Optional[float] = None
    win_rate_pct: Optional[float] = None
    sweep_universe: Optional[str] = None


class DashboardResponse(BaseModel):
    top_picks: list[DashboardPick] = Field(
        default_factory=list,
        description=(
            "Cross-strategy top BUY/STRONG BUY picks, ranked by "
            "composite_score. Deduplicated by ticker — when a ticker "
            "scored in multiple strategies, keeps the highest score."
        ),
    )
    strategies: list[StrategyCard] = Field(default_factory=list)
    generated_at: datetime
