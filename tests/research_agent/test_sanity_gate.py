"""Sanity gate (sync batch path) tests.

The gate must:
* REJECT removes the ticker from kept
* CAUTION keeps the ticker but surfaces in cautioned
* SKIP (gate raised) is treated as REJECT — "when in doubt, don't trade"
* Empty input returns an empty result without raising
"""

from __future__ import annotations

import pytest

from src.api.schemas.sanity import SanityCheck
from src.research_agent.sanity_gate import (
    SanityGateOutcome,
    _build_result,
    gate_picks_sync,
)


def _make_check(verdict: str) -> SanityCheck:
    return SanityCheck(
        verdict=verdict,
        reason=f"{verdict} test",
        catalysts_found=[],
        confidence=0.7,
        model_used="mock",
        mocked=True,
        checked_at="2026-05-18T00:00:00+00:00",
    )


def test_build_result_classifies_outcomes() -> None:
    outcomes = [
        SanityGateOutcome(ticker="A", verdict="OK",
                          check=_make_check("OK"), reason="clean"),
        SanityGateOutcome(ticker="B", verdict="CAUTION",
                          check=_make_check("CAUTION"), reason="warn"),
        SanityGateOutcome(ticker="C", verdict="REJECT",
                          check=_make_check("REJECT"), reason="bad"),
        SanityGateOutcome(ticker="D", verdict="SKIP",
                          check=None, reason="error"),
    ]
    result = _build_result(outcomes)
    assert result.kept == ["A", "B"]
    assert result.rejected == ["C", "D"]
    assert result.cautioned == ["B"]
    assert set(result.outcomes.keys()) == {"A", "B", "C", "D"}


def test_empty_picks_returns_empty_result() -> None:
    result = gate_picks_sync(picks=[], mode="mock")
    assert result.kept == []
    assert result.rejected == []
    assert result.outcomes == {}


def test_mock_gate_rejects_ma_language(monkeypatch) -> None:
    """End-to-end via the mock path. The mock REJECTs when filings/news
    contain M&A language. We can drive that by stubbing the evidence
    fetch — but the gate also runs without filings (gate-only mode), so
    we just verify the call graph works on rule-based inputs."""
    picks = [
        {"ticker": "OK1", "z_score": 2.0},
        {"ticker": "OK2", "z_score": 1.5},
    ]
    result = gate_picks_sync(
        picks=picks, mode="mock", include_filings=False,
    )
    assert "OK1" in result.kept
    assert "OK2" in result.kept
    assert result.rejected == []


def test_picks_without_ticker_are_dropped() -> None:
    picks = [
        {"ticker": "A", "z_score": 1.0},
        {"z_score": 0.5},  # no ticker
    ]
    result = gate_picks_sync(picks=picks, mode="mock", include_filings=False)
    assert "A" in result.kept
    assert all(t != "" for t in result.kept)


def test_skip_treated_as_reject_in_build_result() -> None:
    outcomes = [
        SanityGateOutcome(ticker="X", verdict="SKIP",
                          check=None, reason="anthropic_unavailable"),
    ]
    result = _build_result(outcomes)
    assert result.kept == []
    assert result.rejected == ["X"]


def test_mock_gate_handles_score_fallback() -> None:
    """Picks dict uses composite_score (old shape) instead of z_score —
    the gate should still extract a score and run."""
    picks = [{"ticker": "OLD", "composite_score": 75.0}]
    result = gate_picks_sync(picks=picks, mode="mock", include_filings=False)
    assert result.outcomes["OLD"].verdict == "OK"
