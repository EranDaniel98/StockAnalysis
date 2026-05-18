"""AlpacaClient bracket-direction invariant tests.

Pin the "stop > TP for shorts, TP > stop for longs" guard so a future
change can't silently swap the prices without the test suite catching it.

We don't construct a real TradingClient (would require network + valid
keys). Instead we stub the SDK pieces enough to drive the validation
branch and assert the right errors raise BEFORE the network call.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.execution.alpaca import AlpacaClient, AlpacaClientError
from src.execution.safety_gates import (
    CircuitBreakerThresholds, TradingSafetyGate,
)


@pytest.fixture
def stubbed_client(monkeypatch):
    """Build an AlpacaClient with patched TradingClient + permissive gate."""
    monkeypatch.setenv("ALPACA_API_KEY", "test_key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test_secret")
    with patch("src.execution.alpaca.TradingClient") as MockTC:
        instance = MagicMock()
        # No-op account snapshot — gate won't fire breakers.
        instance.get_account.return_value = MagicMock(
            account_number="x", status="ACTIVE", equity="10000",
            cash="10000", buying_power="10000", portfolio_value="10000",
            long_market_value="0", pattern_day_trader=False,
        )
        instance.get_all_positions.return_value = []
        MockTC.return_value = instance
        gate = TradingSafetyGate(
            trading_enabled=True,
            thresholds=CircuitBreakerThresholds(),
        )
        client = AlpacaClient(safety_gate=gate)
    return client


def test_long_bracket_requires_tp_above_stop(stubbed_client) -> None:
    with pytest.raises(AlpacaClientError, match="Long bracket.*take_profit"):
        stubbed_client.submit_bracket_order(
            ticker="AAPL", qty=10,
            take_profit_price=90.0,
            stop_loss_price=95.0,
            side="buy",
        )


def test_short_bracket_requires_tp_below_stop(stubbed_client) -> None:
    with pytest.raises(AlpacaClientError, match="Short bracket.*take_profit"):
        stubbed_client.submit_bracket_order(
            ticker="AAPL", qty=10,
            take_profit_price=105.0,
            stop_loss_price=100.0,
            side="sell",
        )


def test_long_bracket_with_equal_prices_refused(stubbed_client) -> None:
    """Equality must also raise — not strictly greater."""
    with pytest.raises(AlpacaClientError):
        stubbed_client.submit_bracket_order(
            ticker="AAPL", qty=10,
            take_profit_price=100.0,
            stop_loss_price=100.0,
            side="buy",
        )


def test_bracket_qty_zero_refused(stubbed_client) -> None:
    with pytest.raises(AlpacaClientError, match="qty >= 1"):
        stubbed_client.submit_bracket_order(
            ticker="AAPL", qty=0,
            take_profit_price=110.0,
            stop_loss_price=90.0,
            side="buy",
        )
