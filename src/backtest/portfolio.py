"""
Simulated portfolio for backtesting.
Tracks cash, positions, applies ATR-based stops + targets + max-hold timeout,
records every closed trade with its score bucket for calibration.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def score_bucket(score: float) -> str:
    """Classify a composite score into a calibration bucket."""
    if score < 50:
        return "<50"
    if score < 60:
        return "50-59"
    if score < 70:
        return "60-69"
    if score < 80:
        return "70-79"
    return "80+"


@dataclass
class Position:
    ticker: str
    shares: int
    entry_price: float
    entry_date: pd.Timestamp
    stop_price: float
    target_price: float
    max_exit_date: pd.Timestamp
    score: float
    sector: str = "Unknown"


@dataclass
class ClosedTrade:
    ticker: str
    shares: int
    entry_price: float
    exit_price: float
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    hold_days: int
    pnl: float
    pnl_pct: float
    exit_reason: str
    score: float
    score_bucket: str
    sector: str

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "shares": self.shares,
            "entry_price": round(self.entry_price, 2),
            "exit_price": round(self.exit_price, 2),
            "entry_date": self.entry_date.strftime("%Y-%m-%d"),
            "exit_date": self.exit_date.strftime("%Y-%m-%d"),
            "hold_days": self.hold_days,
            "pnl": round(self.pnl, 2),
            "pnl_pct": round(self.pnl_pct, 2),
            "exit_reason": self.exit_reason,
            "score": round(self.score, 2),
            "score_bucket": self.score_bucket,
            "sector": self.sector,
        }


@dataclass
class SimPortfolio:
    starting_cash: float
    max_position_pct: float = 0.10
    max_open_positions: int = 20
    compound: bool = False
    cash: float = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict)
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    skipped_for_cash: int = 0

    def __post_init__(self):
        self.cash = self.starting_cash

    def position_budget(self) -> float:
        """
        Dollar amount allocated per new position.
        Default (compound=False): fixed at starting_cash * max_position_pct so
        comparisons across runs aren't muddied by path-dependent sizing.
        compound=True: uses cash + book value of open positions, growing the
        budget as winners close into cash.
        """
        if not self.compound:
            return self.starting_cash * self.max_position_pct
        book_value = self.cash + sum(p.shares * p.entry_price for p in self.positions.values())
        return book_value * self.max_position_pct

    def can_open(self, ticker: str) -> bool:
        if ticker in self.positions:
            return False
        if len(self.positions) >= self.max_open_positions:
            return False
        if self.cash < self.position_budget():
            return False
        return True

    def open_position(
        self,
        ticker: str,
        entry_price: float,
        entry_date: pd.Timestamp,
        stop_price: float,
        target_price: float,
        max_exit_date: pd.Timestamp,
        score: float,
        sector: str = "Unknown",
    ) -> Optional[Position]:
        """Open a new long position. Returns the Position or None if rejected."""
        if not self.can_open(ticker):
            self.skipped_for_cash += 1
            return None
        if entry_price <= 0:
            return None
        budget = self.position_budget()
        shares = int(budget // entry_price)
        if shares <= 0:
            return None
        cost = shares * entry_price
        if cost > self.cash:
            return None
        self.cash -= cost
        pos = Position(
            ticker=ticker,
            shares=shares,
            entry_price=entry_price,
            entry_date=entry_date,
            stop_price=stop_price,
            target_price=target_price,
            max_exit_date=max_exit_date,
            score=score,
            sector=sector,
        )
        self.positions[ticker] = pos
        return pos

    def evaluate_day(self, ticker: str, day: pd.Timestamp, day_bar: pd.Series) -> Optional[ClosedTrade]:
        """
        Check a single day's OHLC for stop/target/timeout exits.

        Realistic fill model:
          - Stop hit on a gap-down (Open <= stop): fill at Open, not at stop_price.
            A stop order becomes a market order on trigger; on a gap-down open the
            first available trade IS the open, so fills happen worse than the stop.
          - Target hit on a gap-up (Open >= target): fill at Open, not at target.
            A sell-limit fills at limit OR BETTER, so gap-ups fill at the open.
          - Otherwise stop/target trigger intraday — fill at the trigger price.
          - If both stop and target are touched in the same bar, assume stop fired
            first (conservative, since we lack intraday ordering).
        """
        if ticker not in self.positions:
            return None
        pos = self.positions[ticker]
        open_ = float(day_bar["Open"])
        high = float(day_bar["High"])
        low = float(day_bar["Low"])
        close = float(day_bar["Close"])

        exit_price: Optional[float] = None
        exit_reason: Optional[str] = None

        if low <= pos.stop_price:
            exit_price = open_ if open_ <= pos.stop_price else pos.stop_price
            exit_reason = "stop_hit"
        elif high >= pos.target_price:
            exit_price = open_ if open_ >= pos.target_price else pos.target_price
            exit_reason = "target_hit"
        elif day >= pos.max_exit_date:
            exit_price = close
            exit_reason = "max_hold"

        if exit_price is None:
            return None

        return self._close(ticker, day, exit_price, exit_reason)

    def force_close_all(self, last_day: pd.Timestamp, price_lookup) -> None:
        """Close any still-open positions at last available close price for final stats."""
        for ticker in list(self.positions.keys()):
            close_price = price_lookup(ticker, last_day)
            if close_price is None:
                close_price = self.positions[ticker].entry_price
            self._close(ticker, last_day, close_price, "backtest_end")

    def _close(self, ticker: str, day: pd.Timestamp, exit_price: float, reason: str) -> ClosedTrade:
        pos = self.positions.pop(ticker)
        proceeds = pos.shares * exit_price
        self.cash += proceeds
        pnl = proceeds - (pos.shares * pos.entry_price)
        pnl_pct = (exit_price / pos.entry_price - 1) * 100 if pos.entry_price > 0 else 0
        hold_days = max(0, (day - pos.entry_date).days)
        trade = ClosedTrade(
            ticker=ticker,
            shares=pos.shares,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            entry_date=pos.entry_date,
            exit_date=day,
            hold_days=hold_days,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            score=pos.score,
            score_bucket=score_bucket(pos.score),
            sector=pos.sector,
        )
        self.closed_trades.append(trade)
        return trade

    def equity(self, mark_to_market: dict[str, float]) -> float:
        """Total equity = cash + sum(shares * latest_price)."""
        positions_value = 0.0
        for ticker, pos in self.positions.items():
            price = mark_to_market.get(ticker, pos.entry_price)
            positions_value += pos.shares * price
        return self.cash + positions_value
