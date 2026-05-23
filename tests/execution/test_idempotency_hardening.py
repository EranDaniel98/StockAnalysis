"""PaperDB primitives — pending → finalize lifecycle pins.

The full ``_process_recommendation`` orchestration tests that lived here
were tied to ``src.execution.paper_trade_service`` (the legacy 5-engine
paper trader) and were deleted with it 2026-05-23. The remaining tests
pin the PaperDB methods that ``scripts.paper_trade_factor_picks`` still
depends on for idempotent client_order_id submission.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.execution.paper_db import PaperDB


@pytest.fixture
def tmp_db():
    """Fresh PaperDB per test."""
    with tempfile.TemporaryDirectory() as td:
        db = PaperDB(db_path=Path(td) / "paper_test.db")
        yield db
        db.close()


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
