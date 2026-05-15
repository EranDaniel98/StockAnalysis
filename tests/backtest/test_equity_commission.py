"""Reviewer I1 regression: current_equity must be conserved across an
open transition, including the commission.

Pre-fix, ``current_equity`` summed ``shares * entry_price`` while cash
dropped by ``shares * fill_price + commission`` — so equity silently
shrank by exactly the commission on every open. With $0-commission
Alpaca paper the bug was invisible; with $1-$5/trade and N open
positions per entry day, the sizing basis pre-emptively dropped by
$N-$5N every day, coupling fee model to position sizing.

The fix sums ``cost_basis`` (which is ``shares * fill_price +
commission``) so cash + Σ(cost_basis) = starting_cash, conserving
equity across the transition.
"""

from __future__ import annotations

import pandas as pd

from src.backtest.portfolio import SimPortfolio


def _portfolio(**overrides) -> SimPortfolio:
    defaults = dict(
        starting_cash=10_000.0,
        max_position_pct=0.50,
        commission_per_trade=5.0,
        slippage_bps=0,  # remove slippage to isolate the commission effect
    )
    defaults.update(overrides)
    return SimPortfolio(**defaults)


def test_equity_conserved_across_open_with_commission():
    """The reviewer's exact reproducer. 10k cash, commission=5, one open
    at $100 → post-open equity must be 10_000 (was 9_995 pre-fix)."""
    p = _portfolio()
    pos = p.open_position(
        ticker="AAPL",
        entry_price=100.0,
        entry_date=pd.Timestamp("2025-01-01"),
        stop_price=95.0,
        target_price=115.0,
        max_exit_date=pd.Timestamp("2025-01-31"),
        score=70.0,
    )
    assert pos is not None
    assert p.current_equity() == 10_000.0


def test_equity_conserved_across_multiple_opens_with_commission():
    """Five opens at $5 commission each: cash drops by $25 total, but
    equity stays at starting because each commission lives in its
    position's cost_basis."""
    p = _portfolio(max_position_pct=0.15, max_open_positions=5)
    for i, ticker in enumerate(["AAPL", "MSFT", "GOOGL", "META", "AMZN"]):
        p.open_position(
            ticker=ticker,
            entry_price=100.0,
            entry_date=pd.Timestamp(f"2025-01-{i+1:02d}"),
            stop_price=95.0,
            target_price=115.0,
            max_exit_date=pd.Timestamp("2025-02-28"),
            score=70.0,
        )
    assert len(p.positions) == 5
    # Equity conserved through all five opens.
    assert p.current_equity() == 10_000.0


def test_sizing_basis_uses_conserved_equity_when_compound():
    """Compound=True sizing basis must use the conserved equity so that
    fees don't pre-emptively shrink the per-trade budget."""
    p = _portfolio(compound=True)
    p.open_position(
        ticker="AAPL",
        entry_price=100.0,
        entry_date=pd.Timestamp("2025-01-01"),
        stop_price=95.0,
        target_price=115.0,
        max_exit_date=pd.Timestamp("2025-01-31"),
        score=70.0,
    )
    # Sizing basis = current_equity = 10_000 (NOT 9_995 pre-fix).
    assert p._sizing_basis() == 10_000.0


def test_equity_reflects_zero_commission_unchanged():
    """Sanity: with commission=0 the new formula gives the same answer
    as the old (cost_basis == shares * fill_price)."""
    p = _portfolio(commission_per_trade=0.0)
    p.open_position(
        ticker="AAPL",
        entry_price=100.0,
        entry_date=pd.Timestamp("2025-01-01"),
        stop_price=95.0,
        target_price=115.0,
        max_exit_date=pd.Timestamp("2025-01-31"),
        score=70.0,
    )
    assert p.current_equity() == 10_000.0
