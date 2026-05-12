"""Recommender unit tests.

Two surfaces:
  - ``_determine_action`` is a pure function over (score, thresholds).
    Cheap to test exhaustively at boundaries.
  - ``_build_reasoning`` aggregates signals + sub-scores into a list of
    strings — also pure.

The full ``generate_recommendation`` is integration-y (needs price
data, fundamentals, config). Covered indirectly via existing scan-
path tests.
"""

from __future__ import annotations

import pytest

import numpy as np
import pandas as pd

from src.scoring.recommender import (
    _build_reasoning,
    _calculate_stop_loss,
    _calculate_take_profit,
    _determine_action,
)


@pytest.fixture
def thresholds() -> dict[str, float]:
    return {
        "strong_buy": 80.0,
        "buy": 65.0,
        "hold_upper": 50.0,
        "hold_lower": 35.0,
        "sell": 20.0,
    }


class TestDetermineAction:
    @pytest.mark.parametrize(
        "score,expected_action,expected_conf",
        [
            (95.0, "STRONG BUY", "High"),
            (80.0, "STRONG BUY", "High"),    # boundary, inclusive
            (79.99, "BUY", "Medium-High"),   # just below
            (65.0, "BUY", "Medium-High"),    # boundary
            (64.99, "HOLD", "Medium"),
            (50.0, "HOLD", "Medium"),        # hold_upper boundary
            (49.99, "HOLD", "Low"),
            (35.0, "HOLD", "Low"),           # hold_lower boundary
            (34.99, "SELL", "Medium-High"),
            (20.0, "SELL", "Medium-High"),
            (19.99, "STRONG SELL", "High"),
            (0.0, "STRONG SELL", "High"),
        ],
    )
    def test_boundaries(
        self, score: float, expected_action: str, expected_conf: str,
        thresholds: dict[str, float],
    ) -> None:
        action, confidence = _determine_action(score, thresholds)
        assert action == expected_action
        assert confidence == expected_conf

    def test_uses_defaults_when_thresholds_missing_keys(self) -> None:
        """``_determine_action`` falls back to hardcoded defaults if the
        strategy's thresholds dict is partial. Stops a half-configured
        strategy from silently mis-classifying."""
        action, _ = _determine_action(85.0, {})
        assert action == "STRONG BUY"
        action, _ = _determine_action(15.0, {})
        assert action == "STRONG SELL"


class TestBuildReasoning:
    def _result(self, **overrides) -> dict:
        return {
            "all_signals": [],
            "sub_scores": {},
            **overrides,
        }

    def test_picks_top_bullish_then_bearish(self) -> None:
        signals = [
            {"type": "bullish", "source": "RSI", "detail": "oversold"},
            {"type": "bullish", "source": "MACD", "detail": "cross"},
            {"type": "bearish", "source": "VOL", "detail": "low volume"},
        ]
        result = self._result(all_signals=signals)
        reasons = _build_reasoning(result, fundamentals={})
        assert reasons[0].startswith("+ RSI:")
        assert reasons[1].startswith("+ MACD:")
        assert any(r.startswith("- VOL:") for r in reasons)

    def test_caps_at_five_of_each_type(self) -> None:
        signals = [
            {"type": "bullish", "source": f"S{i}", "detail": f"d{i}"}
            for i in range(10)
        ]
        result = self._result(all_signals=signals)
        reasons = _build_reasoning(result, fundamentals={})
        bullish_reasons = [r for r in reasons if r.startswith("+ ")]
        assert len(bullish_reasons) == 5

    def test_surfaces_strongest_and_weakest_sub_scores(self) -> None:
        result = self._result(
            sub_scores={"technical": 80.0, "fundamental": 30.0, "trend": 50.0}
        )
        reasons = _build_reasoning(result, fundamentals={})
        assert any("Strongest: Technical" in r for r in reasons)
        assert any("Weakest: Fundamental" in r for r in reasons)

    def test_skips_weakest_when_only_one_sub_score(self) -> None:
        """Strongest == weakest when there's a single sub-score — the
        function should not emit a duplicate line."""
        result = self._result(sub_scores={"technical": 60.0})
        reasons = _build_reasoning(result, fundamentals={})
        strongest = [r for r in reasons if r.startswith("Strongest:")]
        weakest = [r for r in reasons if r.startswith("Weakest:")]
        assert len(strongest) == 1
        assert len(weakest) == 0


def _trend_prices(n: int = 30) -> pd.DataFrame:
    """30 bars of clean uptrend with ~1.5% daily range — enough for an
    ATR-based stop calc to produce a sensible number."""
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    base = np.linspace(100.0, 110.0, n)
    return pd.DataFrame(
        {
            "Open": base,
            "High": base * 1.015,
            "Low": base * 0.985,
            "Close": base,
            "Volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


class TestStopLoss:
    def test_atr_method_returns_price_below_current(self) -> None:
        prices = _trend_prices()
        current = float(prices["Close"].iloc[-1])
        result = _calculate_stop_loss(prices, current, {"method": "atr", "atr_multiplier": 2.0})
        assert result["method"] == "atr"
        assert result["price"] < current
        # ATR(2x) on a ~1.5% range trend → stop maybe 3-5% below.
        assert result["pct_from_current"] < 0

    def test_percentage_method_uses_fixed_offset(self) -> None:
        result = _calculate_stop_loss(
            _trend_prices(), current_price=100.0,
            sl_config={"method": "percentage", "percentage": 5.0},
        )
        assert result["price"] == 95.0
        assert result["pct_from_current"] == -5.0
        assert "Fixed 5.0%" in result["detail"]


class TestTakeProfit:
    def test_risk_reward_method_scales_by_ratio(self) -> None:
        """3:1 R:R with a $5 stop distance → $15 reward above entry."""
        current = 100.0
        sl = {"price": 95.0}
        result = _calculate_take_profit(
            _trend_prices(), current, sl,
            tp_config={"method": "risk_reward", "risk_reward_ratio": 3.0},
        )
        assert result["price"] == 115.0
        assert result["pct_from_current"] == 15.0
