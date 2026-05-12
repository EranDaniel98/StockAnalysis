"""Tests for src.market_data.regime — pure classifier + entry gate.

The classifier is a small pure function over (spy series, vix series,
as_of, params), so we drive it with hand-built DataFrames where every
boundary case is unambiguous. No yfinance calls.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.market_data.regime import (
    RegimeParams,
    RegimeSnapshot,
    classify_at,
    gate_allows_entry,
)


def _bars(closes: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    """OHLCV-shaped frame with only 'Close' filled — that's all the
    classifier touches."""
    idx = pd.date_range(start, periods=len(closes), freq="B")
    return pd.DataFrame({"Close": closes}, index=idx)


def _spy_above_sma() -> pd.DataFrame:
    """SPY series where the latest close is meaningfully above the SMA200."""
    # 250 bars: first 200 climb 100→200, then plateau at 220. SMA200 sits
    # near the climbing-window mean (~150), latest close 220 → above.
    climb = list(np.linspace(100, 200, 200))
    plateau = [220.0] * 50
    return _bars(climb + plateau)


def _spy_below_sma() -> pd.DataFrame:
    """SPY series where the latest close has fallen below the SMA200."""
    # Climb 100→200 over 200 bars, then crash to 140. SMA200 ~150, last 140.
    climb = list(np.linspace(100, 200, 200))
    crash = [140.0] * 50
    return _bars(climb + crash)


class TestClassifyAt:
    @pytest.fixture
    def params(self) -> RegimeParams:
        return RegimeParams(sma_period=200, vix_low=20.0, vix_high=25.0)

    def test_bull_regime(self, params: RegimeParams) -> None:
        spy = _spy_above_sma()
        vix = _bars([15.0] * 250)  # well below vix_low
        snap = classify_at(spy, vix, spy.index[-1], params)
        assert snap.label == "bull"
        assert snap.spy_above_sma is True
        assert snap.vix_level == 15.0

    def test_bear_regime(self, params: RegimeParams) -> None:
        spy = _spy_below_sma()
        vix = _bars([30.0] * 250)  # above vix_high
        snap = classify_at(spy, vix, spy.index[-1], params)
        assert snap.label == "bear"
        assert snap.spy_above_sma is False

    def test_chop_when_spy_up_but_vix_high(self, params: RegimeParams) -> None:
        """Bull-side SPY + elevated VIX = caution (not 'bull')."""
        spy = _spy_above_sma()
        vix = _bars([22.0] * 250)
        snap = classify_at(spy, vix, spy.index[-1], params)
        assert snap.label == "chop"

    def test_chop_when_spy_down_but_vix_calm(self, params: RegimeParams) -> None:
        """Bear-side SPY but VIX not panicking = chop, not bear."""
        spy = _spy_below_sma()
        vix = _bars([18.0] * 250)
        snap = classify_at(spy, vix, spy.index[-1], params)
        assert snap.label == "chop"

    def test_unknown_when_spy_missing(self, params: RegimeParams) -> None:
        snap = classify_at(None, _bars([15.0] * 250), pd.Timestamp("2024-12-31"), params)
        assert snap.label == "unknown"

    def test_unknown_when_history_shorter_than_sma_period(
        self, params: RegimeParams
    ) -> None:
        """Fewer than sma_period bars → SMA undefined → unknown."""
        spy = _bars([100.0] * 100)  # 100 < 200
        vix = _bars([15.0] * 100)
        snap = classify_at(spy, vix, spy.index[-1], params)
        assert snap.label == "unknown"

    def test_no_lookahead(self, params: RegimeParams) -> None:
        """Data after as_of must not influence the snapshot."""
        spy_good = _spy_above_sma()
        # Append a crash AFTER our as_of point — should be ignored.
        crash_idx = pd.date_range(
            spy_good.index[-1] + pd.Timedelta(days=1), periods=20, freq="B"
        )
        crash_df = pd.DataFrame({"Close": [50.0] * 20}, index=crash_idx)
        spy = pd.concat([spy_good, crash_df])
        vix = _bars([15.0] * len(spy))
        # Classify as of the pre-crash date — must still be bull.
        snap = classify_at(spy, vix, spy_good.index[-1], params)
        assert snap.label == "bull"

    def test_tz_aware_inputs_normalized(self, params: RegimeParams) -> None:
        """Tz-aware UTC frames are normalized to naive internally."""
        spy = _spy_above_sma()
        spy.index = spy.index.tz_localize("UTC")
        vix = _bars([15.0] * len(spy))
        vix.index = vix.index.tz_localize("UTC")
        # tz-aware as_of: also accepted
        snap = classify_at(
            spy, vix, pd.Timestamp(spy.index[-1]), params
        )
        assert snap.label == "bull"

    def test_custom_thresholds(self) -> None:
        """Tighter VIX bands flip the classification."""
        spy = _spy_above_sma()
        vix = _bars([18.0] * 250)
        loose = RegimeParams(sma_period=200, vix_low=20.0, vix_high=25.0)
        tight = RegimeParams(sma_period=200, vix_low=15.0, vix_high=20.0)
        assert classify_at(spy, vix, spy.index[-1], loose).label == "bull"
        assert classify_at(spy, vix, spy.index[-1], tight).label == "chop"


class TestGateAllowsEntry:
    @pytest.mark.parametrize(
        "label,mode,expected",
        [
            ("bull", "off", True),
            ("bear", "off", True),
            ("chop", "off", True),
            ("unknown", "off", True),
            ("bull", "skip_bear", True),
            ("chop", "skip_bear", True),
            ("bear", "skip_bear", False),
            ("unknown", "skip_bear", True),   # gate must not flatten on outage
            ("bull", "skip_bear_and_chop", True),
            ("chop", "skip_bear_and_chop", False),
            ("bear", "skip_bear_and_chop", False),
            ("unknown", "skip_bear_and_chop", True),
        ],
    )
    def test_truth_table(self, label, mode, expected) -> None:
        assert gate_allows_entry(label, mode) is expected
