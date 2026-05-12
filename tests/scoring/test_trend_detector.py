"""Smoke tests for the trend detector.

This analyzer leans on the project's Config for sector / theme
definitions. Rather than mocking the YAML loader, we use the real
Config and feed in synthetic price + fundamentals — that exercises
the full path the scan pipeline takes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.config_loader import Config
from src.scoring.analyzers.trend_detector import analyze_stock_trend


@pytest.fixture(scope="module")
def cfg() -> Config:
    return Config()


def _price_series(n: int = 60, slope: float = 1.0) -> pd.DataFrame:
    """Synthetic price frame. ``slope`` controls whether close drifts
    upward or downward — the analyzer uses 21-day vs 50-day MA cross
    among other things."""
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    base = 100 + slope * np.arange(n, dtype=float)
    return pd.DataFrame(
        {
            "Open": base,
            "High": base * 1.01,
            "Low": base * 0.99,
            "Close": base,
            "Volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


class TestTrendDetectorContract:
    def test_returns_neutral_for_empty_fundamentals(self, cfg: Config) -> None:
        result = analyze_stock_trend(_price_series(60), {}, cfg)
        # Empty fundamentals short-circuits to a neutral baseline.
        assert result["score"] == 50

    def test_returns_neutral_when_df_missing(self, cfg: Config) -> None:
        result = analyze_stock_trend(
            None,
            {"sector": "Technology", "ticker": "AAPL"},
            cfg,
        )
        assert result["score"] == 50

    def test_emits_score_in_valid_range(self, cfg: Config) -> None:
        """Real price series + populated fundamentals → analyzer should
        produce a 0-100 score and a structured signal list."""
        prices = _price_series(120, slope=0.5)
        funds = {
            "sector": "Technology",
            "industry": "Software—Application",
            "description": "Cloud software platform for enterprises.",
            "ticker": "DEMO",
        }
        result = analyze_stock_trend(prices, funds, cfg)
        assert 0 <= result["score"] <= 100
        assert isinstance(result["signals"], list)
        # trending_themes is whatever the matcher found — could be empty.
        assert "trending_themes" in result
