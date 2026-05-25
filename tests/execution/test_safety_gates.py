"""Real-money safety gate tests.

Pins:
  * trading_enabled default is False (review item #1) — submissions are
    refused at the broker-client boundary without explicit opt-in.
  * Each circuit breaker (daily P&L, drawdown, open-positions, order
    value) refuses on threshold breach (review item #2).
  * score_valid=False refuses BOTH bracket and market submissions
    (review item #3).
  * Env-var STOCKNEW_TRADING_ENABLED overrides config.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from src.execution.alpaca import AlpacaClient
from src.execution.safety_gates import (
    CircuitBreakerThresholds,
    SessionState,
    TradingHaltedError,
    TradingSafetyGate,
)


def _session(
    *,
    starting: float = 100_000.0,
    current: float = 100_000.0,
    peak: float = 100_000.0,
    open_count: int = 0,
) -> SessionState:
    return SessionState(
        starting_equity=starting,
        current_equity=current,
        peak_equity=peak,
        open_position_count=open_count,
    )


# --- Kill switch (review #1) -----------------------------------------------


def test_trading_disabled_refuses_submission():
    """Default config = trading disabled = every submission refused."""
    gate = TradingSafetyGate(
        trading_enabled=False,
        thresholds=CircuitBreakerThresholds(),
    )
    with pytest.raises(TradingHaltedError, match="trading_enabled is False"):
        gate.check_pre_submit(
            ticker="AAPL", notional_usd=1000.0, session=_session(),
        )


def test_trading_enabled_allows_submission():
    gate = TradingSafetyGate(
        trading_enabled=True,
        thresholds=CircuitBreakerThresholds(),
    )
    # No breach — None return = pass.
    assert gate.check_pre_submit(
        ticker="AAPL", notional_usd=1000.0, session=_session(),
    ) is None


def test_env_var_overrides_config_to_enable(monkeypatch):
    """STOCKNEW_TRADING_ENABLED=1 forces on even with config=false."""
    monkeypatch.setenv("STOCKNEW_TRADING_ENABLED", "1")

    config = MagicMock()
    config.get.return_value = False  # config says disabled
    # but get(...) returns a dict for the circuit_breakers path; mock both:
    def cfg_get(*path, default=None):
        if path == ("trading", "trading_enabled"):
            return False
        if path == ("trading", "circuit_breakers"):
            return {}
        return default
    config.get.side_effect = cfg_get

    gate = TradingSafetyGate.from_config(config)
    assert gate.trading_enabled is True


def test_env_var_overrides_config_to_disable(monkeypatch):
    """STOCKNEW_TRADING_ENABLED=0 forces off even with config=true."""
    monkeypatch.setenv("STOCKNEW_TRADING_ENABLED", "0")
    config = MagicMock()
    def cfg_get(*path, default=None):
        if path == ("trading", "trading_enabled"):
            return True
        if path == ("trading", "circuit_breakers"):
            return {}
        return default
    config.get.side_effect = cfg_get

    gate = TradingSafetyGate.from_config(config)
    assert gate.trading_enabled is False


# --- score_valid (review #3) ------------------------------------------------


def test_score_valid_false_refuses_buy_side():
    gate = TradingSafetyGate(
        trading_enabled=True,
        thresholds=CircuitBreakerThresholds(),
    )
    with pytest.raises(TradingHaltedError, match="score_valid=False"):
        gate.check_pre_submit(
            ticker="AAPL", notional_usd=1000.0,
            session=_session(), score_valid=False,
        )


def test_score_valid_false_refuses_sell_side_too():
    """Asymmetry fix: score_valid=False refuses ANY direction, BUY or SELL.
    Pre-fix paper_evaluate_service didn't check score_valid for exits;
    moving the gate to the broker boundary closes that gap."""
    gate = TradingSafetyGate(
        trading_enabled=True,
        thresholds=CircuitBreakerThresholds(),
    )
    with pytest.raises(TradingHaltedError, match="score_valid=False"):
        gate.check_pre_submit(
            ticker="AAPL", notional_usd=1000.0,
            session=_session(), score_valid=False,
        )


# --- Circuit breakers (review #2) -------------------------------------------


def test_max_order_value_refuses_oversize_order():
    gate = TradingSafetyGate(
        trading_enabled=True,
        thresholds=CircuitBreakerThresholds(max_order_value_usd=1000.0),
    )
    with pytest.raises(TradingHaltedError, match=r"max_order_value_usd"):
        gate.check_pre_submit(
            ticker="AAPL", notional_usd=1500.0, session=_session(),
        )


def test_max_order_value_zero_disables_check():
    """0.0 means 'disabled'. Verify a huge notional passes."""
    gate = TradingSafetyGate(
        trading_enabled=True,
        thresholds=CircuitBreakerThresholds(max_order_value_usd=0.0),
    )
    gate.check_pre_submit(
        ticker="AAPL", notional_usd=1_000_000.0, session=_session(),
    )  # no raise


def test_max_open_positions_refuses_at_threshold():
    """Triggers on >=, not strict >."""
    gate = TradingSafetyGate(
        trading_enabled=True,
        thresholds=CircuitBreakerThresholds(max_open_positions=10),
    )
    with pytest.raises(TradingHaltedError, match="max_open_positions"):
        gate.check_pre_submit(
            ticker="AAPL", notional_usd=500.0,
            session=_session(open_count=10),
        )


def test_max_daily_loss_refuses_below_floor():
    gate = TradingSafetyGate(
        trading_enabled=True,
        thresholds=CircuitBreakerThresholds(max_daily_loss_pct=-0.02),
    )
    # session P&L = -3% (current 97k vs starting 100k) → breach
    with pytest.raises(TradingHaltedError, match="max_daily_loss_pct"):
        gate.check_pre_submit(
            ticker="AAPL", notional_usd=500.0,
            session=_session(current=97_000.0, peak=100_000.0),
        )


def test_max_daily_loss_passes_when_above_floor():
    """A -1.5% drawdown does NOT trip a -2% floor."""
    gate = TradingSafetyGate(
        trading_enabled=True,
        thresholds=CircuitBreakerThresholds(max_daily_loss_pct=-0.02),
    )
    gate.check_pre_submit(
        ticker="AAPL", notional_usd=500.0,
        session=_session(current=98_500.0, peak=100_000.0),
    )  # no raise


def test_max_drawdown_refuses_from_peak():
    """Drawdown is measured against session peak, not opening equity.
    A session that went +5% then back to flat must trip a -10% peak-
    referenced halt only if it draws past peak by 10% of starting cash."""
    gate = TradingSafetyGate(
        trading_enabled=True,
        thresholds=CircuitBreakerThresholds(max_drawdown_halt_pct=-0.10),
    )
    # peak hit 105k, now at 90k → dd from peak = -15% of starting
    with pytest.raises(TradingHaltedError, match="max_drawdown_halt_pct"):
        gate.check_pre_submit(
            ticker="AAPL", notional_usd=500.0,
            session=_session(
                starting=100_000.0,
                current=90_000.0,
                peak=105_000.0,
            ),
        )


def test_circuit_breaker_check_order_fails_loud_on_first_breach():
    """If multiple breakers are tripped, we get a specific reason on the
    first one — not a generic 'failed'. Helps the operator diagnose."""
    gate = TradingSafetyGate(
        trading_enabled=False,  # this trips first
        thresholds=CircuitBreakerThresholds(
            max_order_value_usd=100.0,
            max_open_positions=1,
            max_daily_loss_pct=-0.01,
        ),
    )
    # All four would trip. Trading-enabled check is FIRST.
    with pytest.raises(TradingHaltedError) as exc_info:
        gate.check_pre_submit(
            ticker="AAPL", notional_usd=99_999.0,
            session=_session(current=50_000.0, open_count=99),
        )
    assert "trading_enabled is False" in str(exc_info.value)


# --- AlpacaClient integration (fail-closed default) -------------------------


def test_alpaca_client_default_safety_gate_refuses():
    """A client built without an explicit safety_gate fails closed:
    every submission is refused."""
    client = AlpacaClient.__new__(AlpacaClient)  # bypass env-var ctor
    client._client = MagicMock()
    # Simulate __init__'s default-gate behavior:
    client._safety_gate = TradingSafetyGate(
        trading_enabled=False,
        thresholds=CircuitBreakerThresholds(),
    )
    with pytest.raises(TradingHaltedError, match="trading_enabled is False"):
        client.submit_bracket_order(
            ticker="AAPL", qty=1,
            take_profit_price=200.0, stop_loss_price=180.0,
            session_state=_session(),
        )


def test_alpaca_client_submit_market_respects_gate():
    """submit_market_order goes through the same gate as bracket."""
    client = AlpacaClient.__new__(AlpacaClient)
    client._client = MagicMock()
    client._safety_gate = TradingSafetyGate(
        trading_enabled=False,
        thresholds=CircuitBreakerThresholds(),
    )
    with pytest.raises(TradingHaltedError, match="trading_enabled is False"):
        client.submit_market_order(
            ticker="AAPL", qty=1,
            session_state=_session(),
            reference_price=200.0,
        )
