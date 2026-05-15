"""Targeted tests for src/scoring/analyzers/statistical.py.

Currently covers the seasonality as-of fix. Other sub-components of
statistical.analyze() can land here as bugs surface.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.scoring.analyzers.statistical import _calc_seasonality


def _monthly_prices(end_month: int, n_years: int = 5) -> pd.DataFrame:
    """Build daily OHLC with a DatetimeIndex ending at the last business
    day of `end_month` for `n_years` years back. Returns are arbitrary —
    the test only cares which month seasonality reads as "current"."""
    end = pd.Timestamp(2025, end_month, 1) + pd.offsets.MonthEnd(0)
    idx = pd.date_range(end=end, periods=252 * n_years, freq="B")
    rng = np.random.default_rng(42)
    close = 100 * (1 + rng.normal(0.0005, 0.01, len(idx))).cumprod()
    return pd.DataFrame(
        {"Open": close, "High": close * 1.005, "Low": close * 0.995, "Close": close},
        index=idx,
    )


class TestSeasonalityAsOf:
    """Audit finding Q-1: seasonality used `datetime.now().month` instead
    of the as-of month, polluting every historical backtest with TODAY's
    calendar month. The fix derives the month from `df.index[-1]`. These
    tests lock the new behavior in."""

    def test_reads_month_from_latest_bar_not_clock(self) -> None:
        """A df ending in March should produce a March seasonality
        signal regardless of the wall-clock month the test runs in.
        Pre-fix this test would have failed any month except March."""
        metrics: dict = {}
        signals: list = []
        df = _monthly_prices(end_month=3)
        _calc_seasonality(df, metrics, signals)
        # The signal detail (when one fires) names the month read.
        # When the random returns don't trip the ±2% bullish/bearish
        # threshold the signal list stays empty — but `_calc_seasonality`
        # writes `seasonality_sample_size` whenever it reaches that
        # month's bucket, so absence of that key = wrong month resolved.
        assert "seasonality_sample_size" in metrics, (
            f"seasonality should resolve to March from df.index[-1], "
            f"got metrics={metrics}"
        )
        # If any signal fires, it must name March, never another month.
        for sig in signals:
            if sig.get("source") == "Seasonality":
                assert "Mar" in sig["detail"], sig

    def test_reads_month_from_latest_bar_alt(self) -> None:
        """Same property in a different month — confirms it actually
        derives from df, not from a constant."""
        metrics: dict = {}
        signals: list = []
        df = _monthly_prices(end_month=8)
        _calc_seasonality(df, metrics, signals)
        assert "seasonality_sample_size" in metrics
        for sig in signals:
            if sig.get("source") == "Seasonality":
                assert "Aug" in sig["detail"], sig
