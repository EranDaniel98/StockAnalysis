"""ValidationStore tests.

Pins:
  * First snapshot anchors the phase-start equity; cum_pnl_pct = 0.
  * Second snapshot's day_pnl_pct is relative to the first, cum_pnl_pct
    is relative to the phase anchor.
  * Re-inserting on the same (strategy, snapshot_date) UPSERTs (no
    duplicate rows).
  * Snapshot list returns chronological order regardless of insert order.
  * Multiple strategies are independent (per-strategy starting anchors).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.validation.store import DailySnapshot, ValidationStore


@pytest.fixture
def tmp_store():
    with tempfile.TemporaryDirectory() as td:
        store = ValidationStore(db_path=Path(td) / "validation_test.db")
        yield store
        store.close()


def _snap(date: str, equity: float, **kwargs) -> DailySnapshot:
    return DailySnapshot(
        strategy=kwargs.pop("strategy", "minimal_baseline"),
        snapshot_date=date,
        account_equity=equity,
        **kwargs,
    )


# --- Basic insert + lookup --------------------------------------------------


def test_first_snapshot_has_zero_cum_pnl(tmp_store):
    """The first snapshot is the phase anchor — cum_pnl_pct must be 0.0
    not None, since the cum-vs-anchor calculation by definition zero
    on day one."""
    tmp_store.upsert_snapshot(_snap("2026-05-16", 100_000.0))
    row = tmp_store.get_snapshot("minimal_baseline", "2026-05-16")
    assert row is not None
    assert row["cum_pnl_pct"] == 0.0
    assert row["day_pnl_pct"] == 0.0
    assert row["account_equity"] == 100_000.0


def test_second_snapshot_computes_day_and_cum_pnl(tmp_store):
    tmp_store.upsert_snapshot(_snap("2026-05-16", 100_000.0))
    tmp_store.upsert_snapshot(_snap("2026-05-17", 101_500.0))
    row = tmp_store.get_snapshot("minimal_baseline", "2026-05-17")
    # 101500 vs 100000 = +1.5% both day-over-day AND cumulative.
    assert row["day_pnl_pct"] == pytest.approx(1.5, abs=1e-6)
    assert row["cum_pnl_pct"] == pytest.approx(1.5, abs=1e-6)


def test_third_snapshot_cum_anchored_to_first(tmp_store):
    """cum_pnl_pct is relative to the EARLIEST snapshot, not the
    previous one — phase-start anchor stays fixed."""
    tmp_store.upsert_snapshot(_snap("2026-05-16", 100_000.0))
    tmp_store.upsert_snapshot(_snap("2026-05-17", 105_000.0))  # +5%
    tmp_store.upsert_snapshot(_snap("2026-05-18", 102_000.0))  # -2.86% day, +2% cum

    row = tmp_store.get_snapshot("minimal_baseline", "2026-05-18")
    assert row["day_pnl_pct"] == pytest.approx(
        (102_000.0 - 105_000.0) / 105_000.0 * 100.0, abs=1e-3,
    )
    assert row["cum_pnl_pct"] == pytest.approx(2.0, abs=1e-3)


# --- Upsert idempotency -----------------------------------------------------


def test_same_day_insert_updates_in_place(tmp_store):
    """Running validation_daily twice on the same calendar day must
    UPDATE (not insert a duplicate) — re-runs are expected."""
    tmp_store.upsert_snapshot(_snap("2026-05-16", 100_000.0, n_positions=3))
    tmp_store.upsert_snapshot(_snap("2026-05-16", 100_500.0, n_positions=4))

    rows = tmp_store.list_snapshots("minimal_baseline")
    assert len(rows) == 1
    assert rows[0]["account_equity"] == 100_500.0
    assert rows[0]["n_positions"] == 4


def test_upsert_returns_existing_id(tmp_store):
    """The returned id should be stable across upserts on the same key."""
    id1 = tmp_store.upsert_snapshot(_snap("2026-05-16", 100_000.0))
    id2 = tmp_store.upsert_snapshot(_snap("2026-05-16", 100_500.0))
    assert id1 == id2


# --- list_snapshots ordering -----------------------------------------------


def test_list_snapshots_chronological_regardless_of_insert_order(tmp_store):
    """Insert out of order, expect ascending dates back."""
    tmp_store.upsert_snapshot(_snap("2026-05-18", 102_000.0))
    tmp_store.upsert_snapshot(_snap("2026-05-16", 100_000.0))
    tmp_store.upsert_snapshot(_snap("2026-05-17", 101_500.0))
    rows = tmp_store.list_snapshots("minimal_baseline")
    assert [r["snapshot_date"] for r in rows] == [
        "2026-05-16", "2026-05-17", "2026-05-18",
    ]


# --- Multi-strategy isolation ----------------------------------------------


def test_strategies_are_independent(tmp_store):
    """minimal_baseline and swing_trading should each have their own
    starting anchor — cumulative P&L on one must not bleed into the
    other's calculation."""
    tmp_store.upsert_snapshot(_snap("2026-05-16", 100_000.0,
                                     strategy="minimal_baseline"))
    tmp_store.upsert_snapshot(_snap("2026-05-16", 100_000.0,
                                     strategy="swing_trading"))
    tmp_store.upsert_snapshot(_snap("2026-05-17", 105_000.0,
                                     strategy="minimal_baseline"))
    tmp_store.upsert_snapshot(_snap("2026-05-17", 99_000.0,
                                     strategy="swing_trading"))

    mb = tmp_store.get_snapshot("minimal_baseline", "2026-05-17")
    sw = tmp_store.get_snapshot("swing_trading", "2026-05-17")
    assert mb["cum_pnl_pct"] == pytest.approx(5.0, abs=1e-3)
    assert sw["cum_pnl_pct"] == pytest.approx(-1.0, abs=1e-3)
    assert sorted(tmp_store.list_strategies()) == [
        "minimal_baseline", "swing_trading",
    ]


# --- Open-ticker round trip -------------------------------------------------


def test_open_tickers_round_trip_as_json(tmp_store):
    """Tickers persist as JSON; sorted on insert so the report can rely
    on a deterministic ordering."""
    tmp_store.upsert_snapshot(_snap(
        "2026-05-16", 100_000.0,
        open_tickers=["NVDA", "AAPL", "MSFT"],
    ))
    import json
    row = tmp_store.get_snapshot("minimal_baseline", "2026-05-16")
    assert json.loads(row["open_tickers_json"]) == ["AAPL", "MSFT", "NVDA"]
