"""Aggregate trade-analytics schemas.

Distinct from analytics.py (which holds the score-calibration shape) so
the surface stays readable as more aggregations are added.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class TradeHeadline(BaseModel):
    """Top-line aggregate stats over all closed paper trades."""

    n_trades: int
    n_winners: int
    n_losers: int
    n_breakeven: int
    win_rate: float
    """Fraction of trades with pnl > 0 in [0, 1]."""
    total_pnl: float
    avg_pnl: float
    avg_pnl_pct: float
    avg_win_pct: float | None = None
    """Mean pnl_pct over winners only."""
    avg_loss_pct: float | None = None
    """Mean pnl_pct over losers only (negative number)."""
    expectancy_pct: float | None = None
    """win_rate*avg_win_pct + loss_rate*avg_loss_pct."""
    profit_factor: float | None = None
    """sum(winners.pnl) / abs(sum(losers.pnl)); None when no losers."""
    avg_hold_days: float | None = None
    median_hold_days: float | None = None
    max_pnl_pct: float | None = None
    min_pnl_pct: float | None = None


class CumulativePnlPoint(BaseModel):
    date: date
    cumulative_pnl: float
    n_trades: int


class ExitReasonStat(BaseModel):
    reason: str
    n_trades: int
    avg_pnl_pct: float
    win_rate: float
    total_pnl: float


class StrategyStat(BaseModel):
    strategy: str
    n_trades: int
    avg_pnl_pct: float
    win_rate: float
    total_pnl: float


class HoldTimeBucket(BaseModel):
    label: str
    """Human-readable bucket label (e.g. '1-3 days')."""
    lower: int
    upper: int
    """Inclusive lower / exclusive upper, in days."""
    n_trades: int
    avg_pnl_pct: float | None = None
    win_rate: float | None = None


class TickerStat(BaseModel):
    ticker: str
    n_trades: int
    total_pnl: float
    avg_pnl_pct: float


class TradeAnalytics(BaseModel):
    as_of: datetime
    headline: TradeHeadline
    cumulative_pnl: list[CumulativePnlPoint] = Field(default_factory=list)
    by_exit_reason: list[ExitReasonStat] = Field(default_factory=list)
    by_strategy: list[StrategyStat] = Field(default_factory=list)
    hold_time_distribution: list[HoldTimeBucket] = Field(default_factory=list)
    top_winners: list[TickerStat] = Field(default_factory=list)
    """Sorted by total_pnl descending. Capped at 10."""
    top_losers: list[TickerStat] = Field(default_factory=list)
    """Sorted by total_pnl ascending (most negative first). Capped at 10."""
    notes: list[str] = Field(default_factory=list)
