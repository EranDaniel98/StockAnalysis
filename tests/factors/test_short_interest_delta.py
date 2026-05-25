"""Short-interest delta factor — ranking-math tests.

The DB-coupled fetch is exercised once data coverage extends across
the backtest windows. Today's FINRA load covers ~1 year; insufficient
for a 3-window A/B. These tests pin the pure ranking logic.
"""

from __future__ import annotations

import pandas as pd

from src.factors.short_interest_delta import short_delta_factor


def test_short_delta_ranks_decrease_above_increase() -> None:
    panel = pd.DataFrame([
        {"ticker": "COVERING", "current_window_vol": 100,
         "prior_window_vol": 200, "delta_pct": -0.5},
        {"ticker": "STEADY",   "current_window_vol": 100,
         "prior_window_vol": 100, "delta_pct": 0.0},
        {"ticker": "PILING",   "current_window_vol": 200,
         "prior_window_vol": 100, "delta_pct": 1.0},
    ])
    out = short_delta_factor(panel)
    # COVERING has the lowest delta_pct (most short-cover) → rank 1.
    assert out.iloc[0]["ticker"] == "COVERING"
    assert out.iloc[-1]["ticker"] == "PILING"


def test_short_delta_handles_empty_panel() -> None:
    empty = pd.DataFrame(
        columns=["ticker", "current_window_vol", "prior_window_vol", "delta_pct"]
    )
    out = short_delta_factor(empty)
    assert out.empty
    assert list(out.columns) == ["ticker", "raw", "rank", "z_score"]


def test_short_delta_z_score_zero_when_all_equal() -> None:
    panel = pd.DataFrame([
        {"ticker": "A", "current_window_vol": 100,
         "prior_window_vol": 100, "delta_pct": 0.0},
        {"ticker": "B", "current_window_vol": 100,
         "prior_window_vol": 100, "delta_pct": 0.0},
    ])
    out = short_delta_factor(panel)
    assert all(out["z_score"] == 0.0)
