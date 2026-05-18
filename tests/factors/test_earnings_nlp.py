"""Earnings-call NLP factor — scaffolding tests.

The LLM call path is exercised once a transcript provider lands. Here
we pin the score collapse + ranking math + parse fallbacks.
"""

from __future__ import annotations

import pytest

from src.factors.earnings_nlp import (
    EarningsCallSentiment,
    _parse_extraction,
    rank_sentiments,
    sentiment_to_factor_score,
)


def _s(**kw):
    """Build a sentiment with neutral defaults that tests override."""
    defaults = dict(ticker="AAA", call_date="2026-04-15")
    defaults.update(kw)
    return EarningsCallSentiment(**defaults)


def test_factor_score_bullish_with_raised_guide_is_high() -> None:
    s = _s(tone_label="bullish", tone_confidence=1.0,
           guidance_direction="raised", guidance_confidence=1.0,
           eps_surprise_pct=10.0)
    score = sentiment_to_factor_score(s)
    # 50 baseline + 15 tone + 25 guide + 10 surprise = 100, clamped.
    assert score == pytest.approx(100.0)


def test_factor_score_bearish_with_lowered_guide_is_low() -> None:
    s = _s(tone_label="bearish", tone_confidence=1.0,
           guidance_direction="lowered", guidance_confidence=1.0,
           qa_friction=0.5, eps_surprise_pct=-20.0)
    score = sentiment_to_factor_score(s)
    # 50 - 15 - 25 - 10 (friction*20) - 20 (surprise) = -20, clamped to 0.
    assert score == pytest.approx(0.0)


def test_factor_score_neutral_is_50() -> None:
    s = _s()  # all defaults
    assert sentiment_to_factor_score(s) == pytest.approx(50.0)


def test_rank_sentiments_orders_by_score() -> None:
    sents = [
        _s(ticker="LOSER",  tone_label="bearish", tone_confidence=1.0,
           guidance_direction="lowered", guidance_confidence=1.0),
        _s(ticker="MIDDLE"),
        _s(ticker="WINNER", tone_label="bullish", tone_confidence=1.0,
           guidance_direction="raised", guidance_confidence=1.0),
    ]
    out = rank_sentiments(sents)
    assert out.iloc[0]["ticker"] == "WINNER"
    assert out.iloc[-1]["ticker"] == "LOSER"


def test_rank_sentiments_empty_input() -> None:
    out = rank_sentiments([])
    assert out.empty
    assert list(out.columns) == ["ticker", "raw", "rank", "z_score"]


def test_parse_extraction_handles_malformed_json() -> None:
    s = _parse_extraction(
        "no JSON here",
        ticker="A", call_date="2026-04-15", fiscal_period="Q1",
        eps_surprise_pct=None,
    )
    # Defaults: neutral tone, unknown guidance.
    assert s.tone_label == "neutral"
    assert s.guidance_direction == "unknown"


def test_parse_extraction_extracts_clean_json() -> None:
    text = (
        '{"tone_label": "bullish", "tone_confidence": 0.9, '
        '"guidance_direction": "raised", "guidance_confidence": 0.8, '
        '"qa_friction": 0.1, "summary": "Strong quarter; guidance up."}'
    )
    s = _parse_extraction(
        text, ticker="ABC", call_date="2026-04-15",
        fiscal_period="Q1 2026", eps_surprise_pct=5.5,
    )
    assert s.tone_label == "bullish"
    assert s.guidance_direction == "raised"
    assert s.qa_friction == pytest.approx(0.1)
    assert s.eps_surprise_pct == pytest.approx(5.5)


def test_parse_extraction_tolerates_surrounding_prose() -> None:
    text = (
        "Here is the analysis: "
        '{"tone_label": "neutral", "tone_confidence": 0.5, '
        '"guidance_direction": "in_line", "guidance_confidence": 0.5, '
        '"qa_friction": 0.0, "summary": "In-line quarter."} '
        "Hope this helps."
    )
    s = _parse_extraction(
        text, ticker="A", call_date="2026-01-01",
        fiscal_period="Q4 2025", eps_surprise_pct=None,
    )
    assert s.tone_label == "neutral"
