"""AnalyzerStatus contract on the composite scorer.

Covers Tier-1 audit finding X#1/X#2/X#4/X#5/X#17/X#18/T#10: the engine
used to substitute a neutral 50 for any analyzer that returned an empty
dict or a None score. A totally broken alpha158 or fundamentals module
therefore contributed exactly 50 to every composite and silently never
harmed a score.

After the fix:
  * each slot gets a status (ok / disabled / error) on the result
  * "error" slots are EXCLUDED from the weighted denominator (no silent 50)
  * "disabled" slots (optional analyzer not invoked) are excluded too
  * the result surfaces analyzer_status, error_count, error_slots,
    score_valid for downstream gates and dashboards
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from src.scoring.engine import (
    _SLOT_SPECS,
    _infer_status,
    batch_score,
    calculate_composite_score,
)


_STRATEGY = {
    "weights": {
        "technical": 0.30,
        "fundamental": 0.25,
        "pattern": 0.15,
        "statistical": 0.20,
        "trend": 0.10,
    }
}


def _ok(score: float, signals: list[dict] | None = None) -> dict[str, Any]:
    return {"score": score, "signals": signals or []}


# --- _infer_status ---------------------------------------------------------


def test_infer_status_ok_when_score_numeric():
    assert _infer_status({"score": 75}, required=True) == "ok"
    assert _infer_status({"score": 0.0}, required=True) == "ok"


def test_infer_status_error_when_dict_empty():
    assert _infer_status({}, required=True) == "error"


def test_infer_status_error_when_score_missing():
    assert _infer_status({"signals": []}, required=True) == "error"


def test_infer_status_error_when_score_non_numeric():
    assert _infer_status({"score": "huh"}, required=True) == "error"


def test_infer_status_error_when_explicit_error_field():
    """Analyzers that early-exit with {'score': 50, 'error': '...'} must
    not be counted as 'ok' — that was the alpha158 silent-50 pattern."""
    assert _infer_status({"score": 50, "error": "boom"}, required=False) == "error"


def test_infer_status_disabled_for_optional_when_none():
    assert _infer_status(None, required=False) == "disabled"


def test_infer_status_error_for_required_when_none():
    assert _infer_status(None, required=True) == "error"


# --- calculate_composite_score ---------------------------------------------


def test_clean_pass_status_all_ok():
    result = calculate_composite_score(
        _ok(80), _ok(60), _ok(70), _ok(75), _ok(65),
        strategy_config=_STRATEGY,
    )
    assert all(s == "ok" for s in result["analyzer_status"].values()
               if s != "disabled")
    assert result["error_count"] == 0
    assert result["error_slots"] == []
    assert result["score_valid"] is True


def test_broken_analyzer_excluded_from_denominator_not_substituted_with_50():
    """The keystone assertion. If technical is broken, the composite must
    be the weighted avg of the OTHER four — not (50 + others) / 5."""
    broken = {}  # no score → error
    result = calculate_composite_score(
        broken, _ok(80), _ok(80), _ok(80), _ok(80),
        strategy_config=_STRATEGY,
    )
    # Other 4 weights sum to 0.70; renormalized average should be 80,
    # NOT (50*.30 + 80*.70) = 71.0 (the old silent-50 fallback).
    # Account for the consensus signal adjustment (0 signals → no shift).
    assert result["analyzer_status"]["technical"] == "error"
    assert result["error_count"] == 1
    assert "technical" in result["error_slots"]
    assert result["composite_score"] == pytest.approx(80.0, abs=0.01)
    assert result["score_valid"] is True


def test_optional_analyzer_none_is_disabled_not_error():
    result = calculate_composite_score(
        _ok(80), _ok(80), _ok(80), _ok(80), _ok(80),
        strategy_config=_STRATEGY,
        alpha158_result=None,
    )
    assert result["analyzer_status"]["alpha158"] == "disabled"
    assert result["error_count"] == 0


def test_optional_analyzer_with_explicit_error_counts():
    """Optional analyzers that ran and crashed must still bump error_count."""
    result = calculate_composite_score(
        _ok(80), _ok(80), _ok(80), _ok(80), _ok(80),
        strategy_config=_STRATEGY,
        alpha158_result={"score": 50, "error": "ill-conditioned matrix"},
    )
    assert result["analyzer_status"]["alpha158"] == "error"
    assert result["error_count"] == 1
    assert "alpha158" in result["error_slots"]


def test_all_required_errored_returns_score_invalid():
    """If every required slot crashes there's nothing real to compose; the
    engine falls back to 50 but flags score_valid=False so downstream gates
    can refuse the trade."""
    bad = {}
    result = calculate_composite_score(
        bad, bad, bad, bad, bad,
        strategy_config=_STRATEGY,
    )
    assert result["score_valid"] is False
    assert result["error_count"] == 5
    # All five required slots flagged.
    for slot in ("technical", "fundamental", "pattern", "statistical", "trend"):
        assert result["analyzer_status"][slot] == "error"


def test_signals_from_error_slot_excluded_from_consensus():
    """A broken analyzer's leftover signals must not skew the bullish/
    bearish ±5 consensus adjustment."""
    broken_with_signals = {
        "score": None,  # → error
        "signals": [
            {"type": "bullish"}, {"type": "bullish"}, {"type": "bullish"},
        ],
    }
    result = calculate_composite_score(
        broken_with_signals, _ok(50), _ok(50), _ok(50), _ok(50),
        strategy_config=_STRATEGY,
    )
    # Without the fix, three phantom bullish signals would pull composite
    # to 50 + 5 = 55. With the fix, only "ok" slots' signals count, so
    # consensus adjustment is 0.
    assert result["composite_score"] == pytest.approx(50.0, abs=0.01)
    assert result["bullish_signals"] == 0


def test_breakdown_includes_error_rows_with_status():
    """Operators need to SEE why a score looks off. Error slots stay in
    the breakdown with status="error" and score=None."""
    result = calculate_composite_score(
        {}, _ok(80), _ok(80), _ok(80), _ok(80),
        strategy_config=_STRATEGY,
    )
    error_rows = [r for r in result["breakdown"] if r["status"] == "error"]
    assert len(error_rows) == 1
    assert error_rows[0]["category"] == "Technical"
    assert error_rows[0]["score"] is None


# --- batch_score sentinel -------------------------------------------------


def test_batch_score_emits_sentinel_on_engine_crash():
    """Tickers whose composite calculation explodes must NOT disappear
    silently — the old behavior caused len(input) != len(scored) drift
    with no visibility."""

    # Build a result dict that triggers an exception inside the engine.
    # The simplest path: pass a `pead_result` whose composite_bonus is
    # an object the engine can't handle even via the safe-cast path.
    # Easier: monkey-patch calculate_composite_score to raise for a
    # specific ticker.

    from src.scoring import engine as engine_mod

    original = engine_mod.calculate_composite_score

    def bomb_for_aapl(*args, **kwargs):
        if kwargs.get("technical_result", {}).get("_ticker") == "AAPL":
            raise RuntimeError("synthetic explosion")
        return original(*args, **kwargs)

    engine_mod.calculate_composite_score = bomb_for_aapl
    try:
        results = batch_score(
            {
                "AAPL": {
                    "technical": {"score": 80, "_ticker": "AAPL"},
                    "fundamental": _ok(70),
                    "pattern": _ok(70),
                    "statistical": _ok(70),
                    "trend": _ok(70),
                },
                "MSFT": {
                    "technical": _ok(85),
                    "fundamental": _ok(85),
                    "pattern": _ok(85),
                    "statistical": _ok(85),
                    "trend": _ok(85),
                },
            },
            _STRATEGY,
        )
    finally:
        engine_mod.calculate_composite_score = original

    by_ticker = {t: r for t, r in results}
    assert set(by_ticker) == {"AAPL", "MSFT"}
    aapl = by_ticker["AAPL"]
    assert aapl["error_count"] == 999
    assert aapl["score_valid"] is False
    assert "scoring_engine_error" in aapl
    assert by_ticker["MSFT"]["error_count"] == 0
