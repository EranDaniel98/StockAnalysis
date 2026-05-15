"""Idempotency hardening tests (Tier 1 #1 / review M1).

Pins the bulletproof submit lifecycle:

  insert_pending_order   ───►  Alpaca call  ───►  finalize_pending_order
        (DB)                                              (DB)

On retry, the path consults DB + Alpaca to decide whether to skip,
recover, or resubmit:

  prior=submitted → skip (already done in a prior run)
  prior=pending_submit + Alpaca has it → finalize, no resubmit
  prior=pending_submit + Alpaca lacks it → discard pending, fresh submit
  no prior → fresh insert_pending + submit + finalize

Crash points covered: process killed between Alpaca-ack and finalize
(orphan-at-broker mode), Alpaca-rejection-after-pending (clean rollback),
duplicate-COID-error-at-Alpaca (recovery via lookup).
"""

from __future__ import annotations

import logging
import sqlite3
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.execution.alpaca import AlpacaDuplicateOrderError, make_client_order_id
from src.execution.paper_db import PaperDB
from src.execution.paper_trade_service import _process_recommendation


@pytest.fixture
def tmp_db():
    """Fresh PaperDB per test."""
    with tempfile.TemporaryDirectory() as td:
        db = PaperDB(db_path=Path(td) / "paper_test.db")
        yield db
        db.close()


def _make_rec(ticker: str = "AAPL", current_price: float = 150.0,
              stop_loss: float = 140.0, take_profit: float = 170.0,
              score: float = 70.0, action: str = "BUY") -> dict:
    return {
        "ticker": ticker,
        "composite_score": score,
        "action": action,
        "sector": "Technology",
        "sub_scores": {"technical": 70},
        "score_valid": True,
        "risk_management": {
            "current_price": current_price,
            "stop_loss": {"price": stop_loss},
            "take_profit": {"price": take_profit},
        },
    }


def _stub_alpaca_client(submit_side_effect=None, get_by_coid_returns=None,
                       get_by_coid_side_effect=None):
    client = MagicMock()
    if submit_side_effect is not None:
        # MagicMock semantics: an Exception INSTANCE on side_effect raises;
        # a callable on side_effect is invoked; anything else is iterable.
        # Be explicit so the helper handles all three correctly.
        if isinstance(submit_side_effect, BaseException) or \
           (isinstance(submit_side_effect, type) and issubclass(submit_side_effect, BaseException)):
            client.submit_bracket_order.side_effect = submit_side_effect
        elif callable(submit_side_effect):
            client.submit_bracket_order.side_effect = submit_side_effect
        else:
            client.submit_bracket_order.return_value = submit_side_effect
    if get_by_coid_side_effect is not None:
        client.get_order_by_coid.side_effect = get_by_coid_side_effect
    else:
        client.get_order_by_coid.return_value = get_by_coid_returns
    return client


def _patch_earnings(monkeypatch, status: str = "not_scheduled"):
    """Bypass yfinance — pretend no earnings within blackout."""
    from src.execution.paper_trade_service import EarningsLookup
    import src.execution.paper_trade_service as svc

    monkeypatch.setattr(
        svc, "_check_next_earnings",
        lambda ticker: EarningsLookup(status=status),
    )


# --- Happy path: fresh submit -----------------------------------------------


def test_fresh_submit_writes_pending_then_finalizes(tmp_db, monkeypatch):
    """No prior row → insert_pending → submit → finalize. End state:
    one row, status='submitted', real alpaca_order_id."""
    _patch_earnings(monkeypatch)
    client = _stub_alpaca_client(submit_side_effect={
        "order_id": "alpaca-abc-123",
        "client_order_id": "sn-swing-AAPL-2026-05-15",
        "status": "submitted",
        "submitted_at": "2026-05-15T15:30:00Z",
        "qty": 6,
        "ticker": "AAPL",
        "take_profit": 170.0,
        "stop_loss": 140.0,
    })

    outcome = _process_recommendation(
        _make_rec(), "swing", client, tmp_db,
        open_tickers=set(), orphan_tickers=set(),
        max_per_order=1000, blackout_days=5, dry_run=False,
    )

    assert outcome["submitted"] is True
    assert outcome["order_id"] == "alpaca-abc-123"
    # DB shows finalized row, NOT pending.
    coid = make_client_order_id("swing", "AAPL")
    row = tmp_db.get_order_by_client_order_id(coid)
    assert row is not None
    assert row["status"] == "submitted"
    assert row["alpaca_order_id"] == "alpaca-abc-123"
    # Alpaca lookup was NOT called (no prior pending row to recover).
    client.get_order_by_coid.assert_not_called()


# --- Retry: prior submitted row → skip --------------------------------------


def test_retry_when_already_submitted_skips_alpaca_call(tmp_db, monkeypatch):
    _patch_earnings(monkeypatch)
    # Simulate a successful prior run by writing a finalized row.
    coid = make_client_order_id("swing", "AAPL")
    rec_id = tmp_db.insert_recommendation(
        ticker="AAPL", strategy="swing", composite_score=70.0, action="BUY",
        sub_scores={}, entry_price=150.0, stop_loss=140.0, take_profit=170.0,
        sector="Tech",
    )
    tmp_db.insert_pending_order(
        recommendation_id=rec_id, client_order_id=coid, ticker="AAPL",
        qty=6, take_profit=170.0, stop_loss=140.0,
    )
    tmp_db.finalize_pending_order(
        client_order_id=coid, alpaca_order_id="alpaca-prior-1",
        status="submitted",
    )

    client = _stub_alpaca_client()
    outcome = _process_recommendation(
        _make_rec(), "swing", client, tmp_db,
        open_tickers=set(), orphan_tickers=set(),
        max_per_order=1000, blackout_days=5, dry_run=False,
    )

    assert outcome["submitted"] is True
    assert outcome["order_id"] == "alpaca-prior-1"
    assert outcome["skip_reason"] == "already_submitted_prior_run"
    client.submit_bracket_order.assert_not_called()


# --- Recovery: pending row + Alpaca HAS the order ---------------------------


def test_recovery_finalizes_when_alpaca_has_the_order(tmp_db, monkeypatch):
    """The crash-between-ack-and-finalize case. Pending row exists,
    Alpaca confirms the order landed. Must finalize, NOT resubmit."""
    _patch_earnings(monkeypatch)
    coid = make_client_order_id("swing", "AAPL")
    rec_id = tmp_db.insert_recommendation(
        ticker="AAPL", strategy="swing", composite_score=70.0, action="BUY",
        sub_scores={}, entry_price=150.0, stop_loss=140.0, take_profit=170.0,
        sector="Tech",
    )
    tmp_db.insert_pending_order(
        recommendation_id=rec_id, client_order_id=coid, ticker="AAPL",
        qty=6, take_profit=170.0, stop_loss=140.0,
    )

    client = _stub_alpaca_client(get_by_coid_returns={
        "order_id": "alpaca-recovered-1",
        "client_order_id": coid,
        "status": "filled",
        "submitted_at": "2026-05-15T15:29:00Z",
        "ticker": "AAPL",
    })

    outcome = _process_recommendation(
        _make_rec(), "swing", client, tmp_db,
        open_tickers=set(), orphan_tickers=set(),
        max_per_order=1000, blackout_days=5, dry_run=False,
    )

    assert outcome["submitted"] is True
    assert outcome["order_id"] == "alpaca-recovered-1"
    assert outcome["skip_reason"] == "recovered_pending_via_alpaca_lookup"
    client.submit_bracket_order.assert_not_called()
    # DB now shows finalized row, not pending.
    row = tmp_db.get_order_by_client_order_id(coid)
    assert row["status"] == "filled"
    assert row["alpaca_order_id"] == "alpaca-recovered-1"


# --- Recovery: pending row + Alpaca DOES NOT have the order -----------------


def test_recovery_discards_and_resubmits_when_alpaca_lacks_order(
    tmp_db, monkeypatch
):
    """Crash-before-Alpaca-got-the-request case. Pending row exists,
    Alpaca returns None on COID lookup. Must discard pending and
    issue a fresh submit."""
    _patch_earnings(monkeypatch)
    coid = make_client_order_id("swing", "AAPL")
    rec_id = tmp_db.insert_recommendation(
        ticker="AAPL", strategy="swing", composite_score=70.0, action="BUY",
        sub_scores={}, entry_price=150.0, stop_loss=140.0, take_profit=170.0,
        sector="Tech",
    )
    tmp_db.insert_pending_order(
        recommendation_id=rec_id, client_order_id=coid, ticker="AAPL",
        qty=6, take_profit=170.0, stop_loss=140.0,
    )

    client = _stub_alpaca_client(
        get_by_coid_returns=None,  # Alpaca says "no such order"
        submit_side_effect={
            "order_id": "alpaca-fresh-1",
            "client_order_id": coid,
            "status": "submitted",
            "submitted_at": "2026-05-15T15:30:00Z",
            "qty": 6, "ticker": "AAPL",
            "take_profit": 170.0, "stop_loss": 140.0,
        },
    )

    outcome = _process_recommendation(
        _make_rec(), "swing", client, tmp_db,
        open_tickers=set(), orphan_tickers=set(),
        max_per_order=1000, blackout_days=5, dry_run=False,
    )

    assert outcome["submitted"] is True
    assert outcome["order_id"] == "alpaca-fresh-1"
    client.submit_bracket_order.assert_called_once()
    row = tmp_db.get_order_by_client_order_id(coid)
    assert row["status"] == "submitted"
    assert row["alpaca_order_id"] == "alpaca-fresh-1"


# --- Alpaca-duplicate-error on a fresh submit --------------------------------


def test_alpaca_duplicate_error_falls_back_to_recovery_lookup(
    tmp_db, monkeypatch
):
    """If Alpaca returns 'duplicate COID' on a fresh submit, the code
    queries Alpaca to fill in the real id and finalizes. No double-fill."""
    _patch_earnings(monkeypatch)
    client = _stub_alpaca_client(
        submit_side_effect=AlpacaDuplicateOrderError("duplicate"),
        get_by_coid_returns={
            "order_id": "alpaca-dup-resolved-1",
            "client_order_id": make_client_order_id("swing", "AAPL"),
            "status": "submitted",
            "submitted_at": "2026-05-15T15:30:00Z",
            "ticker": "AAPL",
        },
    )

    outcome = _process_recommendation(
        _make_rec(), "swing", client, tmp_db,
        open_tickers=set(), orphan_tickers=set(),
        max_per_order=1000, blackout_days=5, dry_run=False,
    )

    assert outcome["submitted"] is True
    assert outcome["order_id"] == "alpaca-dup-resolved-1"
    assert outcome["skip_reason"] == "already_submitted_today"
    row = tmp_db.get_order_by_client_order_id(make_client_order_id("swing", "AAPL"))
    assert row["status"] == "submitted"


# --- Safety gate refusal: pending row must be discarded ---------------------


def test_safety_gate_refusal_discards_pending(tmp_db, monkeypatch):
    """When the safety gate refuses (e.g. trading_enabled=False), the
    Alpaca call never happens. The pending row MUST be discarded so
    next run isn't stuck in a phantom-pending state."""
    from src.execution.safety_gates import TradingHaltedError

    _patch_earnings(monkeypatch)
    client = _stub_alpaca_client(
        submit_side_effect=TradingHaltedError("trading_enabled is False"),
    )

    outcome = _process_recommendation(
        _make_rec(), "swing", client, tmp_db,
        open_tickers=set(), orphan_tickers=set(),
        max_per_order=1000, blackout_days=5, dry_run=False,
    )

    assert outcome["submitted"] is False
    assert "safety_gate" in (outcome["skip_reason"] or "")
    # Pending row gone — next run can retry cleanly.
    coid = make_client_order_id("swing", "AAPL")
    assert tmp_db.get_order_by_client_order_id(coid) is None


# --- Unknown-error: keep pending for next-run recovery ----------------------


def test_unknown_submit_error_keeps_pending_for_recovery(tmp_db, monkeypatch):
    """An unknown exception during submit may mean Alpaca DID get the
    order (we just couldn't read the response). Don't discard pending —
    the next run's recovery will check Alpaca."""
    _patch_earnings(monkeypatch)
    client = _stub_alpaca_client(
        submit_side_effect=RuntimeError("network timeout"),
    )

    outcome = _process_recommendation(
        _make_rec(), "swing", client, tmp_db,
        open_tickers=set(), orphan_tickers=set(),
        max_per_order=1000, blackout_days=5, dry_run=False,
    )

    assert outcome["submitted"] is False
    coid = make_client_order_id("swing", "AAPL")
    row = tmp_db.get_order_by_client_order_id(coid)
    assert row is not None
    assert row["status"] == PaperDB._PENDING_STATUS


# --- PaperDB primitives -----------------------------------------------------


def test_insert_pending_then_finalize_roundtrip(tmp_db):
    rec_id = tmp_db.insert_recommendation(
        ticker="MSFT", strategy="swing", composite_score=68.0, action="BUY",
        sub_scores={}, entry_price=350.0, stop_loss=335.0, take_profit=380.0,
        sector="Tech",
    )
    coid = "sn-swing-MSFT-2026-05-15"

    tmp_db.insert_pending_order(
        recommendation_id=rec_id, client_order_id=coid, ticker="MSFT",
        qty=2, take_profit=380.0, stop_loss=335.0,
    )
    row = tmp_db.get_order_by_client_order_id(coid)
    assert row["status"] == "pending_submit"
    assert row["alpaca_order_id"] == f"PENDING:{coid}"

    ok = tmp_db.finalize_pending_order(
        client_order_id=coid, alpaca_order_id="alpaca-msft-1",
        status="submitted",
    )
    assert ok is True
    row = tmp_db.get_order_by_client_order_id(coid)
    assert row["status"] == "submitted"
    assert row["alpaca_order_id"] == "alpaca-msft-1"


def test_finalize_unknown_coid_returns_false(tmp_db):
    """Finalize on a non-existent pending row is a safe no-op."""
    ok = tmp_db.finalize_pending_order(
        client_order_id="nope", alpaca_order_id="x", status="submitted",
    )
    assert ok is False


def test_discard_pending_only_deletes_pending(tmp_db):
    """discard_pending_order must NOT delete a finalized row even if
    given the same COID."""
    rec_id = tmp_db.insert_recommendation(
        ticker="GOOG", strategy="swing", composite_score=65.0, action="BUY",
        sub_scores={}, entry_price=150.0, stop_loss=140.0, take_profit=170.0,
        sector="Tech",
    )
    coid = "sn-swing-GOOG-2026-05-15"
    tmp_db.insert_pending_order(
        recommendation_id=rec_id, client_order_id=coid, ticker="GOOG",
        qty=6, take_profit=170.0, stop_loss=140.0,
    )
    tmp_db.finalize_pending_order(
        client_order_id=coid, alpaca_order_id="alpaca-goog-1",
        status="submitted",
    )
    # Now try to discard — must NOT remove the finalized row.
    deleted = tmp_db.discard_pending_order(coid)
    assert deleted is False
    assert tmp_db.get_order_by_client_order_id(coid) is not None


def test_pending_insert_unique_on_coid(tmp_db):
    """Two concurrent paper_trade runs both reach insert_pending — the
    UNIQUE on client_order_id (partial index) blocks the second insert."""
    rec_id = tmp_db.insert_recommendation(
        ticker="NVDA", strategy="swing", composite_score=72.0, action="BUY",
        sub_scores={}, entry_price=500.0, stop_loss=475.0, take_profit=550.0,
        sector="Tech",
    )
    coid = "sn-swing-NVDA-2026-05-15"
    tmp_db.insert_pending_order(
        recommendation_id=rec_id, client_order_id=coid, ticker="NVDA",
        qty=2, take_profit=550.0, stop_loss=475.0,
    )
    with pytest.raises(sqlite3.IntegrityError):
        tmp_db.insert_pending_order(
            recommendation_id=rec_id, client_order_id=coid, ticker="NVDA",
            qty=2, take_profit=550.0, stop_loss=475.0,
        )
