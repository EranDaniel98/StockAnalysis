"""Insider cluster factor tests (pure ranking logic only).

The DB-coupled fetch_cluster_counts is exercised indirectly via the
integration backtest. Here we pin the ranking math.
"""

from __future__ import annotations

import pandas as pd

from src.factors.insider_cluster import cluster_factor


def test_cluster_factor_ranks_by_n_insiders() -> None:
    panel = pd.DataFrame([
        {"ticker": "AAA", "n_insiders": 5, "total_shares": 1000, "total_value_usd": 200000},
        {"ticker": "BBB", "n_insiders": 2, "total_shares": 500,  "total_value_usd": 50000},
        {"ticker": "CCC", "n_insiders": 3, "total_shares": 800,  "total_value_usd": 100000},
    ])
    out = cluster_factor(panel)
    assert out.iloc[0]["ticker"] == "AAA"
    assert out.iloc[-1]["ticker"] == "BBB"
    assert list(out["rank"]) == [1, 2, 3]


def test_cluster_factor_breaks_ties_by_value() -> None:
    panel = pd.DataFrame([
        {"ticker": "A", "n_insiders": 3, "total_shares": 1000, "total_value_usd":  10000},
        {"ticker": "B", "n_insiders": 3, "total_shares": 1000, "total_value_usd": 500000},
        {"ticker": "C", "n_insiders": 3, "total_shares": 1000, "total_value_usd":  50000},
    ])
    out = cluster_factor(panel)
    # B wins on highest value among the 3-insider ties.
    assert out.iloc[0]["ticker"] == "B"
    assert out.iloc[1]["ticker"] == "C"
    assert out.iloc[2]["ticker"] == "A"


def test_cluster_factor_handles_empty_panel() -> None:
    empty = pd.DataFrame(
        columns=["ticker", "n_insiders", "total_shares", "total_value_usd"]
    )
    out = cluster_factor(empty)
    assert out.empty
    assert list(out.columns) == ["ticker", "raw", "rank", "z_score"]


def test_cluster_factor_z_score_zero_when_all_equal() -> None:
    panel = pd.DataFrame([
        {"ticker": "A", "n_insiders": 4, "total_shares": 1, "total_value_usd": 1},
        {"ticker": "B", "n_insiders": 4, "total_shares": 1, "total_value_usd": 1},
    ])
    out = cluster_factor(panel)
    # std is 0 so z-scores collapse to 0.
    assert all(out["z_score"] == 0.0)
