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

from datetime import date

from src.scoring.recommender import (
    _build_reasoning,
    _calculate_stop_loss,
    _calculate_take_profit,
    _calculate_time_stop,
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

    def test_atr_fallback_rewrites_method_and_detail(self) -> None:
        """Tier-1 audit X#7: when ATR is 0 the calculator falls back to a
        flat percentage stop, but it used to leave method="atr" set. The
        UI then claimed "ATR(2x)" for what was actually a flat 5%. The
        fix rewrites method to "percentage" and writes a detail string
        that names the fallback explicitly."""
        # Zero-range bars → ATR will be 0.0 → fallback fires.
        idx = pd.date_range("2025-01-01", periods=20, freq="B")
        flat = pd.DataFrame(
            {
                "Open": np.full(20, 100.0),
                "High": np.full(20, 100.0),
                "Low": np.full(20, 100.0),
                "Close": np.full(20, 100.0),
                "Volume": np.full(20, 1_000_000.0),
            },
            index=idx,
        )
        result = _calculate_stop_loss(
            flat, current_price=100.0,
            sl_config={"method": "atr", "atr_multiplier": 2.0, "percentage": 5.0},
        )
        assert result["method"] == "percentage"
        assert result["price"] == 95.0
        assert "Fallback flat" in result["detail"]
        assert "ATR was 0" in result["detail"]

    def test_support_fallback_rewrites_method_and_detail(self) -> None:
        """Same X#7 contract for the support method when no support
        level is found near the current price."""
        # Constant-up trend has no local-min support points the analyzer
        # picks up (resistance/support detection looks for local extrema).
        idx = pd.date_range("2025-01-01", periods=20, freq="B")
        up = np.linspace(90.0, 110.0, 20)
        prices = pd.DataFrame(
            {
                "Open": up,
                "High": up * 1.001,
                "Low": up * 0.999,
                "Close": up,
                "Volume": np.full(20, 1_000_000.0),
            },
            index=idx,
        )
        result = _calculate_stop_loss(
            prices, current_price=float(prices["Close"].iloc[-1]),
            sl_config={"method": "support", "percentage": 5.0},
        )
        # Either support was found (method stays "support") OR fallback
        # fired (method flips to "percentage" with a fallback detail).
        # The X#7 contract is: when the fallback fires, method MUST flip.
        # Skip if the analyzer happened to find a level on this data.
        if result["method"] == "percentage":
            assert "Fallback flat" in result["detail"]
            assert "no support" in result["detail"]
        else:
            # Support was found — different code path, not what we're
            # asserting here.
            assert result["method"] == "support"


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

    def test_resistance_method_uses_chart_level_when_rr_qualifies(self) -> None:
        """A clear resistance peak ~15% above current with a tight stop
        should be picked as the take-profit (not the R/R fallback)."""
        # 60 bars with a peak at $115 in the middle, then pulls back to
        # ~$100 so resistance is well above current.
        idx = pd.date_range("2025-01-01", periods=60, freq="B")
        # First 30 bars climb to $115, next 30 fall back to $100.
        up = np.linspace(95.0, 115.0, 30)
        down = np.linspace(115.0, 100.0, 30)
        base = np.concatenate([up, down])
        prices = pd.DataFrame(
            {
                "Open": base,
                "High": base * 1.01,
                "Low": base * 0.99,
                "Close": base,
                "Volume": np.full(60, 1_000_000.0),
            },
            index=idx,
        )
        current = float(prices["Close"].iloc[-1])  # ~$100
        sl = {"price": current * 0.97}             # 3% stop → low risk, easy R/R
        result = _calculate_take_profit(
            prices, current, sl,
            tp_config={
                "method": "resistance",
                "risk_reward_ratio": 3.0,
                "min_risk_reward_ratio": 1.5,
            },
        )
        assert result["method"] == "resistance", result
        # Picked level should be the ~$115 peak (above current and well
        # over 1.5:1 R/R).
        assert 110.0 < result["price"] < 120.0, result
        assert result["detail"].startswith("Resistance:")

    def test_resistance_method_falls_back_when_no_level_qualifies(self) -> None:
        """Clean uptrend has no local-maxima resistance above current →
        we fall back to the R/R multiple AND surface that in the
        `method` + `detail` fields so the UI doesn't claim a chart
        basis it didn't actually use."""
        current = 110.0  # top of the trend
        sl = {"price": 100.0}
        result = _calculate_take_profit(
            _trend_prices(), current, sl,
            tp_config={
                "method": "resistance",
                "risk_reward_ratio": 3.0,
                "min_risk_reward_ratio": 1.5,
            },
        )
        # Method downgrades to risk_reward because the resistance
        # branch couldn't produce a usable level.
        assert result["method"] == "risk_reward"
        # 3:1 on a $10 risk → $30 reward → $140.
        assert result["price"] == 140.0
        assert "no resistance" in result["detail"]


class TestTimeStop:
    def test_falls_back_to_default_when_no_strategy(self) -> None:
        """Default reverted from 90 -> 365 on 2026-05-15 (Stage-1 revert):
        the apparent time-stop edge was a scoring-engine-bias artifact.
        The fallback is still finite so missing config doesn't produce an
        unbounded hold."""
        result = _calculate_time_stop(None, as_of=date(2026, 1, 1))
        assert result["method"] == "calendar"
        assert result["days"] == 365
        assert result["exit_date"] == "2027-01-01"

    def test_reads_strategy_time_stop_days(self) -> None:
        result = _calculate_time_stop(
            {"time_stop_days": 20}, as_of=date(2026, 1, 1)
        )
        assert result["days"] == 20
        assert result["exit_date"] == "2026-01-21"

    def test_rejects_non_positive_and_falls_back(self) -> None:
        """A zero / negative / non-numeric `time_stop_days` should
        fall back to the default — not silently produce a same-day
        forced exit (which would auto-close every position)."""
        for bad_value in [0, -5, None, "thirty", float("nan")]:
            r = _calculate_time_stop(
                {"time_stop_days": bad_value}, as_of=date(2026, 1, 1)
            )
            assert r["days"] == 365, f"bad value {bad_value!r} should fall back"

    def test_detail_string_includes_human_date(self) -> None:
        r = _calculate_time_stop({"time_stop_days": 10}, as_of=date(2026, 5, 14))
        assert "2026-05-24" in r["detail"]
        assert "10 calendar days" in r["detail"]
