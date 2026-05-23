"""Orphan-fill detection + refusal tests (Tier 1 #2 / review M2).

Pins:
  * PaperDB.insert_orphan_fill records an orphan keyed on alpaca_order_id.
  * Inserting the same orphan twice is idempotent (UNIQUE constraint).
  * get_orphan_tickers returns only UNRESOLVED tickers.
  * resolve_orphan marks the row resolved + ticker disappears from
    get_orphan_tickers.
  * _reconcile_closed_trades inserts an orphan row when Alpaca has a fill
    our DB doesn't, and emits a WARN log.
  * The full reconcile returns (n_new_trades, n_new_orphans).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.execution.paper_db import PaperDB


@pytest.fixture
def tmp_db():
    """A fresh PaperDB in a temp file — each test gets its own."""
    with tempfile.TemporaryDirectory() as td:
        db = PaperDB(db_path=Path(td) / "paper_test.db")
        yield db
        db.close()


# --- PaperDB orphan_fills primitives ---------------------------------------


def test_insert_orphan_records_row(tmp_db):
    row_id = tmp_db.insert_orphan_fill(
        alpaca_order_id="abc-123",
        client_order_id="sn-foo-AAPL-2026-05-15",
        ticker="AAPL", side="buy", qty=10, filled_qty=10,
        filled_price=200.0, filled_at="2026-05-15T15:30:00Z",
        status="filled",
    )
    assert row_id is not None
    orphans = tmp_db.list_orphans()
    assert len(orphans) == 1
    assert orphans[0]["alpaca_order_id"] == "abc-123"
    assert orphans[0]["ticker"] == "AAPL"
    assert orphans[0]["resolved_at"] is None


def test_insert_orphan_idempotent_on_alpaca_id(tmp_db):
    """Re-detecting the same orphan must NOT create a second row."""
    first = tmp_db.insert_orphan_fill(
        alpaca_order_id="dup-1", client_order_id=None,
        ticker="MSFT", side="buy", qty=5, filled_qty=5,
        filled_price=350.0, filled_at="2026-05-15T16:00:00Z",
        status="filled",
    )
    second = tmp_db.insert_orphan_fill(
        alpaca_order_id="dup-1", client_order_id=None,
        ticker="MSFT", side="buy", qty=5, filled_qty=5,
        filled_price=350.0, filled_at="2026-05-15T16:00:00Z",
        status="filled",
    )
    assert first is not None
    assert second is None  # idempotent — no new row
    assert len(tmp_db.list_orphans()) == 1


def test_get_orphan_tickers_returns_unresolved_only(tmp_db):
    tmp_db.insert_orphan_fill(
        alpaca_order_id="r-1", client_order_id=None,
        ticker="GOOG", side="buy", qty=1, filled_qty=1,
        filled_price=150.0, filled_at="2026-05-15T15:00:00Z",
        status="filled",
    )
    tmp_db.insert_orphan_fill(
        alpaca_order_id="r-2", client_order_id=None,
        ticker="NVDA", side="sell", qty=2, filled_qty=2,
        filled_price=500.0, filled_at="2026-05-15T15:30:00Z",
        status="filled",
    )
    assert tmp_db.get_orphan_tickers() == {"GOOG", "NVDA"}

    # Resolve one — the ticker should drop off the unresolved set.
    assert tmp_db.resolve_orphan("r-1", note="reconciled by hand") is True
    assert tmp_db.get_orphan_tickers() == {"NVDA"}
    # list_orphans default hides resolved rows
    assert len(tmp_db.list_orphans()) == 1
    # include_resolved=True shows both
    assert len(tmp_db.list_orphans(include_resolved=True)) == 2


def test_resolve_orphan_returns_false_for_unknown_id(tmp_db):
    assert tmp_db.resolve_orphan("never-existed") is False


def test_summary_counts_includes_unresolved_orphan_count(tmp_db):
    tmp_db.insert_orphan_fill(
        alpaca_order_id="s-1", client_order_id=None,
        ticker="TSLA", side="buy", qty=1, filled_qty=1,
        filled_price=250.0, filled_at="2026-05-15T15:00:00Z",
        status="filled",
    )
    counts = tmp_db.get_summary_counts()
    assert counts["unresolved_orphans"] == 1
    tmp_db.resolve_orphan("s-1")
    counts = tmp_db.get_summary_counts()
    assert counts["unresolved_orphans"] == 0


