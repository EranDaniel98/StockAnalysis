"""B1 + B2 regression: silent-50 gate is wired end-to-end.

The silent-50 fix (commit 9345a74) gave the engine the ability to
report `score_valid=False` when all required analyzers errored. But
reviewer found that:

* B1 — no downstream consumer refused on score_valid: paper-trade and
  backtest entry gates only looked at composite/action.
* B2 — PEAD bonus, Carver consensus scaling, and signal-consensus ±5
  applied even when score_valid=False, so a fully-broken pipeline's
  50.0 placeholder could be lifted to a BUY threshold (~65).
* I4 — Recommendation.legacy_dict() didn't propagate score_valid /
  error_count, so the legacy-dict surface couldn't be gated either.

This file pins the closure end-to-end:
  * engine doesn't apply post-composite lifts when score_valid=False
  * recommender forces HOLD/Low when score_valid=False
  * recommender legacy dict carries the validity fields
  * Recommendation.legacy_dict() preserves them
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.scoring.engine import calculate_composite_score
from src.scoring.recommender import generate_recommendation


# --- Engine layer (B2): post-composite lifts only when score_valid ---


def _broken_chain(_n_signals=2):
    """Build sub-results that all error so score_valid flips False."""
    errored = {"error": "No data", "score": None}
    return {
        "technical_result": errored,
        "fundamental_result": errored,
        "pattern_result": errored,
        "statistical_result": errored,
        "trend_result": errored,
    }


def _strategy_cfg():
    return {
        "weights": {
            "technical": 0.30,
            "fundamental": 0.25,
            "pattern": 0.15,
            "statistical": 0.20,
            "trend": 0.10,
        },
    }


def test_engine_score_invalid_when_all_required_error():
    """All five required analyzers error → score_valid False, composite=50."""
    result = calculate_composite_score(
        **_broken_chain(),
        strategy_config=_strategy_cfg(),
    )
    assert result["score_valid"] is False
    assert result["composite_score"] == 50.0
    assert result["error_count"] == 5


def test_engine_pead_bonus_does_not_lift_broken_chain():
    """B2 keystone: a +15 PEAD bonus over a 50.0 placeholder must NOT
    push composite to 65 (BUY threshold) when score_valid=False."""
    pead = {"composite_bonus": 15.0, "signals": []}
    result = calculate_composite_score(
        **_broken_chain(),
        strategy_config=_strategy_cfg(),
        pead_result=pead,
    )
    assert result["score_valid"] is False
    assert result["composite_score"] == 50.0  # NOT 65


def test_engine_signal_consensus_does_not_lift_broken_chain():
    """All bullish signals + broken chain: ±5 adjustment must be
    skipped. Composite stays at 50."""
    bullish_signal = {"type": "bullish", "source": "x", "detail": ""}
    technical = {
        "score": None,
        "error": "no data",
        "signals": [bullish_signal, bullish_signal, bullish_signal],
    }
    result = calculate_composite_score(
        technical_result=technical,
        fundamental_result={"error": "x", "score": None},
        pattern_result={"error": "x", "score": None},
        statistical_result={"error": "x", "score": None},
        trend_result={"error": "x", "score": None},
        strategy_config=_strategy_cfg(),
    )
    # Signals from error slots are excluded from all_signals (engine
    # guard from 9345a74), so this test also confirms the engine doesn't
    # collect signals from error slots in the first place.
    assert result["composite_score"] == 50.0
    assert result["score_valid"] is False


def test_engine_score_valid_preserves_pead_lift():
    """Sanity: when score IS valid, PEAD bonus still applies. We didn't
    accidentally disable it for healthy pipelines."""
    ok = {"score": 60.0, "signals": []}
    pead = {"composite_bonus": 5.0, "signals": []}
    result = calculate_composite_score(
        technical_result=ok,
        fundamental_result=ok,
        pattern_result=ok,
        statistical_result=ok,
        trend_result=ok,
        strategy_config=_strategy_cfg(),
        pead_result=pead,
    )
    assert result["score_valid"] is True
    assert result["composite_score"] == pytest.approx(65.0)


# --- Recommender layer (B1): legacy dict carries score_valid + forces HOLD ---


def _config_stub():
    cfg = MagicMock()
    cfg.get_scoring_thresholds = MagicMock(return_value={
        "strong_buy": 80, "buy": 65, "hold_upper": 50,
        "hold_lower": 35, "sell": 20,
    })
    return cfg


def test_recommender_forces_hold_when_score_invalid():
    """B1: even if composite happens to be at a BUY threshold value
    (it shouldn't with engine fix, but defence-in-depth), the recommender
    overrides action → HOLD when score_valid is False."""
    score_result = {
        "composite_score": 70.0,  # would normally be BUY
        "score_valid": False,
        "error_count": 5,
        "error_slots": ["technical", "fundamental", "pattern", "statistical", "trend"],
        "sub_scores": {},
        "breakdown": [],
        "all_signals": [],
        "bullish_signals": 0,
        "bearish_signals": 0,
    }
    rec = generate_recommendation(
        ticker="FOO",
        score_result=score_result,
        price_data=None,
        fundamentals={"name": "Foo Co", "sector": "Tech"},
        config=_config_stub(),
        strategy=None,
    )
    assert rec["action"] == "HOLD"
    assert rec["confidence"] == "Low"
    assert rec["score_valid"] is False
    assert rec["error_count"] == 5
    assert rec["error_slots"] == [
        "technical", "fundamental", "pattern", "statistical", "trend",
    ]


def test_recommender_passes_through_score_valid_true():
    """Healthy path: score_valid=True → normal action mapping."""
    score_result = {
        "composite_score": 70.0,
        "score_valid": True,
        "error_count": 0,
        "error_slots": [],
        "sub_scores": {"technical": 70.0},
        "breakdown": [],
        "all_signals": [],
        "bullish_signals": 0,
        "bearish_signals": 0,
    }
    rec = generate_recommendation(
        ticker="FOO",
        score_result=score_result,
        price_data=None,
        fundamentals=None,
        config=_config_stub(),
        strategy=None,
    )
    assert rec["action"] == "BUY"
    assert rec["score_valid"] is True


# --- Contract layer (I4): Recommendation.legacy_dict() carries validity ---


def test_recommendation_legacy_dict_includes_score_valid_fields():
    """I4: legacy_dict must surface score_valid / error_count / error_slots
    so legacy-dict consumers (paper_trade_service) can gate on them."""
    from src.contracts.entities.recommendation import Recommendation

    rec = Recommendation(
        ticker="FOO",
        action="HOLD",
        composite_score=50.0,
        confidence="Low",
        score_valid=False,
        error_count=5,
        error_slots=("technical", "fundamental", "pattern", "statistical", "trend"),
    )
    legacy = rec.legacy_dict()
    assert legacy["score_valid"] is False
    assert legacy["error_count"] == 5
    assert legacy["error_slots"] == [
        "technical", "fundamental", "pattern", "statistical", "trend",
    ]


def test_recommendation_legacy_dict_defaults_when_constructed_minimally():
    """Backwards-compat: a Recommendation constructed without explicit
    validity fields (legacy callers) defaults to score_valid=True."""
    from src.contracts.entities.recommendation import Recommendation

    rec = Recommendation(
        ticker="FOO",
        action="BUY",
        composite_score=70.0,
        confidence="Medium-High",
    )
    legacy = rec.legacy_dict()
    assert legacy["score_valid"] is True
    assert legacy["error_count"] == 0
    assert legacy["error_slots"] == []


def test_recommendation_legacy_dict_empty_risk_management_safe():
    """I3: when risk_management is constructed but stop_loss/take_profit
    are None, legacy_dict emits {} not None so paper_trade_service's
    ``.get("stop_loss", {}).get("price")`` chain stays safe."""
    from src.contracts.entities.recommendation import Recommendation, RiskManagement

    rm = RiskManagement(current_price=100.0)  # both stop_loss and take_profit default None
    rec = Recommendation(
        ticker="FOO",
        action="BUY",
        composite_score=70.0,
        confidence="Medium-High",
        risk_management=rm,
    )
    legacy = rec.legacy_dict()
    # The keystone: the chain must not raise AttributeError on a None.
    assert legacy["risk_management"]["stop_loss"] == {}
    assert legacy["risk_management"]["take_profit"] == {}
    # And the qualified-list comprehension's price extraction returns
    # None (falsey) rather than crashing.
    assert legacy["risk_management"]["stop_loss"].get("price") is None
