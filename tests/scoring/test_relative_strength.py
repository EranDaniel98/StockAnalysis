"""Tests for src.scoring.analyzers.relative_strength.

Pure analyzer: in goes (stock_df, benchmark_df, config), out comes a
score dict (or None). Hand-built series cover the boundary buckets,
missing-data behavior, and the multi-window aggregation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.scoring.analyzers import relative_strength as rs


class _StubConfig:
    """Minimal Config stand-in. The analyzer only calls ``config.get``."""

    def __init__(self, overrides: dict | None = None) -> None:
        self._overrides = overrides or {}

    def get(self, *keys, default=None):
        # Walk into self._overrides via the same path the analyzer uses.
        node = self._overrides
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                return default
        return node


def _series(values: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(values), freq="B")
    return pd.DataFrame({"Close": values}, index=idx)


@pytest.fixture
def config() -> _StubConfig:
    return _StubConfig()


class TestAnalyze:
    def test_neutral_when_stock_matches_benchmark(self, config) -> None:
        """Identical series → 0% RS → score around 50."""
        prices = list(np.linspace(100.0, 110.0, 300))
        result = rs.analyze(_series(prices), _series(prices), config)
        assert result is not None
        assert result["score"] == 50
        # Each window's RS should be exactly zero.
        for window in (21, 63, 126, 252):
            assert result["indicators"][f"rs_{window}d"] == 0.0

    def test_strong_outperformance_scores_bullish(self, config) -> None:
        """Stock up 40% while SPY up 10% → +30% weighted RS → top bucket."""
        n = 300
        stock = list(np.linspace(100.0, 140.0, n))
        bench = list(np.linspace(100.0, 110.0, n))
        result = rs.analyze(_series(stock), _series(bench), config)
        assert result is not None
        assert result["score"] >= 80
        bullish_sources = {s["source"] for s in result["signals"]}
        assert "Relative Strength" in bullish_sources

    def test_strong_underperformance_scores_bearish(self, config) -> None:
        """Stock down 20% while SPY up 10% → -30% weighted RS → bottom bucket."""
        n = 300
        stock = list(np.linspace(100.0, 80.0, n))
        bench = list(np.linspace(100.0, 110.0, n))
        result = rs.analyze(_series(stock), _series(bench), config)
        assert result is not None
        assert result["score"] <= 25
        bearish_sources = {s["source"] for s in result["signals"]}
        assert "Relative Strength" in bearish_sources

    def test_returns_none_when_benchmark_missing(self, config) -> None:
        assert rs.analyze(_series([100.0] * 300), None, config) is None
        assert rs.analyze(None, _series([100.0] * 300), config) is None

    def test_returns_none_when_history_too_short(self, config) -> None:
        """Only 20 bars — even the shortest 21d window can't fire."""
        result = rs.analyze(_series([100.0] * 20), _series([100.0] * 20), config)
        assert result is None

    def test_partial_coverage_when_some_windows_too_short(self, config) -> None:
        """50 bars: 21d window fires, 63/126/252 can't. Score must still
        return something (re-normalized on partial coverage) — not None."""
        stock = list(np.linspace(100.0, 120.0, 50))
        bench = list(np.linspace(100.0, 105.0, 50))
        result = rs.analyze(_series(stock), _series(bench), config)
        assert result is not None
        # Only the 21d window produced data.
        assert "rs_21d" in result["indicators"]
        assert "rs_252d" not in result["indicators"]
        # Coverage equals the 1M weight (0.10 normalized).
        assert 0 < result["indicators"]["coverage"] <= 1.0

    def test_handles_non_overlapping_indices(self, config) -> None:
        """Stock starts a year after the benchmark — must use the
        intersection of the indices, not crash on misalignment."""
        bench = _series(list(np.linspace(100.0, 110.0, 500)), start="2023-01-02")
        stock = _series(list(np.linspace(100.0, 130.0, 300)), start="2024-01-02")
        result = rs.analyze(stock, bench, config)
        assert result is not None
        # The 21d window fits in the overlap, the 252d doesn't.
        assert "rs_21d" in result["indicators"]

    def test_zero_close_at_window_start_is_rejected(self, config) -> None:
        """A zero Close at the window's anchor would produce -inf/NaN.
        The analyzer drops just that window and keeps the rest."""
        n = 300
        stock = [100.0] * n
        # iloc[-252] is the anchor for the 252d window. Setting it to 0
        # forces _aligned_returns to reject that window.
        stock[-252] = 0.0
        bench = [100.0] * n
        result = rs.analyze(_series(stock), _series(bench), config)
        assert result is not None
        assert result["score"] == 50
        assert "rs_252d" not in result["indicators"]
        # Shorter windows still produce data.
        assert "rs_21d" in result["indicators"]

    def test_custom_windows_via_config(self) -> None:
        """A config override picks up a different lookback set."""
        config = _StubConfig({
            "scoring": {
                "relative_strength": {
                    "windows_days": [60, 30],
                    "weights": [0.5, 0.5],
                }
            }
        })
        stock = list(np.linspace(100.0, 120.0, 100))
        bench = list(np.linspace(100.0, 110.0, 100))
        result = rs.analyze(_series(stock), _series(bench), config)
        assert result is not None
        assert "rs_60d" in result["indicators"]
        assert "rs_252d" not in result["indicators"]

    def test_mismatched_windows_weights_falls_back_to_defaults(
        self, caplog
    ) -> None:
        """Length mismatch is a config typo — log a warning, don't crash."""
        config = _StubConfig({
            "scoring": {
                "relative_strength": {
                    "windows_days": [60],
                    "weights": [0.4, 0.3],
                }
            }
        })
        stock = list(np.linspace(100.0, 120.0, 300))
        bench = list(np.linspace(100.0, 110.0, 300))
        with caplog.at_level("WARNING"):
            result = rs.analyze(_series(stock), _series(bench), config)
        assert result is not None
        # Defaults restored → 252d window present.
        assert "rs_252d" in result["indicators"]
        assert any("mismatch" in rec.message for rec in caplog.records)


class TestScoreFromRs:
    @pytest.mark.parametrize(
        "rs_value,expected_band",
        [
            (0.30, range(85, 96)),     # very strong → 90
            (0.10, range(75, 86)),     # strong → 80
            (0.05, range(60, 70)),     # mild → 65
            (0.00, range(45, 55)),     # neutral → 50
            (-0.05, range(30, 40)),    # mild weak → 35
            (-0.15, range(15, 25)),    # weak → 20
            (-0.30, range(5, 15)),     # crashing → 10
        ],
    )
    def test_score_bands(self, rs_value: float, expected_band: range) -> None:
        score = rs._score_from_rs(rs_value)
        assert score in expected_band
