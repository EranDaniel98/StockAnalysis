"""Pure-function tests for ml/feature_store.py.

The persistence path (``compute_and_persist_snapshot``) needs Postgres
and lives in integration tests. Here we cover the two helpers that
deserve unit-level scrutiny: ``_score_at_as_of`` (with monkey-patched
analyzers) and ``_zscore_universe``.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.ml import feature_store
from src.ml.feature_store import (
    MIN_HISTORY_BARS,
    SnapshotRow,
    _score_at_as_of,
    _zscore_universe,
)


def _stub_score(value: float):
    """A fake analyzer.analyze() — returns a constant ``score``."""
    def _f(*_args, **_kwargs):
        return {"score": value, "signals": []}
    return _f


def _price_frame(n_bars: int, tz: str | None = None) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n_bars, freq="B", tz=tz)
    return pd.DataFrame(
        {
            "Open": np.linspace(100, 110, n_bars),
            "High": np.linspace(101, 111, n_bars),
            "Low": np.linspace(99, 109, n_bars),
            "Close": np.linspace(100, 110, n_bars),
            "Volume": np.full(n_bars, 1_000_000),
        },
        index=idx,
    )


class TestScoreAtAsOf:
    @pytest.fixture(autouse=True)
    def _patch_analyzers(self, monkeypatch):
        """Replace each analyzer with a deterministic stub so the test
        is about the slicing/coercion logic, not the analyzer internals."""
        monkeypatch.setattr(feature_store.technical, "analyze", _stub_score(60.0))
        monkeypatch.setattr(feature_store.fundamental, "analyze", _stub_score(55.0))
        monkeypatch.setattr(feature_store.patterns, "analyze", _stub_score(50.0))
        monkeypatch.setattr(feature_store.statistical, "analyze", _stub_score(45.0))
        monkeypatch.setattr(
            feature_store, "analyze_stock_trend", _stub_score(65.0)
        )
        monkeypatch.setattr(feature_store.alpha158, "analyze", _stub_score(70.0))

    def test_returns_none_for_empty_frame(self) -> None:
        result = _score_at_as_of("AAA", pd.DataFrame(), {}, config=None,
                                 as_of=pd.Timestamp("2025-06-01"))
        assert result is None

    def test_returns_none_when_history_below_threshold(self) -> None:
        prices = _price_frame(MIN_HISTORY_BARS - 1)
        as_of = prices.index[-1]
        result = _score_at_as_of("AAA", prices, {}, config=None, as_of=as_of)
        assert result is None

    def test_returns_snapshot_with_stubbed_scores(self) -> None:
        prices = _price_frame(MIN_HISTORY_BARS + 10)
        as_of = prices.index[-1]
        result = _score_at_as_of("AAA", prices, {}, config=None, as_of=as_of)
        assert isinstance(result, SnapshotRow)
        assert result.ticker == "AAA"
        assert result.values == {
            "technical": 60.0,
            "fundamental": 55.0,
            "pattern": 50.0,
            "statistical": 45.0,
            "trend": 65.0,
            "alpha158": 70.0,
        }

    def test_coerces_nan_to_zero(self, monkeypatch) -> None:
        """An analyzer returning NaN must surface as 0.0 — JSONB can't
        store NaN, and z-scoring will absorb the neutral value."""
        monkeypatch.setattr(
            feature_store.technical, "analyze", _stub_score(float("nan"))
        )
        prices = _price_frame(MIN_HISTORY_BARS + 5)
        result = _score_at_as_of(
            "AAA", prices, {}, config=None, as_of=prices.index[-1]
        )
        assert result is not None
        assert result.values["technical"] == 0.0

    def test_normalizes_tz_aware_input(self) -> None:
        prices = _price_frame(MIN_HISTORY_BARS + 5, tz="UTC")
        # Pass a tz-naive as_of — the function should normalize both sides
        # so the comparison doesn't blow up.
        as_of = pd.Timestamp(prices.index[-1].tz_localize(None))
        result = _score_at_as_of("AAA", prices, {}, config=None, as_of=as_of)
        assert result is not None

    def test_returns_none_when_analyzer_raises(self, monkeypatch) -> None:
        def _boom(*_, **__):
            raise RuntimeError("analyzer exploded")

        monkeypatch.setattr(feature_store.alpha158, "analyze", _boom)
        prices = _price_frame(MIN_HISTORY_BARS + 5)
        result = _score_at_as_of(
            "AAA", prices, {}, config=None, as_of=prices.index[-1]
        )
        assert result is None


class TestZscoreUniverse:
    def _row(self, ticker: str, **values) -> SnapshotRow:
        return SnapshotRow(
            ticker=ticker,
            as_of=pd.Timestamp("2025-06-01"),
            values=values,
        )

    def test_empty_input_returns_empty(self) -> None:
        assert _zscore_universe([]) == []

    def test_z_scores_have_zero_mean_and_unit_std(self) -> None:
        rows = [
            self._row("A", technical=40, fundamental=50),
            self._row("B", technical=50, fundamental=50),
            self._row("C", technical=60, fundamental=50),
        ]
        zscored = _zscore_universe(rows)
        assert len(zscored) == 3
        z_technical = [z["technical"] for _, z in zscored]
        # ddof=1 sample std → for [40, 50, 60], std = 10, mean = 50 →
        # z = [-1, 0, 1]
        assert pytest.approx(z_technical, abs=1e-9) == [-1.0, 0.0, 1.0]

    def test_degenerate_factor_gets_zero_z(self) -> None:
        """A factor where every ticker has the same value would produce
        NaN z-scores (divide by zero std). The function fills NaN with 0
        because JSONB can't round-trip NaN."""
        rows = [
            self._row("A", technical=50, fundamental=10),
            self._row("B", technical=50, fundamental=20),
        ]
        zscored = _zscore_universe(rows)
        # technical is constant → every z_technical is 0.0
        assert all(z["technical"] == 0.0 for _, z in zscored)
        # fundamental varies → z_fundamental is non-zero
        assert any(z["fundamental"] != 0.0 for _, z in zscored)

    def test_z_scores_align_with_input_row_order(self) -> None:
        rows = [
            self._row("A", technical=10),
            self._row("B", technical=20),
            self._row("C", technical=30),
        ]
        zscored = _zscore_universe(rows)
        tickers = [r.ticker for r, _ in zscored]
        assert tickers == ["A", "B", "C"]
