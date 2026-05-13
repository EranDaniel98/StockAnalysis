"""Tests for src.scoring.analyzers.sector_flows.

Pure analyzer over a sector ETF's OHLCV DataFrame. Hand-built synthetic
series cover the score bands, slicing semantics, and the no-signal
fallthrough.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from src.scoring.analyzers import sector_flows as sf
from src.scoring.analyzers.sector_flows import (
    SECTOR_TO_ETF,
    SectorFlowsParams,
    analyze,
)


def _ohlcv(
    closes: list[float],
    volumes: list[float] | None = None,
    start: str = "2023-01-02",
) -> pd.DataFrame:
    """Build a daily OHLCV frame from a closing-price list. Volumes
    default to a flat baseline so the volume-surge test can override
    just the tail."""
    n = len(closes)
    if volumes is None:
        volumes = [1_000_000.0] * n
    assert len(volumes) == n
    idx = pd.date_range(start, periods=n, freq="B")
    return pd.DataFrame({
        "Open": closes,
        "High": closes,
        "Low": closes,
        "Close": closes,
        "Volume": volumes,
    }, index=idx)


@pytest.fixture
def as_of() -> pd.Timestamp:
    """A timestamp comfortably past the synthetic series so the slice
    keeps the whole history."""
    return pd.Timestamp("2024-12-31")


class TestNoSignal:
    def test_none_on_empty_dataframe(self, as_of) -> None:
        assert analyze(pd.DataFrame(), as_of=as_of) is None

    def test_none_on_too_little_history(self, as_of) -> None:
        """50 bars < 63-bar min_history → no signal."""
        df = _ohlcv(list(np.linspace(100.0, 105.0, 50)))
        assert analyze(df, as_of=as_of) is None

    def test_none_when_close_column_missing(self, as_of) -> None:
        df = pd.DataFrame({"Price": [100.0] * 80},
                          index=pd.date_range("2024-01-02", periods=80, freq="B"))
        assert analyze(df, as_of=as_of) is None


class TestScoreBands:
    def test_strong_inflow_scores_bullish(self, as_of) -> None:
        """+10% over the last 20 bars with a 1.5x volume surge — top band."""
        n = 120
        base = list(np.linspace(100.0, 100.0, n - 20))
        surge_close = list(np.linspace(100.0, 110.0, 20))
        closes = base + surge_close
        # Make the surge sharp enough that the trailing-20 / trailing-60
        # ratio clears 1.3 even though the long-window mean already
        # absorbs the surge tail.
        volumes = [1_000_000.0] * (n - 20) + [2_500_000.0] * 20
        df = _ohlcv(closes, volumes=volumes)
        result = analyze(df, as_of=as_of)
        assert result is not None
        assert result["score"] > 65
        assert any(s["type"] == "bullish" for s in result["signals"])
        assert result["indicators"]["etf_return_20d"] > 5.0
        assert result["indicators"]["etf_volume_ratio_20d"] > 1.3

    def test_sustained_outflow_scores_bearish(self, as_of) -> None:
        """-8% over 20 bars — bearish band."""
        n = 120
        closes = list(np.linspace(100.0, 100.0, n - 20)) + list(np.linspace(100.0, 92.0, 20))
        df = _ohlcv(closes)
        result = analyze(df, as_of=as_of)
        assert result is not None
        assert result["score"] < 40
        assert any(s["type"] == "bearish" for s in result["signals"])

    def test_sideways_scores_neutral(self, as_of) -> None:
        """Flat tape — score lands at 50."""
        df = _ohlcv([100.0] * 120)
        result = analyze(df, as_of=as_of)
        assert result is not None
        assert 45 <= result["score"] <= 55

    def test_crash_with_volume_surge_scores_capitulation(self, as_of) -> None:
        """-15% on 1.5x volume — capitulation band, score in [15, 20]."""
        n = 120
        closes = list(np.linspace(100.0, 100.0, n - 20)) + list(np.linspace(100.0, 85.0, 20))
        volumes = [1_000_000.0] * (n - 20) + [2_500_000.0] * 20
        df = _ohlcv(closes, volumes=volumes)
        result = analyze(df, as_of=as_of)
        assert result is not None
        assert result["score"] <= 20


class TestAsOfSlicing:
    def test_rows_on_or_after_as_of_are_excluded(self) -> None:
        """A flat history followed by a synthetic spike AFTER as_of must
        be ignored — the slice is strictly less-than."""
        n = 120
        flat = [100.0] * 100
        spike_after = list(np.linspace(100.0, 200.0, 20))
        df = _ohlcv(flat + spike_after, start="2024-01-02")
        as_of = df.index[100]  # cut right before the spike
        result = analyze(df, as_of=as_of)
        assert result is not None
        # Spike is past as_of → return should round to ~0%.
        assert abs(result["indicators"]["etf_return_20d"]) < 1.0

    def test_window_math_on_synthetic_data(self, as_of) -> None:
        """Construct closes where the 20d-prior bar is exactly 100 and
        the last bar is exactly 110 → etf_return_20d == 10.00."""
        closes = [100.0] * 100
        closes[-21] = 100.0   # 20 bars back from iloc[-1]
        closes[-1] = 110.0
        df = _ohlcv(closes)
        result = analyze(df, as_of=as_of)
        assert result is not None
        assert result["indicators"]["etf_return_20d"] == pytest.approx(10.0, abs=0.01)

    def test_tz_naive_and_tz_aware_as_of_both_work(self) -> None:
        """A tz-aware as_of must not crash against a naive index."""
        closes = list(np.linspace(100.0, 105.0, 120))
        df = _ohlcv(closes)
        naive = pd.Timestamp("2024-12-31")
        aware = pd.Timestamp("2024-12-31", tz="UTC")
        r_naive = analyze(df, as_of=naive)
        r_aware = analyze(df, as_of=aware)
        assert r_naive is not None and r_aware is not None
        assert r_naive["score"] == r_aware["score"]


class TestResultShape:
    def test_signals_list_empty_when_neutral(self, as_of) -> None:
        """A neutral score (~50) should not emit a bullish or bearish
        signal — empty signals list is the no-call convention."""
        df = _ohlcv([100.0] * 120)
        result = analyze(df, as_of=as_of)
        assert result is not None
        assert result["signals"] == []

    def test_etf_symbol_passed_through(self, as_of) -> None:
        df = _ohlcv([100.0] * 120)
        result = analyze(df, as_of=as_of, etf_symbol="XLK")
        assert result is not None
        assert result["sector_etf"] == "XLK"

    def test_flow_indicator_present(self, as_of) -> None:
        df = _ohlcv([100.0] * 120)
        result = analyze(df, as_of=as_of)
        assert result is not None
        assert "flow_indicator" in result
        assert isinstance(result["flow_indicator"], float)


class TestParamsImmutable:
    def test_params_is_frozen(self) -> None:
        params = SectorFlowsParams()
        with pytest.raises(dataclasses.FrozenInstanceError):
            params.short_window = 99  # type: ignore[misc]

    def test_custom_params_change_behavior(self, as_of) -> None:
        """Tighten min_history_bars to 200 — a 120-bar series no
        longer qualifies."""
        df = _ohlcv(list(np.linspace(100.0, 110.0, 120)))
        strict = SectorFlowsParams(min_history_bars=200)
        assert analyze(df, as_of=as_of, params=strict) is None


class TestSectorMapping:
    def test_both_financials_aliases_resolve_to_xlf(self) -> None:
        """yfinance has used both labels at different times — both must
        land on XLF so the caller doesn't have to special-case."""
        assert SECTOR_TO_ETF["Financials"] == "XLF"
        assert SECTOR_TO_ETF["Financial Services"] == "XLF"

    def test_all_eleven_gics_sectors_covered(self) -> None:
        """The S&P / GICS taxonomy has 11 sectors. The map should cover
        each one (Financials counted once)."""
        unique_etfs = set(SECTOR_TO_ETF.values())
        assert len(unique_etfs) == 11
