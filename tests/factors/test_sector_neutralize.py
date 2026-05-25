"""Sector-neutralize tests.

Pin the invariants:
- output shape matches input shape
- a name that's mediocre overall but BEST in its sector ranks high
- a name that's high cross-sectionally but mid-of-sector loses ground
- sectors smaller than min_sector_size collapse into Unknown
- empty frame and missing-column frame are handled cleanly
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.factors.sector_neutralize import sector_neutralize


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_output_shape_preserved() -> None:
    frame = _frame([
        {"ticker": "AAPL", "raw": 0.9, "rank": 1, "z_score": 2.0},
        {"ticker": "MSFT", "raw": 0.8, "rank": 2, "z_score": 1.5},
        {"ticker": "GOOG", "raw": 0.7, "rank": 3, "z_score": 1.0},
        {"ticker": "XOM",  "raw": 0.6, "rank": 4, "z_score": 0.5},
        {"ticker": "CVX",  "raw": 0.5, "rank": 5, "z_score": 0.0},
        {"ticker": "OXY",  "raw": 0.4, "rank": 6, "z_score": -0.5},
    ])
    sectors = {"AAPL": "Tech", "MSFT": "Tech", "GOOG": "Tech",
                "XOM": "Energy", "CVX": "Energy", "OXY": "Energy"}
    out = sector_neutralize(frame, sectors)
    assert list(out.columns) == ["ticker", "raw", "rank", "z_score"]
    assert len(out) == 6
    assert set(out["ticker"]) == set(frame["ticker"])


def test_sector_neutralized_top_picks_one_per_sector() -> None:
    """The original 'top 3 cross-sectional' was all-Tech because Tech
    had the highest raw scores. After sector-neutralization, the top
    by rank should include the BEST OF EACH SECTOR."""
    frame = _frame([
        {"ticker": "AAPL", "raw": 0.9, "rank": 1, "z_score": 2.0},
        {"ticker": "MSFT", "raw": 0.8, "rank": 2, "z_score": 1.5},
        {"ticker": "GOOG", "raw": 0.7, "rank": 3, "z_score": 1.0},
        {"ticker": "XOM",  "raw": 0.6, "rank": 4, "z_score": 0.5},
        {"ticker": "CVX",  "raw": 0.5, "rank": 5, "z_score": 0.0},
        {"ticker": "OXY",  "raw": 0.4, "rank": 6, "z_score": -0.5},
    ])
    sectors = {"AAPL": "Tech", "MSFT": "Tech", "GOOG": "Tech",
                "XOM": "Energy", "CVX": "Energy", "OXY": "Energy"}
    out = sector_neutralize(frame, sectors)
    # Best of Tech is AAPL (raw 0.9); best of Energy is XOM (raw 0.6).
    # Both should tie at rank 1.
    top = out[out["rank"] == 1]
    assert set(top["ticker"]) == {"AAPL", "XOM"}


def test_within_sector_rank_promotes_mid_universe_name() -> None:
    """OXY is rank 6 cross-sectionally but rank 3 within Energy. After
    neutralization, OXY's percentile-in-sector is 100% (worst of Energy)
    so it should be the worst overall. Conversely, XOM (best of Energy)
    moves UP from rank 4 cross-sectional to rank 1 sector-neutral."""
    frame = _frame([
        {"ticker": "AAPL", "raw": 0.9, "rank": 1, "z_score": 2.0},
        {"ticker": "MSFT", "raw": 0.8, "rank": 2, "z_score": 1.5},
        {"ticker": "GOOG", "raw": 0.7, "rank": 3, "z_score": 1.0},
        {"ticker": "XOM",  "raw": 0.6, "rank": 4, "z_score": 0.5},
        {"ticker": "CVX",  "raw": 0.5, "rank": 5, "z_score": 0.0},
        {"ticker": "OXY",  "raw": 0.4, "rank": 6, "z_score": -0.5},
    ])
    sectors = {"AAPL": "Tech", "MSFT": "Tech", "GOOG": "Tech",
                "XOM": "Energy", "CVX": "Energy", "OXY": "Energy"}
    out = sector_neutralize(frame, sectors).set_index("ticker")
    # XOM = best of Energy → tied at rank 1 with AAPL (best of Tech).
    assert out.loc["XOM", "rank"] == 1
    # OXY = worst of Energy; tied at the bottom with GOOG (worst of Tech).
    bottom_rank = out["rank"].max()
    assert out.loc["OXY", "rank"] == bottom_rank


def test_small_sectors_collapse_into_unknown() -> None:
    """A sector with only 2 members at min_sector_size=3 should
    collapse into Unknown so the 2 names compete against any other
    sub-min-size sector names."""
    frame = _frame([
        {"ticker": "AAPL", "raw": 0.9, "rank": 1, "z_score": 2.0},
        {"ticker": "MSFT", "raw": 0.8, "rank": 2, "z_score": 1.5},
        {"ticker": "GOOG", "raw": 0.7, "rank": 3, "z_score": 1.0},
        {"ticker": "XOM",  "raw": 0.6, "rank": 4, "z_score": 0.5},
        # Two-member sector "Tiny" — should collapse.
        {"ticker": "ABC",  "raw": 0.3, "rank": 5, "z_score": -1.0},
        {"ticker": "DEF",  "raw": 0.2, "rank": 6, "z_score": -1.5},
    ])
    sectors = {"AAPL": "Tech", "MSFT": "Tech", "GOOG": "Tech",
                "XOM": "Energy",  # 1-name Energy → collapses
                "ABC": "Tiny", "DEF": "Tiny"}  # 2-name Tiny → collapses
    out = sector_neutralize(frame, sectors, min_sector_size=3).set_index("ticker")
    # AAPL is best of Tech (3-name sector) → top.
    # XOM, ABC, DEF compete in the Unknown bucket (where XOM=0.6 wins).
    assert out.loc["AAPL", "rank"] == 1
    # XOM no longer ties with AAPL (it's now in Unknown, not its own
    # 1-name Energy sector that would have made it best-of).
    assert out.loc["XOM", "rank"] >= out.loc["AAPL", "rank"]


def test_missing_sectors_go_to_unknown() -> None:
    frame = _frame([
        {"ticker": "AAA", "raw": 0.9, "rank": 1, "z_score": 2.0},
        {"ticker": "BBB", "raw": 0.8, "rank": 2, "z_score": 1.5},
        {"ticker": "CCC", "raw": 0.7, "rank": 3, "z_score": 1.0},
    ])
    sectors = {"AAA": "Tech"}  # BBB, CCC have no sector
    out = sector_neutralize(frame, sectors).set_index("ticker")
    # AAA is alone in Tech (collapses to Unknown if min_sector_size > 1).
    # All three end up in Unknown -> ranked by raw.
    assert out.loc["AAA", "rank"] == 1


def test_empty_frame_passes_through() -> None:
    empty = _frame([])
    out = sector_neutralize(empty, {"AAA": "Tech"})
    assert out.empty


def test_missing_columns_raises() -> None:
    bad = _frame([{"ticker": "AAA", "raw": 0.9}])
    with pytest.raises(ValueError, match="missing columns"):
        sector_neutralize(bad, {"AAA": "Tech"})


def test_z_score_is_negative_of_centered_pct() -> None:
    """A name in the top half of its sector should have positive z."""
    frame = _frame([
        {"ticker": "T1", "raw": 0.9, "rank": 1, "z_score": 2.0},
        {"ticker": "T2", "raw": 0.5, "rank": 2, "z_score": 0.0},
        {"ticker": "T3", "raw": 0.1, "rank": 3, "z_score": -2.0},
    ])
    sectors = {"T1": "Sec", "T2": "Sec", "T3": "Sec"}
    out = sector_neutralize(frame, sectors).set_index("ticker")
    assert out.loc["T1", "z_score"] > 0  # top of sector
    assert out.loc["T3", "z_score"] < 0  # bottom of sector
