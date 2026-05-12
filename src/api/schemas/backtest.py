"""Backtest request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

UniverseKind = Literal["watchlist", "portfolio", "themes", "tickers"]


class BacktestRequest(BaseModel):
    strategy: str = Field(default="swing_trading")
    universe: UniverseKind = Field(default="themes")
    tickers: list[str] | None = Field(
        default=None,
        description="Required when universe='tickers'. Ignored otherwise.",
    )
    years: float = Field(default=3.0, gt=0, le=20)
    min_score: float | None = Field(default=None, ge=0, le=100)
    max_positions: int = Field(default=20, gt=0, le=100)
    position_pct: float = Field(default=0.10, gt=0, le=1.0)
    cash: float = Field(default=10_000.0, gt=0)
    hold_days: int = Field(default=90, gt=0, le=400)
    earnings_blackout: int = Field(default=3, ge=0, le=30)
    accept_lookahead: bool = Field(default=False)
    oos_split: float = Field(default=0.30, ge=0, le=0.6)
    bootstrap_resamples: int = Field(default=0, ge=0, le=10_000)
    commission: float = Field(default=0.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)
    regulatory_bps: float = Field(default=3.0, ge=0)
    vol_target_risk: float = Field(default=0.0, ge=0, le=0.10)
    fresh: bool = Field(default=False)


class BacktestSummary(BaseModel):
    id: int
    strategy: str
    universe_label: str
    window_start: datetime
    window_end: datetime
    created_at: datetime
    n_trades: int | None = None
    oos_sharpe: float | None = None
    oos_total_return_pct: float | None = None
    oos_max_drawdown_pct: float | None = None


class BacktestResponse(BaseModel):
    id: int
    strategy: str
    window_start: datetime
    window_end: datetime
    result: dict[str, Any]
    """Full BacktestResult tree (summary, calibration, trades, equity_curve, ...)."""
