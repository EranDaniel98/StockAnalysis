"""Composite rank-blend tests.

The combine function must:
- normalize ranks per-frame to [0, 1] before averaging
- enforce min_overlap (default = all frames)
- handle empty input frames gracefully
- handle frames with different ticker sets
"""

from __future__ import annotations

import pandas as pd

from src.factors.composite import combine


def _frame(rows: list[tuple[str, int]]) -> pd.DataFrame:
    """tuples of (ticker, rank); fills raw/z_score deterministically."""
    return pd.DataFrame([
        {"ticker": t, "raw": -r, "rank": r, "z_score": -r * 0.1}
        for t, r in rows
    ])


def test_combine_two_frames_same_universe() -> None:
    a = _frame([("AAPL", 1), ("MSFT", 2), ("NVDA", 3)])
    b = _frame([("NVDA", 1), ("MSFT", 2), ("AAPL", 3)])
    out = combine([a, b])
    # Each name appears in both — MSFT should win because it's rank
    # 2 in both, mean rank = 2 vs AAPL=2 vs NVDA=2.
    # Actually all three have mean normalized rank 0.5; ranks should
    # all tie at 1.
    assert set(out["ticker"]) == {"AAPL", "MSFT", "NVDA"}
    assert out["mean_normalized_rank"].nunique() == 1


def test_combine_strict_overlap_drops_singletons() -> None:
    a = _frame([("AAPL", 1), ("MSFT", 2), ("NVDA", 3)])
    b = _frame([("MSFT", 1), ("NVDA", 2)])  # AAPL missing from b
    out = combine([a, b])
    assert set(out["ticker"]) == {"MSFT", "NVDA"}
    # MSFT: ranks (2, 1) → normalized (1/2, 0) → mean 0.25
    # NVDA: ranks (3, 2) → normalized (1, 1) → mean 1.0
    msft_mnr = float(out.loc[out["ticker"] == "MSFT",
                             "mean_normalized_rank"].iloc[0])
    nvda_mnr = float(out.loc[out["ticker"] == "NVDA",
                             "mean_normalized_rank"].iloc[0])
    assert msft_mnr < nvda_mnr
    assert int(out.loc[out["ticker"] == "MSFT", "rank"].iloc[0]) == 1


def test_combine_permissive_overlap_keeps_singletons() -> None:
    a = _frame([("AAPL", 1), ("MSFT", 2), ("NVDA", 3)])
    b = _frame([("MSFT", 1), ("NVDA", 2)])
    out = combine([a, b], min_overlap=1)
    assert set(out["ticker"]) == {"AAPL", "MSFT", "NVDA"}


def test_combine_empty_input() -> None:
    out = combine([])
    assert out.empty
    out = combine([pd.DataFrame()])
    assert out.empty


def test_combine_three_factors_picks_consistent_winner() -> None:
    """Ticker top-ranked in all three factors should be the composite winner."""
    a = _frame([("WIN", 1), ("MID", 2), ("LOW", 3)])
    b = _frame([("WIN", 1), ("MID", 2), ("LOW", 3)])
    c = _frame([("WIN", 1), ("MID", 2), ("LOW", 3)])
    out = combine([a, b, c])
    assert out.iloc[0]["ticker"] == "WIN"
    assert out.iloc[-1]["ticker"] == "LOW"
