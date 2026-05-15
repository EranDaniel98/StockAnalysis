"""Earnings-blackout contract for paper trading.

Covers Tier-1 audit finding E#7/X#25: a yfinance hang or shape change
must not silently bypass the earnings-blackout filter. Previously
`_days_to_next_earnings` returned None on any failure and the caller
treated None as "no earnings ahead", so a trade could ship 0-3 days
before an announcement on any transient error.

After the fix, the lookup returns a discriminated `EarningsLookup`:
  * status="scheduled"     -> trade if days_until > blackout_days
  * status="not_scheduled" -> trade
  * status="unknown"       -> REFUSE, skip_reason="earnings_unknown"
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from unittest.mock import patch, MagicMock

import pandas as pd

from src.execution import paper_trade_service
from src.execution.paper_trade_service import (
    EarningsLookup,
    _check_next_earnings,
    _fetch_next_earnings_date,
    _process_recommendation,
)


# --- _fetch_next_earnings_date (shape coverage) ----------------------------


def _ticker_with_calendar(cal_value):
    t = MagicMock()
    t.calendar = cal_value
    return t


def test_fetch_dict_shape_with_list():
    next_dt = date.today() + timedelta(days=7)
    with patch("yfinance.Ticker", return_value=_ticker_with_calendar(
        {"Earnings Date": [next_dt]}
    )):
        assert _fetch_next_earnings_date("AAPL") == next_dt


def test_fetch_dict_shape_with_scalar():
    next_dt = date.today() + timedelta(days=3)
    with patch("yfinance.Ticker", return_value=_ticker_with_calendar(
        {"Earnings Date": next_dt}
    )):
        assert _fetch_next_earnings_date("AAPL") == next_dt


def test_fetch_dataframe_shape():
    next_dt = date.today() + timedelta(days=12)
    df = pd.DataFrame({"AAPL": [pd.Timestamp(next_dt)]}, index=["Earnings Date"])
    with patch("yfinance.Ticker", return_value=_ticker_with_calendar(df)):
        # Pandas .iloc[0] on a single-column row returns the Timestamp directly.
        assert _fetch_next_earnings_date("AAPL") == next_dt


def test_fetch_returns_none_when_calendar_missing():
    with patch("yfinance.Ticker", return_value=_ticker_with_calendar(None)):
        assert _fetch_next_earnings_date("AAPL") is None


def test_fetch_raises_on_dataframe_shape_change():
    """If yfinance drops the 'Earnings Date' label, propagate the KeyError
    so the wrapper records 'unknown' instead of silently returning None."""
    df = pd.DataFrame({"AAPL": [1]}, index=["Something Else"])
    with patch("yfinance.Ticker", return_value=_ticker_with_calendar(df)):
        try:
            _fetch_next_earnings_date("AAPL")
        except KeyError:
            return
        raise AssertionError("expected KeyError on missing row label")


# --- _check_next_earnings (real-money branch coverage) ---------------------


def test_check_returns_scheduled_when_date_ahead():
    with patch.object(
        paper_trade_service, "_fetch_next_earnings_date",
        return_value=date.today() + timedelta(days=4),
    ):
        result = _check_next_earnings("AAPL")
    assert result == EarningsLookup(status="scheduled", days_until=4)


def test_check_returns_not_scheduled_when_no_date():
    with patch.object(
        paper_trade_service, "_fetch_next_earnings_date", return_value=None
    ):
        result = _check_next_earnings("AAPL")
    assert result == EarningsLookup(status="not_scheduled")


def test_check_returns_not_scheduled_when_date_in_past():
    """Stale yfinance row from a prior quarter must not poison the filter."""
    with patch.object(
        paper_trade_service, "_fetch_next_earnings_date",
        return_value=date.today() - timedelta(days=30),
    ):
        result = _check_next_earnings("AAPL")
    assert result == EarningsLookup(status="not_scheduled")


def test_check_returns_unknown_on_yfinance_exception():
    """Any exception from yfinance (network, KeyError, RuntimeError) must
    surface as 'unknown' so the caller refuses to trade."""
    with patch.object(
        paper_trade_service, "_fetch_next_earnings_date",
        side_effect=RuntimeError("yfinance broke"),
    ):
        result = _check_next_earnings("AAPL")
    assert result.status == "unknown"
    assert result.days_until is None


def test_check_returns_unknown_on_timeout(monkeypatch):
    """A hung yfinance call must time out within the configured budget
    rather than blocking the trade loop indefinitely. We hijack
    `_fetch_next_earnings_date` with a sleep longer than the budget and
    drop the budget to 0.1s so the test stays fast."""
    monkeypatch.setattr(paper_trade_service, "EARNINGS_LOOKUP_TIMEOUT_SECONDS", 0.1)

    def hung(_ticker):
        time.sleep(2.0)
        return None

    monkeypatch.setattr(paper_trade_service, "_fetch_next_earnings_date", hung)

    start = time.monotonic()
    result = _check_next_earnings("AAPL")
    elapsed = time.monotonic() - start

    assert result.status == "unknown"
    # Wall-clock should be near the budget, not near the sleep duration.
    assert elapsed < 1.0, f"timeout did not fire within budget; elapsed={elapsed:.2f}s"


# --- _process_recommendation (caller-level contract) ----------------------


def _stub_rec(ticker: str = "AAPL", score: float = 75.0) -> dict:
    return {
        "ticker": ticker,
        "composite_score": score,
        "action": "BUY",
        "sub_scores": {},
        "sector": "Tech",
        "risk_management": {
            "current_price": 100.0,
            "stop_loss": {"price": 95.0},
            "take_profit": {"price": 110.0},
        },
    }


def test_unknown_earnings_blocks_submission():
    """End-to-end safety: when the earnings lookup returns "unknown" the
    process step must set skip_reason and never call the broker."""
    client = MagicMock()
    db = MagicMock()
    with patch.object(
        paper_trade_service, "_check_next_earnings",
        return_value=EarningsLookup(status="unknown"),
    ):
        outcome = _process_recommendation(
            _stub_rec(), "swing_trading", client, db,
            open_tickers=set(), orphan_tickers=set(),
            max_per_order=1000,
            blackout_days=5,
            dry_run=False,
        )

    assert outcome["skip_reason"] == "earnings_unknown"
    assert outcome["submitted"] is False
    assert outcome["order_id"] is None
    client.submit_bracket_order.assert_not_called()


def test_scheduled_outside_blackout_window_submits():
    """Earnings 30d away with blackout=5 should NOT block."""
    client = MagicMock()
    client.submit_bracket_order.return_value = {
        "order_id": "abc123", "client_order_id": "x", "status": "new",
        "submitted_at": None, "qty": 10, "ticker": "AAPL",
        "take_profit": 110.0, "stop_loss": 95.0,
    }
    db = MagicMock()
    db.insert_recommendation.return_value = 1
    with patch.object(
        paper_trade_service, "_check_next_earnings",
        return_value=EarningsLookup(status="scheduled", days_until=30),
    ):
        outcome = _process_recommendation(
            _stub_rec(), "swing_trading", client, db,
            open_tickers=set(), orphan_tickers=set(),
            max_per_order=1000,
            blackout_days=5,
            dry_run=False,
        )

    assert outcome["skip_reason"] is None
    assert outcome["submitted"] is True
    client.submit_bracket_order.assert_called_once()


def test_scheduled_within_blackout_window_blocks():
    client = MagicMock()
    db = MagicMock()
    db.insert_recommendation.return_value = 1
    with patch.object(
        paper_trade_service, "_check_next_earnings",
        return_value=EarningsLookup(status="scheduled", days_until=3),
    ):
        outcome = _process_recommendation(
            _stub_rec(), "swing_trading", client, db,
            open_tickers=set(), orphan_tickers=set(),
            max_per_order=1000,
            blackout_days=5,
            dry_run=False,
        )

    assert outcome["skip_reason"] == "earnings_in_3d"
    assert outcome["submitted"] is False
    client.submit_bracket_order.assert_not_called()
