"""Tests for catalyst_result wiring in src.scoring.engine.

The composite engine accepts catalyst_result alongside the other
optional sub-scores (alpha158, pead, rel_strength, insider_flow).
This module pins:
  * sub_scores includes catalyst when provided, omits it when None
  * signals from catalyst contribute to the bullish/bearish consensus
  * breakdown surfaces catalyst when it's part of the weighted average
  * passing catalyst_result=None is a no-op (preserves legacy behavior)
"""

from __future__ import annotations

import pytest

from src.scoring.engine import calculate_composite_score


# Minimal analyzer-shape dict factory — every analyzer returns this
# shape; tests only need a score + signals to verify the composite math.
def _analyzer(score: float, signals: list[dict] | None = None) -> dict:
    return {"score": score, "signals": signals or []}


def _base_kwargs() -> dict:
    """Five mandatory analyzer results at neutral 50 + a strategy
    config that weights them equally for an easy-to-reason composite.
    """
    return {
        "technical_result": _analyzer(50),
        "fundamental_result": _analyzer(50),
        "pattern_result": _analyzer(50),
        "statistical_result": _analyzer(50),
        "trend_result": _analyzer(50),
        "strategy_config": {
            "weights": {
                "technical": 0.20,
                "fundamental": 0.20,
                "pattern": 0.20,
                "statistical": 0.20,
                "trend": 0.20,
            },
        },
    }


class TestCatalystOmittedDefault:
    def test_no_catalyst_result_keeps_sub_scores_unchanged(self) -> None:
        """Legacy behavior: callers that don't pass catalyst_result
        get the same sub_scores dict as before the feature was wired."""
        result = calculate_composite_score(**_base_kwargs())
        assert "catalyst" not in result["sub_scores"]
        assert "Catalyst" not in {row["category"] for row in result["breakdown"]}

    def test_explicit_none_is_no_op(self) -> None:
        result = calculate_composite_score(**_base_kwargs(), catalyst_result=None)
        assert "catalyst" not in result["sub_scores"]


class TestCatalystIncluded:
    def test_score_appears_in_sub_scores(self) -> None:
        catalyst = _analyzer(70, signals=[
            {"type": "bullish", "source": "Catalyst",
             "detail": "buyback authorization (sim=0.55, 8-K 3d ago)"},
        ])
        result = calculate_composite_score(
            **_base_kwargs(), catalyst_result=catalyst
        )
        assert result["sub_scores"]["catalyst"] == 70
        # Catalyst row in breakdown — capitalized category label
        cats = [row["category"] for row in result["breakdown"]]
        assert "Catalyst" in cats

    def test_bullish_signal_propagates_into_consensus(self) -> None:
        """The composite's signal-consensus adjustment (±5 points
        based on bullish-vs-bearish ratio) must see catalyst signals.
        """
        catalyst = _analyzer(70, signals=[
            {"type": "bullish", "source": "Catalyst", "detail": "buyback"},
        ])
        result = calculate_composite_score(
            **_base_kwargs(), catalyst_result=catalyst
        )
        assert result["bullish_signals"] == 1
        assert result["bearish_signals"] == 0

    def test_bearish_signal_propagates(self) -> None:
        catalyst = _analyzer(35, signals=[
            {"type": "bearish", "source": "Catalyst", "detail": "going concern"},
        ])
        result = calculate_composite_score(
            **_base_kwargs(), catalyst_result=catalyst
        )
        assert result["bearish_signals"] == 1
        assert result["bullish_signals"] == 0

    def test_catalyst_score_pulls_composite_when_weighted(self) -> None:
        """Add a catalyst weight to the strategy; a 100 catalyst with
        a 0.2 weight should pull the composite measurably above the
        neutral baseline.
        """
        kwargs = _base_kwargs()
        # Bring catalyst into the weight set; re-normalize down the
        # original five to make room (each was 0.20 → 0.16, plus 0.20
        # for catalyst).
        kwargs["strategy_config"]["weights"] = {
            "technical": 0.16,
            "fundamental": 0.16,
            "pattern": 0.16,
            "statistical": 0.16,
            "trend": 0.16,
            "catalyst": 0.20,
        }
        base = calculate_composite_score(**kwargs)
        with_cat = calculate_composite_score(
            **kwargs, catalyst_result=_analyzer(100),
        )
        # The weighted catalyst of 100 (vs the absent baseline default
        # of "no slot") should raise the composite. Both runs hit the
        # signal-consensus path identically (no signals from the
        # neutral analyzers) so the delta is purely from the weight.
        assert with_cat["composite_score"] > base["composite_score"]


class TestBatchScoreForwarding:
    def test_batch_score_passes_catalyst_through(self) -> None:
        """The batch_score wrapper must pass the catalyst entry from
        each ticker's results dict into calculate_composite_score —
        without that forwarding, the analyze_and_score pipeline (which
        produces analysis_results[ticker]['catalyst']) would silently
        drop the signal."""
        from src.scoring.engine import batch_score

        catalyst = _analyzer(75, signals=[
            {"type": "bullish", "source": "Catalyst", "detail": "guidance raised"},
        ])
        results = {
            "AAPL": {
                "technical": _analyzer(50),
                "fundamental": _analyzer(50),
                "pattern": _analyzer(50),
                "statistical": _analyzer(50),
                "trend": _analyzer(50),
                "catalyst": catalyst,
            },
        }
        scored = batch_score(results, {"weights": {"catalyst": 0.20}})
        assert len(scored) == 1
        _, score_result = scored[0]
        assert "catalyst" in score_result["sub_scores"]
        assert score_result["sub_scores"]["catalyst"] == 75
