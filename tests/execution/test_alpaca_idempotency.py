"""Idempotency contract for Alpaca submits.

Covers Tier-1 audit finding E#1/E#25/T#21: a retry of the same
recommendation must not double-fill. The application layer enforces
this by passing a deterministic client_order_id derived from
(strategy, ticker, date); the database UNIQUE constraint is a backstop.

These tests do not hit Alpaca — they exercise the helper that builds
the id and the wrapper's reaction to a simulated duplicate response.
"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock

import pytest
from alpaca.common.exceptions import APIError

from src.execution.alpaca import (
    AlpacaClient,
    AlpacaDuplicateOrderError,
    make_client_order_id,
)


# --- make_client_order_id --------------------------------------------------


def test_client_order_id_is_deterministic_within_day():
    a = make_client_order_id("swing_trading", "AAPL", as_of=date(2026, 5, 15))
    b = make_client_order_id("swing_trading", "AAPL", as_of=date(2026, 5, 15))
    assert a == b == "sn-swing_trading-AAPL-2026-05-15"


def test_client_order_id_changes_across_days():
    a = make_client_order_id("swing_trading", "AAPL", as_of=date(2026, 5, 15))
    b = make_client_order_id("swing_trading", "AAPL", as_of=date(2026, 5, 16))
    assert a != b


def test_client_order_id_disambiguates_strategies():
    a = make_client_order_id("swing_trading", "AAPL", as_of=date(2026, 5, 15))
    b = make_client_order_id("mean_reversion", "AAPL", as_of=date(2026, 5, 15))
    assert a != b


def test_client_order_id_respects_alpaca_max_length():
    long_strategy = "x" * 200
    coid = make_client_order_id(long_strategy, "AAPL", as_of=date(2026, 5, 15))
    assert len(coid) <= 128
    # Date + ticker preserved (the parts that carry uniqueness signal).
    assert coid.endswith("-AAPL-2026-05-15")


# --- duplicate detection ---------------------------------------------------


def _make_client_with_apierror(payload: dict, status_code: int) -> AlpacaClient:
    """Build an AlpacaClient whose underlying TradingClient raises an APIError
    matching the shape Alpaca returns on duplicate client_order_id."""
    client = AlpacaClient.__new__(AlpacaClient)  # bypass env-var __init__
    inner = MagicMock()
    http_error = MagicMock()
    http_error.response.status_code = status_code
    inner.submit_order.side_effect = APIError(
        json.dumps(payload), http_error=http_error
    )
    client._client = inner
    return client


def test_bracket_duplicate_coid_raises_typed_error():
    client = _make_client_with_apierror(
        {"code": 40010001, "message": "client_order_id must be unique"},
        status_code=422,
    )
    with pytest.raises(AlpacaDuplicateOrderError):
        client.submit_bracket_order(
            ticker="AAPL",
            qty=10,
            take_profit_price=200.0,
            stop_loss_price=180.0,
            client_order_id="sn-swing_trading-AAPL-2026-05-15",
        )


def test_market_duplicate_coid_raises_typed_error():
    client = _make_client_with_apierror(
        {"code": 40010001, "message": "client_order_id already exists"},
        status_code=422,
    )
    with pytest.raises(AlpacaDuplicateOrderError):
        client.submit_market_order(
            ticker="AAPL",
            qty=1,
            client_order_id="sn-bootstrap-AAPL-2026-05-15",
        )


def test_non_duplicate_apierror_propagates_unchanged():
    """Insufficient buying power must NOT be classified as duplicate."""
    client = _make_client_with_apierror(
        {"code": 40310000, "message": "insufficient buying power"},
        status_code=403,
    )
    with pytest.raises(APIError):
        client.submit_bracket_order(
            ticker="AAPL",
            qty=10,
            take_profit_price=200.0,
            stop_loss_price=180.0,
            client_order_id="sn-swing_trading-AAPL-2026-05-15",
        )
