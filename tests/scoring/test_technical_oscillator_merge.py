"""Tests for the RSI+Stochastic merge in technical.analyze.

The merge is gated by ``risk_management.momentum_oscillator.merge_rsi_stoch``.
Default false (legacy independent behavior). When true, the two
indicators share a single composite slot and emit one signal only
when they agree.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.config_loader import Config
from src.scoring.analyzers import technical


def _oversold_bars(n: int = 200) -> pd.DataFrame:
    """A long climb followed by a sharp pullback — both RSI and Stoch
    will sit firmly in oversold territory on the last bar."""
    climb = list(np.linspace(50.0, 100.0, n - 30))
    crash = list(np.linspace(100.0, 70.0, 30))
    closes = np.array(climb + crash)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.005,
            "Low": closes * 0.995,
            "Close": closes,
            "Volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


def _overbought_bars(n: int = 200) -> pd.DataFrame:
    """A long flat period then a sharp run-up — both oscillators land
    overbought on the last bar."""
    flat = [50.0] * (n - 30)
    pop = list(np.linspace(50.0, 80.0, 30))
    closes = np.array(flat + pop)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.005,
            "Low": closes * 0.995,
            "Close": closes,
            "Volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


def _cfg(merge: bool) -> Config:
    cfg = Config()
    cfg.settings.setdefault("risk_management", {})["momentum_oscillator"] = {
        "merge_rsi_stoch": merge,
    }
    return cfg


class TestMergeDisabled:
    """Legacy path — RSI and Stoch fire independently. Sanity check
    that the new code path doesn't alter the default behavior."""

    def test_both_indicators_present_in_indicators_dict(self) -> None:
        result = technical.analyze(_oversold_bars(), _cfg(False))
        assert "rsi" in result["indicators"]
        assert "stoch_k" in result["indicators"]

    def test_separate_signals_emitted(self) -> None:
        result = technical.analyze(_oversold_bars(), _cfg(False))
        sources = {s["source"] for s in result["signals"]}
        assert "RSI" in sources
        assert "Stochastic" in sources
        # Crucially: no merged signal in legacy mode.
        assert "MomOsc" not in sources


class TestMergeEnabled:
    def test_emits_one_merged_signal_when_both_oversold(self) -> None:
        result = technical.analyze(_oversold_bars(), _cfg(True))
        sources = [s["source"] for s in result["signals"]]
        types = {(s["source"], s["type"]) for s in result["signals"]}
        # No separate RSI/Stoch oscillator signals — only the merged one.
        assert "RSI" not in sources
        assert "Stochastic" not in sources
        assert ("MomOsc", "bullish") in types

    def test_indicators_dict_still_populated(self) -> None:
        """Even with merge on, raw RSI + Stoch values are still
        recorded so the UI / debug paths can inspect them."""
        result = technical.analyze(_oversold_bars(), _cfg(True))
        assert "rsi" in result["indicators"]
        assert "stoch_k" in result["indicators"]
        assert "stoch_d" in result["indicators"]

    def test_score_stays_in_valid_band(self) -> None:
        """Sanity check on the full composite — both modes should
        produce scores in [0, 100]. Direction can vary because the
        full technical composite includes 5+ other indicators
        (MAs, Bollinger, volume, Clenow) that aren't part of this
        change."""
        legacy = technical.analyze(_oversold_bars(), _cfg(False))["score"]
        merged = technical.analyze(_oversold_bars(), _cfg(True))["score"]
        assert 0 <= legacy <= 100
        assert 0 <= merged <= 100


class TestMergedHelperDirectly:
    """Targeted tests on ``_calc_rsi_stoch_merged`` itself so we don't
    have to fight the full technical composite for signal coverage."""

    def _close(self, values: list[float]) -> pd.Series:
        idx = pd.date_range("2024-01-01", periods=len(values), freq="B")
        return pd.Series(values, index=idx, name="Close")

    def _ohlcv(self, closes: list[float]) -> tuple[pd.Series, pd.Series, pd.Series]:
        c = self._close(closes)
        return c * 1.005, c * 0.995, c

    def test_emits_bearish_on_overbought_overbought(self) -> None:
        """A zig-zag rally — every up move is larger than each
        intervening pullback, so the net trend is strongly up and RSI
        lands well above 70, but the pullbacks keep avg_loss > 0 so
        RSI doesn't degenerate to NaN (the project's RSI returns NaN
        when avg_loss = 0)."""
        n = 200
        closes = [50.0]
        for i in range(n - 1):
            # +1.5 up bars / -0.5 down bars pattern: every 2-bar cycle
            # nets +1.0; loss is always > 0, gain dominates.
            closes.append(closes[-1] + (1.5 if i % 2 == 0 else -0.5))
        high, low, close = self._ohlcv(closes)
        indicators: dict = {}
        signals: list = []
        cfg = _cfg(True)
        score = technical._calc_rsi_stoch_merged(
            close, high, low, cfg, indicators, signals,
        )
        assert score is not None
        # RSI on this curve hits >= 70 and Stoch K hits >= 80 — both
        # bearish. Merged signal must fire bearish exactly once.
        bearish = [s for s in signals if s["source"] == "MomOsc" and s["type"] == "bearish"]
        assert len(bearish) == 1

    def test_no_signal_when_indicators_disagree(self) -> None:
        """A gentle climb where neither hits oversold nor overbought —
        no merged signal should be emitted."""
        closes = list(np.linspace(50.0, 60.0, 200))
        high, low, close = self._ohlcv(closes)
        indicators: dict = {}
        signals: list = []
        score = technical._calc_rsi_stoch_merged(
            close, high, low, _cfg(True), indicators, signals,
        )
        assert score is not None
        assert not any(s["source"] == "MomOsc" for s in signals)

    def test_returns_none_when_history_too_short(self) -> None:
        closes = [50.0] * 5  # well under RSI period
        high, low, close = self._ohlcv(closes)
        score = technical._calc_rsi_stoch_merged(
            close, high, low, _cfg(True), {}, [],
        )
        assert score is None
