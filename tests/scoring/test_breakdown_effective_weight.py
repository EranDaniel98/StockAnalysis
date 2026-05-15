"""Reviewer I6 regression: ScoreBreakdownRow.effective_weight is the
post-renormalization share so operators reading the breakdown for a
stress investigation don't get misled by stale nominal weights.

Pre-fix, an error scenario produced rows like:
    technical 30%  ok    contribution 18.0   <-- nominal weight, but
    fundamental 25%  err   contribution  0.0       this row contributes
                                                   18/composite, not
                                                   18% of an absolute base
    ...

Reading those nominal weights would make the operator believe the
remaining 70% summed to the composite — they don't, the surviving
slots renormalize against each other.
"""

from __future__ import annotations

from src.scoring.engine import calculate_composite_score


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


def test_breakdown_effective_weight_all_ok_sums_to_one():
    """All five required slots ok → effective_weights sum to 1.0
    (and equal nominal weights since no renormalization happened)."""
    ok = {"score": 60.0, "signals": []}
    result = calculate_composite_score(
        technical_result=ok,
        fundamental_result=ok,
        pattern_result=ok,
        statistical_result=ok,
        trend_result=ok,
        strategy_config=_strategy_cfg(),
    )
    ok_rows = [r for r in result["breakdown"] if r["status"] == "ok"]
    assert len(ok_rows) == 5
    total_effective = sum(r["effective_weight"] for r in ok_rows)
    assert abs(total_effective - 1.0) < 1e-9

    # Each effective_weight equals the nominal weight (no renormalization).
    for row in ok_rows:
        nominal = float(row["weight"].rstrip("%")) / 100.0
        assert abs(row["effective_weight"] - nominal) < 1e-9


def test_breakdown_effective_weight_renormalizes_when_slots_error():
    """One slot errors → the four surviving slots' effective_weights
    must sum to 1.0 (renormalized) even though their nominal weights
    sum to 0.70."""
    ok = {"score": 60.0, "signals": []}
    err = {"score": None, "error": "no data"}
    result = calculate_composite_score(
        technical_result=ok,            # nominal 0.30
        fundamental_result=err,         # nominal 0.25, dropped
        pattern_result=ok,              # nominal 0.15
        statistical_result=ok,          # nominal 0.20
        trend_result=ok,                # nominal 0.10
        strategy_config=_strategy_cfg(),
    )
    ok_rows = [r for r in result["breakdown"] if r["status"] == "ok"]
    err_rows = [r for r in result["breakdown"] if r["status"] == "error"]
    assert len(ok_rows) == 4
    assert len(err_rows) == 1

    total_effective = sum(r["effective_weight"] for r in ok_rows)
    assert abs(total_effective - 1.0) < 1e-9

    # Effective weights are NOT equal to nominal (renormalized against 0.75).
    technical_row = next(r for r in ok_rows if r["category"] == "Technical")
    assert abs(technical_row["effective_weight"] - (0.30 / 0.75)) < 1e-9

    # Error rows carry effective_weight=None (they contributed nothing).
    assert err_rows[0]["effective_weight"] is None


def test_breakdown_contributions_sum_to_composite():
    """Math sanity: regardless of whether slots errored, the
    contributions on ok rows sum to the composite. This guards against
    a refactor breaking the relationship between effective_weight and
    contribution."""
    ok = {"score": 60.0, "signals": []}
    err = {"score": None, "error": "no data"}
    result = calculate_composite_score(
        technical_result=ok,
        fundamental_result=err,
        pattern_result=ok,
        statistical_result=ok,
        trend_result=ok,
        strategy_config=_strategy_cfg(),
    )
    ok_rows = [r for r in result["breakdown"] if r["status"] == "ok"]
    total_contribution = sum(r["contribution"] for r in ok_rows)
    # Rounding floor: contributions rounded to 1 dp, composite to 2 dp.
    assert abs(total_contribution - result["composite_score"]) < 0.5
