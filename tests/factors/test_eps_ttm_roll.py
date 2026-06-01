"""Regression tests for the TTM-EPS roll (compute_eps_ttm).

Guards the fix from commit ff13d8b: TTM = latest 10-K annual EPS + post-10-K
quarters - their prior-year counterparts. The old code summed the 4 most-recent
10-Qs, which omits Q4 (reported in the 10-K) and spans ~5 quarters.

No DB: FundamentalsPITLoader is constructed directly from FundamentalSnapshot
rows, so these assert exact numeric TTM values offline. The smoke tests in
test_quality_value_smoke.py only check shape, so this is the arithmetic guard.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.contracts.entities.fundamentals import FundamentalSnapshot
from src.factors.fundamentals_pit_loader import FundamentalsPITLoader


def _snap(source: str, ymd: str, eps: float, ticker: str = "TST") -> FundamentalSnapshot:
    y, m, d = (int(x) for x in ymd.split("-"))
    return FundamentalSnapshot(
        ticker=ticker,
        valid_from=datetime(y, m, d, tzinfo=timezone.utc),
        source=source,  # "edgar_10k" | "edgar_10q"
        eps_diluted=eps,
    )


def test_ttm_rolls_10k_anchor_plus_post_anchor_quarter() -> None:
    """FY anchor + one post-10-K quarter, minus its prior-year quarter."""
    loader = FundamentalsPITLoader([
        _snap("edgar_10q", "2022-05-01", 1.50),   # Q1-2022 (prior-year match)
        _snap("edgar_10k", "2023-02-01", 6.00),   # FY2022 annual anchor
        _snap("edgar_10q", "2023-05-01", 2.00),   # Q1-2023 (post-anchor)
    ])
    # 6.00 + 2.00 - 1.50 = 6.50
    assert loader.compute_eps_ttm("TST", datetime(2023, 6, 1, tzinfo=timezone.utc)) == 6.50


def test_ttm_is_just_the_anchor_when_no_post_anchor_quarter() -> None:
    """No 10-Q after the 10-K -> TTM is exactly the fiscal-year figure."""
    loader = FundamentalsPITLoader([
        _snap("edgar_10k", "2023-02-01", 6.00),
    ])
    assert loader.compute_eps_ttm("TST", datetime(2023, 3, 1, tzinfo=timezone.utc)) == 6.00


def test_ttm_none_without_anchor_and_under_four_quarters() -> None:
    """No 10-K anchor and fewer than 4 10-Qs -> cannot form a TTM."""
    loader = FundamentalsPITLoader([
        _snap("edgar_10q", "2023-02-01", 1.00),
        _snap("edgar_10q", "2023-05-01", 2.00),
    ])
    assert loader.compute_eps_ttm("TST", datetime(2023, 6, 1, tzinfo=timezone.utc)) is None


def test_ttm_legacy_four_quarter_fallback_without_anchor() -> None:
    """No 10-K but >=4 10-Qs -> legacy sum of the 4 most recent."""
    loader = FundamentalsPITLoader([
        _snap("edgar_10q", "2022-05-01", 1.00),
        _snap("edgar_10q", "2022-08-01", 2.00),
        _snap("edgar_10q", "2022-11-01", 3.00),
        _snap("edgar_10q", "2023-05-01", 4.00),
    ])
    # sum of the 4 most-recent = 10.0
    assert loader.compute_eps_ttm("TST", datetime(2023, 6, 1, tzinfo=timezone.utc)) == 10.00


def test_ttm_none_when_prior_year_quarter_missing() -> None:
    """Post-anchor quarter with no matching prior-year quarter -> None (no guess)."""
    loader = FundamentalsPITLoader([
        _snap("edgar_10k", "2023-02-01", 6.00),
        _snap("edgar_10q", "2023-05-01", 2.00),  # Q1-2023 but no Q1-2022 to net out
    ])
    assert loader.compute_eps_ttm("TST", datetime(2023, 6, 1, tzinfo=timezone.utc)) is None


def test_ttm_excludes_rows_after_as_of() -> None:
    """PIT discipline: a 10-Q filed after as_of must not enter the roll."""
    loader = FundamentalsPITLoader([
        _snap("edgar_10q", "2022-05-01", 1.50),
        _snap("edgar_10k", "2023-02-01", 6.00),
        _snap("edgar_10q", "2023-05-01", 2.00),  # filed AFTER the as_of below
    ])
    # as_of before the Q1-2023 filing -> TTM is just the anchor.
    assert loader.compute_eps_ttm("TST", datetime(2023, 3, 1, tzinfo=timezone.utc)) == 6.00
