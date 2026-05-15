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
    entry_price: float                # filled price (post-slippage)
    entry_date: pd.Timestamp
    stop_price: float
    target_price: float
    max_exit_date: pd.Timestamp
    score: float
    sector: str = "Unknown"
    cost_basis: float = 0.0           # total cash spent at entry incl commission
    intended_entry_price: float = 0.0  # Open price pre-slippage (for sensitivity)
    # MFE/MAE tracking (4.3) — running over the position's life
    running_high: float = 0.0         # max High since entry (exclusive of entry bar)
    running_low: float = float("inf")  # min Low since entry


@dataclass
class ClosedTrade:
    ticker: str
    shares: int
    entry_price: float                  # filled (post-slippage)
    exit_price: float                   # filled (post-slippage)
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    hold_days: int
    pnl: float                          # net (after all costs)
    pnl_pct: float
    exit_reason: str
    score: float
    score_bucket: str
    sector: str
    # For cost-sensitivity grid (Tier 3.5)
    intended_entry_price: float = 0.0   # Open, pre-slippage
    intended_exit_price: float = 0.0    # stop/target/close, pre-slippage
    gross_pnl: float = 0.0              # shares * (intended_exit - intended_entry)
    commissions_paid: float = 0.0       # round-trip commission
    # Excursion analytics (Tier 4.3)
    mfe_pct: float = 0.0                # max favorable excursion: max_high/entry - 1
    mae_pct: float = 0.0                # max adverse excursion: min_low/entry - 1
    r_multiple: float = 0.0             # pnl_pct / |stop distance pct|

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
            "gross_pnl": round(self.gross_pnl, 2),
            "exit_reason": self.exit_reason,
            "score": round(self.score, 2),
            "score_bucket": self.score_bucket,
            "sector": self.sector,
            "mfe_pct": round(self.mfe_pct, 2),
            "mae_pct": round(self.mae_pct, 2),
            "r_multiple": round(self.r_multiple, 2),
        }


@dataclass
class SimPortfolio:
    starting_cash: float
    max_position_pct: float = 0.10
    max_open_positions: int = 20
    compound: bool = False
    # Realism
    commission_per_trade: float = 0.0
    regulatory_bps_on_sale: float = 0.0   # SEC + FINRA on sales (~3bps)
    slippage_bps: float = 0.0             # each side
    # Volatility-targeted sizing (Tier 4.5)
    vol_target_risk_pct: float = 0.0      # 0 = use max_position_pct sizing; e.g. 0.01 = risk 1%/trade
    # Tier-2 audit #17 (Q#5 / Q#6): when True, BOTH position_budget AND
    # vol-target risk_dollars stay locked to starting_cash regardless of
    # the `compound` flag. Use this when reproducibility across sweep
    # runs matters more than apples-to-apples SPY comparison. Default
    # False so the bug fix (risk_dollars compounding with equity in
    # compound=True mode) is the natural behavior.
    fixed_size: bool = False
    cash: float = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict)
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    skipped_for_cash: int = 0
    total_commissions: float = 0.0
    total_slippage_cost: float = 0.0
    total_regulatory_fees: float = 0.0

    def __post_init__(self):
        self.cash = self.starting_cash

    def current_equity(self) -> float:
        """Book-value equity: cash + open positions at ENTRY price.

        Not mark-to-market on purpose — sizing on cost basis avoids
        letting a runaway winner inflate later position budgets. This
        is the sizing basis when compound=True.
        """
        return self.cash + sum(
            p.shares * p.entry_price for p in self.positions.values()
        )

    def _sizing_basis(self) -> float:
        """Account size used for position_budget AND vol-target risk_dollars.

        Tier-2 audit #17. The previous code computed each of these from
        a different base — position_budget honored `compound`, but
        risk_dollars in the vol-target branch always used starting_cash.
        So a compound=True backtest with vol_target_risk_pct=0.01 kept
        per-trade risk frozen as the account grew, which silently caps
        compounding for vol-targeted strategies.

        Single source of truth now:
          fixed_size=True   -> starting_cash (full reproducibility)
          compound=True     -> current_equity (compounds with the account)
          compound=False    -> starting_cash (legacy default)
        """
        if self.fixed_size or not self.compound:
            return self.starting_cash
        return self.current_equity()

    def position_budget(self) -> float:
        """Dollar amount allocated per new position.

        Goes through ``_sizing_basis()`` so position_budget and vol-target
        risk_dollars share the same account-size view. See _sizing_basis
        for the compound / fixed_size matrix.
        """
        return self._sizing_basis() * self.max_position_pct

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
        """
        Open a new long position. `entry_price` is the intended fill (Open).
        Slippage is applied so the actual fill is entry_price * (1 + slippage_bps/10000).
        Commission is deducted from cash on top of share cost.
        Returns the Position or None if rejected.
        """
        if not self.can_open(ticker):
            self.skipped_for_cash += 1
            return None
        if entry_price <= 0:
            return None
        slip = self.slippage_bps / 10000.0
        fill_price = entry_price * (1 + slip)
        budget = self.position_budget()
        # Position sizing: vol-target if enabled (each trade risks the same dollar
        # amount), else fixed-fractional (each trade gets the same dollar budget).
        if self.vol_target_risk_pct > 0:
            risk_per_share = fill_price - stop_price
            if risk_per_share <= 0:
                return None
            # Tier-2 audit #17: was `starting_cash * vol_target_risk_pct`
            # which froze risk dollars even in compound=True mode. Goes
            # through _sizing_basis() now so it compounds with the
            # account when the operator asked for compounding.
            risk_dollars = self._sizing_basis() * self.vol_target_risk_pct
            shares_by_risk = int(risk_dollars / risk_per_share)
            shares_by_budget = int(budget // fill_price)
            shares = min(shares_by_risk, shares_by_budget)  # cap so we never overspend
        else:
            shares = int(budget // fill_price)
        if shares <= 0:
            return None
        gross_cost = shares * fill_price
        cost_basis = gross_cost + self.commission_per_trade
        if cost_basis > self.cash:
            return None
        self.cash -= cost_basis
        self.total_commissions += self.commission_per_trade
        self.total_slippage_cost += (fill_price - entry_price) * shares
        pos = Position(
            ticker=ticker,
            shares=shares,
            entry_price=fill_price,
            entry_date=entry_date,
            stop_price=stop_price,
            target_price=target_price,
            max_exit_date=max_exit_date,
            score=score,
            sector=sector,
            cost_basis=cost_basis,
            intended_entry_price=entry_price,
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

        # Track running extremes for MFE/MAE
        if high > pos.running_high:
            pos.running_high = high
        if low < pos.running_low:
            pos.running_low = low

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
        """
        Close a position. `exit_price` is the intended fill (stop_price, target_price,
        or close). Slippage is applied so we actually receive exit_price*(1-slip);
        regulatory bps and commission are subtracted from proceeds.
        """
        pos = self.positions.pop(ticker)
        slip = self.slippage_bps / 10000.0
        fill_price = exit_price * (1 - slip)
        proceeds_gross = pos.shares * fill_price
        reg_fee = proceeds_gross * (self.regulatory_bps_on_sale / 10000.0)
        proceeds_net = proceeds_gross - reg_fee - self.commission_per_trade
        self.cash += proceeds_net
        self.total_commissions += self.commission_per_trade
        self.total_slippage_cost += (exit_price - fill_price) * pos.shares
        self.total_regulatory_fees += reg_fee
        pnl = proceeds_net - pos.cost_basis
        pnl_pct = (pnl / pos.cost_basis * 100) if pos.cost_basis > 0 else 0.0
        hold_days = max(0, (day - pos.entry_date).days)
        gross_pnl = pos.shares * (exit_price - pos.intended_entry_price) if pos.intended_entry_price > 0 else pnl

        # Excursion analytics (4.3)
        ref_price = pos.intended_entry_price if pos.intended_entry_price > 0 else pos.entry_price
        if pos.running_high > 0 and ref_price > 0:
            mfe_pct = (pos.running_high / ref_price - 1) * 100
        else:
            mfe_pct = 0.0
        if pos.running_low < float("inf") and ref_price > 0:
            mae_pct = (pos.running_low / ref_price - 1) * 100
        else:
            mae_pct = 0.0
        # R-multiple: pnl as multiple of intended risk per share
        risk_per_share = ref_price - pos.stop_price
        r_multiple = ((exit_price - ref_price) / risk_per_share) if risk_per_share > 0 else 0.0

        trade = ClosedTrade(
            ticker=ticker,
            shares=pos.shares,
            entry_price=pos.entry_price,
            exit_price=fill_price,
            entry_date=pos.entry_date,
            exit_date=day,
            hold_days=hold_days,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            score=pos.score,
            score_bucket=score_bucket(pos.score),
            sector=pos.sector,
            intended_entry_price=pos.intended_entry_price,
            intended_exit_price=exit_price,
            gross_pnl=gross_pnl,
            commissions_paid=2 * self.commission_per_trade,
            mfe_pct=mfe_pct,
            mae_pct=mae_pct,
            r_multiple=r_multiple,
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
