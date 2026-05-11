"""Backtest result entities."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ExitReason = Literal[
    "target_hit",
    "stop_hit",
    "max_hold",
    "backtest_end",
    "delisted_or_halted",
    "earnings_blackout",
    "manual",
]


class BacktestTrade(BaseModel):
    """A single closed (or end-of-window) trade in a backtest run.

    Mirrors the trade dict shape in src/backtest/engine.py portfolio close
    logic."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    entry_date: datetime
    entry_price: float
    exit_date: datetime
    exit_price: float
    qty: float
    pnl: float
    pnl_pct: float
    hold_days: int
    composite_score: float
    sub_scores: dict[str, float] = Field(default_factory=dict)
    exit_reason: ExitReason
    mfe: float = 0
    """Max favorable excursion (peak unrealized gain during the hold)."""
    mae: float = 0
    """Max adverse excursion (worst unrealized loss during the hold)."""
    r_multiple: float = 0
    """Realized P&L divided by initial risk (entry - stop)."""


class EquityPoint(BaseModel):
    """One daily mark on the equity curve."""

    model_config = ConfigDict(frozen=True)

    date: datetime
    equity: float
    cash: float
    open_positions: int


class RegimeSplit(BaseModel):
    """Performance bucket by regime (e.g. 'SPY > 200-SMA', 'VIX > 25')."""

    model_config = ConfigDict(frozen=True)

    regime: str
    n_trades: int
    win_rate: float
    avg_return_pct: float
    total_pnl: float


class BacktestResult(BaseModel):
    """Full result tree from a backtest run. Replaces the nested dict that
    src/backtest/engine.py:run_backtest returns today.

    Stored as a JSONB column in Postgres `backtest_runs` table (Stream A).
    The actual JSON structure preserved by Phase 0 stays close to the
    current `data/backtest_results.json` shape so the parity test compares
    cleanly.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    strategy: str
    window_start: datetime
    window_end: datetime
    oos_split_date: Optional[datetime] = None
    trades: tuple[BacktestTrade, ...] = ()
    equity_curve: tuple[EquityPoint, ...] = ()
    regime_splits: tuple[RegimeSplit, ...] = ()
    exit_reason_counts: dict[str, int] = Field(default_factory=dict)
    monthly_returns_pct: dict[str, dict[str, float]] = Field(default_factory=dict)
    """year -> {month_name -> return_pct}."""

    # --- summary metrics ---
    full: dict = Field(default_factory=dict)
    in_sample: dict = Field(default_factory=dict)
    out_of_sample: dict = Field(default_factory=dict)
    """Per-bucket summary dicts: total_return_pct, cagr_pct, sharpe, sortino,
    calmar, max_drawdown_pct, expectancy_pct, win_rate, alpha_vs_spy_pct.
    Kept as dict for JSON round-trip simplicity; typed view is on the
    roadmap for Phase 1."""

    bootstrap: dict = Field(default_factory=dict)
    monte_carlo: dict = Field(default_factory=dict)
    cost_sensitivity: list[dict] = Field(default_factory=list)
    verdict_oos: str = ""
    warnings: tuple[str, ...] = ()
