"""Tests for src.scoring.sector_stats.

The helper is pure (in: dict of fundamentals; out: per-sector quantile
table), so we drive it with hand-built inputs. Edge cases matter more
than scale here — sparse sectors and bad data are the common failure
modes in production yfinance dumps.
"""

from __future__ import annotations

import pytest

from src.scoring.sector_stats import (
    DEFAULT_MIN_COHORT,
    compute_sector_stats,
    percentile_bucket,
)


def _make_funds(rows: list[dict]) -> dict[str, dict]:
    """Convenience: each row is a partial fundamentals dict; tickers
    auto-numbered."""
    return {f"T{i:02d}": r for i, r in enumerate(rows)}


class TestComputeSectorStats:
    def test_empty_input(self) -> None:
        assert compute_sector_stats({}) == {}

    def test_drops_unknown_and_missing_sector(self) -> None:
        funds = _make_funds(
            [
                {"sector": "Unknown", "pe_trailing": 15.0},
                {"sector": None, "pe_trailing": 20.0},
                {"pe_trailing": 25.0},  # no sector key at all
            ]
        )
        assert compute_sector_stats(funds, min_cohort=1) == {}

    def test_drops_sectors_below_min_cohort(self) -> None:
        """Only 3 tech tickers — below default min_cohort=5 — so no
        stats published. Analyzer will fall back to absolute thresholds."""
        funds = _make_funds(
            [{"sector": "Tech", "pe_trailing": v} for v in (10, 20, 30)]
        )
        assert compute_sector_stats(funds) == {}

    def test_publishes_stats_when_cohort_large_enough(self) -> None:
        funds = _make_funds(
            [
                {"sector": "Tech", "pe_trailing": v}
                for v in (10, 15, 20, 25, 30, 40)
            ]
        )
        stats = compute_sector_stats(funds)
        tech = stats["Tech"]["pe_trailing"]
        assert tech["count"] == 6
        # Sanity: quantiles are within the input range and ordered.
        assert tech["q1"] < tech["median"] < tech["q3"]
        assert 10 <= tech["q1"] <= 40
        assert 10 <= tech["q3"] <= 40

    def test_drops_metric_with_too_few_values(self) -> None:
        """Cohort has 6 tickers in sector but only 3 expose pe_trailing
        — the metric must be dropped while other metrics survive."""
        funds = _make_funds(
            [
                {"sector": "Tech", "pe_trailing": 15.0, "pb_ratio": 2.0},
                {"sector": "Tech", "pe_trailing": 20.0, "pb_ratio": 3.0},
                {"sector": "Tech", "pe_trailing": 25.0, "pb_ratio": 4.0},
                {"sector": "Tech", "pb_ratio": 5.0},
                {"sector": "Tech", "pb_ratio": 6.0},
                {"sector": "Tech", "pb_ratio": 7.0},
            ]
        )
        stats = compute_sector_stats(funds)
        # 3 pe_trailing values < min_cohort default of 5 → metric dropped.
        assert "pe_trailing" not in stats["Tech"]
        # All 6 have pb_ratio → metric present.
        assert "pb_ratio" in stats["Tech"]

    def test_negative_and_zero_pe_excluded(self) -> None:
        """Loss-making (negative P/E) and zeros must not poison the
        sector cohort — they're skipped, not zero-imputed."""
        funds = _make_funds(
            [{"sector": "Tech", "pe_trailing": v} for v in (-5.0, 0.0, 10.0, 15.0, 20.0, 25.0, 30.0)]
        )
        stats = compute_sector_stats(funds, min_cohort=3)
        pe = stats["Tech"]["pe_trailing"]
        assert pe["count"] == 5  # negatives + zero dropped, 5 valid remain
        assert pe["q1"] >= 10.0

    def test_nan_and_non_numeric_excluded(self) -> None:
        funds = _make_funds(
            [
                {"sector": "Tech", "pe_trailing": float("nan")},
                {"sector": "Tech", "pe_trailing": "n/a"},
                *[{"sector": "Tech", "pe_trailing": v} for v in (10, 15, 20, 25, 30)],
            ]
        )
        stats = compute_sector_stats(funds, min_cohort=3)
        assert stats["Tech"]["pe_trailing"]["count"] == 5

    def test_independent_sectors(self) -> None:
        """Tech and Utilities each have their own cohort; one sector's
        sparse data must not contaminate another."""
        funds = _make_funds(
            [
                *[{"sector": "Tech", "pe_trailing": v} for v in (25, 30, 35, 40, 50, 60)],
                *[{"sector": "Utilities", "pe_trailing": v} for v in (12, 14, 16, 18, 20, 22)],
            ]
        )
        stats = compute_sector_stats(funds)
        assert stats["Tech"]["pe_trailing"]["median"] > stats["Utilities"]["pe_trailing"]["median"]


class TestPercentileBucket:
    @pytest.fixture
    def stats(self) -> dict[str, float]:
        return {"q1": 10.0, "median": 20.0, "q3": 30.0, "count": 10.0}

    @pytest.mark.parametrize(
        "value,expected",
        [
            (5.0, "low"),
            (10.0, "low"),          # boundary inclusive
            (10.01, "below_median"),
            (20.0, "below_median"), # boundary
            (20.01, "above_median"),
            (30.0, "above_median"), # boundary
            (30.01, "high"),
            (100.0, "high"),
        ],
    )
    def test_buckets(self, stats: dict[str, float], value: float, expected: str) -> None:
        assert percentile_bucket(value, stats) == expected


def test_min_cohort_constant_is_documented() -> None:
    """Defensive check: someone may bump the default; make sure the
    constant is visible so tests + code stay in sync."""
    assert DEFAULT_MIN_COHORT >= 3
