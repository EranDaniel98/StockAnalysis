"""Sector-cap selector tests.

The factor pipeline's naive ``head(top_n)`` selector produced the
2026-05-17 picks with 46% Financial Services concentration — a real
single-regime risk. ``_select_with_sector_cap`` walks the ranked
composite and bounds each sector at ``ceil(top_n * pct / 100)``,
preserving rank order within sectors and recording every eviction.
"""

from __future__ import annotations

import pandas as pd

from src.factors.pipeline import _select_with_sector_cap


def _composite(rows: list[tuple[str, int]]) -> pd.DataFrame:
    """tuples of (ticker, rank). raw/z_score filled deterministically."""
    return pd.DataFrame([
        {
            "ticker": t,
            "raw": -r,
            "rank": r,
            "z_score": -r * 0.1,
            "mean_normalized_rank": r * 0.01,
        }
        for t, r in rows
    ])


def test_sector_cap_evicts_excess_names_from_same_sector() -> None:
    # 12 names, 8 in "Financial Services". With top_n=10 and 30% cap
    # only 3 Financial Services names fit (ceil(10*0.3) = 3).
    rows = [(f"F{i}", i) for i in range(1, 9)]  # F1..F8 in Financials
    rows += [("X1", 9), ("Y1", 10), ("Z1", 11), ("W1", 12)]
    composite = _composite(rows)
    sectors = {f"F{i}": "Financial Services" for i in range(1, 9)}
    sectors.update({"X1": "Energy", "Y1": "Healthcare",
                    "Z1": "Tech", "W1": "Utilities"})

    selected, skipped = _select_with_sector_cap(
        composite, sectors, top_n=10, max_sector_pct=30.0,
    )
    selected_tickers = selected["ticker"].tolist()
    assert selected_tickers[:3] == ["F1", "F2", "F3"], (
        "highest-ranked Financials must be kept"
    )
    fin_count = sum(1 for t in selected_tickers if t.startswith("F"))
    assert fin_count == 3, "Financial Services capped at 3 of 10"
    skipped_tickers = [s["ticker"] for s in skipped]
    assert skipped_tickers == ["F4", "F5", "F6", "F7", "F8"], (
        "rank 4-8 Financials evicted in rank order"
    )
    assert all(s["sector"] == "Financial Services" for s in skipped)


def test_sector_cap_under_fills_when_universe_too_concentrated() -> None:
    # 8 names, 6 in one sector. With top_n=8 and 30% cap only 3 fit.
    # Only 2 names from other sectors exist → we under-fill at 5 picks.
    rows = [(f"F{i}", i) for i in range(1, 7)]
    rows += [("X1", 7), ("Y1", 8)]
    composite = _composite(rows)
    sectors = {f"F{i}": "Financial Services" for i in range(1, 7)}
    sectors.update({"X1": "Energy", "Y1": "Healthcare"})

    selected, skipped = _select_with_sector_cap(
        composite, sectors, top_n=8, max_sector_pct=30.0,
    )
    assert len(selected) == 5, (
        "expected under-fill (3 Financials + 2 non-financials)"
    )
    assert set(selected["ticker"]) == {"F1", "F2", "F3", "X1", "Y1"}
    skipped_tickers = {s["ticker"] for s in skipped}
    assert skipped_tickers == {"F4", "F5", "F6"}


def test_sector_cap_missing_sector_bucketed_as_unknown() -> None:
    composite = _composite([("A", 1), ("B", 2), ("C", 3), ("D", 4)])
    sectors = {"A": "Energy", "B": None}  # C, D missing entirely
    selected, skipped = _select_with_sector_cap(
        composite, sectors, top_n=4, max_sector_pct=50.0,
    )
    # 50% cap on 4 = 2 names per sector.
    # Energy (A): 1; Unknown (B, C, D): 3 → cap at 2 → 1 skip.
    assert len(selected) == 3
    assert skipped[0]["sector"] == "Unknown"


def test_sector_cap_preserves_rank_ordering_within_selected() -> None:
    composite = _composite([("A", 1), ("B", 2), ("C", 3), ("D", 4)])
    sectors = {"A": "Tech", "B": "Energy", "C": "Tech", "D": "Energy"}
    selected, _ = _select_with_sector_cap(
        composite, sectors, top_n=4, max_sector_pct=50.0,
    )
    # 50% cap on 4 = 2 per sector — none evicted, all 4 fit.
    assert selected["ticker"].tolist() == ["A", "B", "C", "D"]


def test_sector_cap_attaches_sector_column() -> None:
    composite = _composite([("A", 1), ("B", 2)])
    sectors = {"A": "Energy", "B": "Healthcare"}
    selected, _ = _select_with_sector_cap(
        composite, sectors, top_n=2, max_sector_pct=100.0,
    )
    assert "sector" in selected.columns
    assert selected.set_index("ticker")["sector"].to_dict() == {
        "A": "Energy", "B": "Healthcare",
    }


def test_sector_cap_empty_input() -> None:
    composite = _composite([])
    selected, skipped = _select_with_sector_cap(
        composite, {}, top_n=10, max_sector_pct=30.0,
    )
    assert selected.empty
    assert skipped == []
    assert "sector" in selected.columns
