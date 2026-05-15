"""Vol-target sizing must compound with the account, not freeze at starting_cash.

Tier-2 audit #17 (Q#5 + Q#6). The previous code computed
``risk_dollars = starting_cash * vol_target_risk_pct`` regardless of
the ``compound`` flag, so a compound=True backtest with vol-targeted
sizing kept per-trade risk frozen — the strategy's compounding was
silently capped to the position_budget side only.

After the fix:
  * fixed_size=True  -> sizing basis is starting_cash (full reproducibility)
  * compound=True    -> sizing basis is current_equity (compounds)
  * compound=False   -> sizing basis is starting_cash (legacy)

Both position_budget AND vol-target risk_dollars go through the same
_sizing_basis() helper so they can't disagree again.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.backtest.portfolio import SimPortfolio


def _portfolio(**overrides) -> SimPortfolio:
    defaults = dict(starting_cash=10_000.0, max_position_pct=0.10)
    defaults.update(overrides)
    return SimPortfolio(**defaults)


def test_current_equity_starts_at_starting_cash():
    p = _portfolio()
    assert p.current_equity() == 10_000.0


def test_current_equity_reflects_open_positions_at_cost_basis():
    """Open positions add to equity at ENTRY price, not mark-to-market.
    That keeps the sizing basis stable across intraday price swings
    rather than re-sizing positions every time a winner rallies."""
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
    # cash dropped by 10 shares * 100, equity = cash + 10*100 = 10_000.
    assert p.current_equity() == 10_000.0


def test_vol_target_risk_dollars_compound_when_compound_true():
    """Keystone for audit #17. After a winning trade closes, account
    equity is up; vol-target risk_dollars on the next entry MUST scale
    with the new equity, not stay frozen at the original starting_cash."""
    p = _portfolio(
        compound=True,
        vol_target_risk_pct=0.01,
        max_position_pct=1.0,  # let one position absorb whole account
    )
    # Simulate a +20% win.
    p.cash = 12_000.0

    basis = p._sizing_basis()
    expected_risk_dollars = basis * 0.01

    assert basis == 12_000.0
    assert expected_risk_dollars == 120.0
    # NOT 100.0 (the broken behavior — starting_cash * 0.01 frozen).


def test_vol_target_risk_dollars_stay_frozen_when_compound_false():
    """compound=False is the legacy reproducibility-across-runs mode.
    Risk dollars stay locked to starting_cash even as equity grows."""
    p = _portfolio(
        compound=False,
        vol_target_risk_pct=0.01,
    )
    p.cash = 12_000.0  # simulate growth
    basis = p._sizing_basis()
    assert basis == 10_000.0  # starting_cash, frozen
    assert basis * 0.01 == 100.0


def test_fixed_size_overrides_compound():
    """The explicit reproducibility flag must dominate the compound
    flag — operators can deliberately freeze sizing for cross-sweep
    comparisons even while running compound mode for the equity curve."""
    p = _portfolio(
        compound=True,
        fixed_size=True,
        vol_target_risk_pct=0.01,
    )
    p.cash = 50_000.0
    assert p._sizing_basis() == 10_000.0  # starting_cash, not 50k current_equity


def test_position_budget_matches_sizing_basis_times_pct():
    """The bug fix's other half: position_budget and risk_dollars are
    derived from the SAME _sizing_basis, so they can't disagree about
    which account-size view to use."""
    p = _portfolio(
        compound=True,
        max_position_pct=0.10,
    )
    p.cash = 12_000.0
    assert p.position_budget() == pytest.approx(1_200.0)  # 12_000 * 0.10
    assert p._sizing_basis() == 12_000.0


def test_position_budget_legacy_compound_false_unchanged():
    """compound=False semantics preserved for back-compat: budget stays
    at starting_cash * max_position_pct regardless of equity."""
    p = _portfolio(compound=False, max_position_pct=0.10)
    p.cash = 50_000.0  # simulate growth
    assert p.position_budget() == 1_000.0  # 10k * 0.10, NOT 50k * 0.10
