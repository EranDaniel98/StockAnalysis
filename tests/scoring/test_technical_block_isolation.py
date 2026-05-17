"""Isolated unit tests for the technical analyzer's indicator blocks.

Post-2026-05-17 refactor: each ``_calc_*`` returns an ``IndicatorBlock``
instead of mutating caller buffers, so individual indicators can be
exercised without spinning up the full ``analyze()`` orchestrator or
constructing shared mutable state. These tests pin that property —
if a future refactor reintroduces mutation-by-reference, they break.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.config_loader import Config
from src.scoring.analyzers import technical


def _close(values: list[float]) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="B")
    return pd.Series(values, index=idx, name="Close")


def _ohlcv_from_close(c: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    return c * 1.005, c * 0.995, c


def test_blocks_are_independent_no_shared_state() -> None:
    """Two consecutive calls to the same helper produce structurally
    identical results — no caller buffer contamination."""
    # Mild noise so RSI has both gains and losses (a perfectly monotonic
    # series makes avg_loss=0 → NaN, and NaN != NaN even for equal frames).
    close = _close([100 + i * 0.1 + ((-1) ** i) * 0.5 for i in range(60)])
    a = technical._calc_rsi(close, Config())
    b = technical._calc_rsi(close, Config())
    assert a.indicators == b.indicators
    assert a.scores == b.scores
    assert a.signals == b.signals
    # Mutating one must not affect the other.
    a.signals.append({"type": "bullish", "source": "TEST"})
    assert "TEST" not in {s["source"] for s in b.signals}


def test_short_history_returns_empty_block() -> None:
    """Under-history → block with no scores/signals/indicators."""
    close = _close([100.0] * 5)
    block = technical._calc_rsi(close, Config())
    assert block.scores == []
    assert block.signals == []
    assert block.indicators == {}


def test_oversold_rsi_emits_bullish_signal_and_high_score() -> None:
    """A steep drop drives RSI deeply oversold → score > 70 + bullish signal."""
    closes = list(np.linspace(100.0, 50.0, 200))
    close = _close(closes)
    block = technical._calc_rsi(close, Config())
    assert block.scores, "expected one RSI score"
    assert block.scores[0] >= 70
    types = {s["type"] for s in block.signals if s["source"] == "RSI"}
    assert "bullish" in types


def test_macd_block_yields_one_score_and_three_indicators() -> None:
    """Sanity: MACD has 3 indicator outputs (line, signal, histogram)
    and contributes exactly one score to the composite."""
    close = _close([100 + i * 0.05 for i in range(60)])
    block = technical._calc_macd(close, Config())
    assert len(block.scores) == 1
    assert {"macd_line", "macd_signal", "macd_histogram"}.issubset(
        set(block.indicators)
    )


def test_atr_block_records_indicators_but_no_scores() -> None:
    """ATR is a risk-management input only — it must populate atr +
    atr_pct but never contribute to the technical composite score."""
    close = _close([100.0 + (i % 3) for i in range(60)])
    high, low, _ = _ohlcv_from_close(close)
    block = technical._calc_atr(high, low, close, Config())
    assert block.scores == []
    assert "atr" in block.indicators
    assert "atr_pct" in block.indicators


def test_moving_averages_emit_multi_score_per_period() -> None:
    """The SMA block returns one score per configured SMA period, plus
    a Golden/Death cross when applicable — the multi-score contract
    other helpers can rely on."""
    closes = list(np.linspace(100.0, 200.0, 250))  # smooth uptrend, no MA cross
    close = _close(closes)
    block = technical._calc_moving_averages(close, Config())
    # Default config has SMA periods [20, 50, 200] → 3 scores minimum.
    assert len(block.scores) >= 3
    # Indicators dict carries one SMA value per period.
    assert {"sma_20", "sma_50", "sma_200"}.issubset(set(block.indicators))


def test_clenow_block_score_is_in_band() -> None:
    """Whatever the regression input, score must be in [0, 100]."""
    for trend in (0.001, -0.001, 0.005, -0.005):
        closes = [100 * np.exp(trend * i) for i in range(120)]
        close = _close(closes)
        block = technical._calc_regression_slope_momentum(close, Config())
        if block.scores:
            assert 0 <= block.scores[0] <= 100
