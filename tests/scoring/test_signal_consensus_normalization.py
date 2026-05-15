"""Tier-2 audit #21: signal-consensus normalizes per analyzer source.

Pre-fix: every bullish/bearish signal in the flat ``all_signals`` list
got one vote in the ±5 consensus nudge. An analyzer with many
sub-indicators (technical = SMA20 + SMA50 + SMA200 + RSI + MACD +
volume = up to 6 bullish votes) would dominate the consensus signal,
regardless of strategy-weight allocation.

After: each analyzer slot contributes at most one bullish + one
bearish vote to the consensus calculation. Display counts
(``bullish_signals`` / ``bearish_signals`` in the result dict) stay
raw — operators reading the UI still see "8 bullish / 3 bearish"
honestly — but the actual ±5 adjustment uses the normalized count.

Same logic is mirrored in ``src/backtest/score_cache.py:recompose_composite``
so cached multi-mode replays don't diverge from the live path.
"""

from __future__ import annotations

import pytest

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


def _ok(score: float, signals: list[dict]) -> dict:
    return {"score": score, "signals": signals}


def test_one_analyzer_many_bullish_signals_does_not_dominate():
    """Pre-fix reproducer: technical emits 5 bullish, fundamental emits
    1 bearish → 5 vs 1 → consensus = +4/6 = +0.67 → +3.3 pts.
    After fix: technical contributes 1 bullish, fundamental 1 bearish
    → consensus = 0 → 0 pts. The composite must reflect the new math."""
    technical = _ok(60.0, [
        {"type": "bullish", "source": "SMA20", "detail": ""},
        {"type": "bullish", "source": "SMA50", "detail": ""},
        {"type": "bullish", "source": "SMA200", "detail": ""},
        {"type": "bullish", "source": "RSI", "detail": ""},
        {"type": "bullish", "source": "MACD", "detail": ""},
    ])
    fundamental = _ok(60.0, [
        {"type": "bearish", "source": "PEG", "detail": ""},
    ])
    pattern = _ok(60.0, [])
    statistical = _ok(60.0, [])
    trend = _ok(60.0, [])

    out = calculate_composite_score(
        technical_result=technical,
        fundamental_result=fundamental,
        pattern_result=pattern,
        statistical_result=statistical,
        trend_result=trend,
        strategy_config=_strategy_cfg(),
    )

    # Weighted base composite = 60. Per-source normalization: technical
    # contributes 1 bullish, fundamental contributes 1 bearish → tie.
    # Consensus adjustment = 0. So composite stays at 60.0.
    assert out["composite_score"] == pytest.approx(60.0, abs=0.01)


def test_display_counts_remain_raw():
    """Sanity: the bullish_signals / bearish_signals fields in the
    result dict are RAW counts (every sub-indicator counted). Only the
    consensus math uses the normalized version. Operators see the
    honest indicator-level count in the UI."""
    technical = _ok(60.0, [
        {"type": "bullish", "source": "SMA20", "detail": ""},
        {"type": "bullish", "source": "SMA50", "detail": ""},
        {"type": "bullish", "source": "SMA200", "detail": ""},
    ])
    fundamental = _ok(60.0, [
        {"type": "bearish", "source": "PEG", "detail": ""},
    ])
    out = calculate_composite_score(
        technical_result=technical,
        fundamental_result=fundamental,
        pattern_result=_ok(60.0, []),
        statistical_result=_ok(60.0, []),
        trend_result=_ok(60.0, []),
        strategy_config=_strategy_cfg(),
    )
    # Raw counts, NOT normalized.
    assert out["bullish_signals"] == 3
    assert out["bearish_signals"] == 1


def test_unanimous_bullish_across_analyzers_still_lifts():
    """Sanity: if EVERY analyzer agrees bullishly, the consensus nudge
    should still fire (it's not zero just because we normalized). 5
    analyzers × 1 bullish each = 5 bullish, 0 bearish → +5.0 pts."""
    bullish_signal = [{"type": "bullish", "source": "x", "detail": ""}]
    out = calculate_composite_score(
        technical_result=_ok(60.0, list(bullish_signal)),
        fundamental_result=_ok(60.0, list(bullish_signal)),
        pattern_result=_ok(60.0, list(bullish_signal)),
        statistical_result=_ok(60.0, list(bullish_signal)),
        trend_result=_ok(60.0, list(bullish_signal)),
        strategy_config=_strategy_cfg(),
    )
    # 5 bullish, 0 bearish → consensus ratio = 1.0 → +5.0 pts. Composite
    # base is 60, so result is 65.
    assert out["composite_score"] == pytest.approx(65.0, abs=0.01)


def test_no_signals_means_no_consensus_adjustment():
    """Sanity: zero signals → no adjustment, composite stays at base."""
    out = calculate_composite_score(
        technical_result=_ok(72.0, []),
        fundamental_result=_ok(72.0, []),
        pattern_result=_ok(72.0, []),
        statistical_result=_ok(72.0, []),
        trend_result=_ok(72.0, []),
        strategy_config=_strategy_cfg(),
    )
    assert out["composite_score"] == pytest.approx(72.0, abs=0.01)


def test_score_cache_recompose_matches_normalized_engine():
    """The multi-mode replay path in score_cache must apply the SAME
    per-analyzer normalization, else cached and live composites would
    diverge for the same inputs. Pre-fix this divergence was the
    suspected cause of the insider_flow A/B null result (memory entry
    project_insider_r1000_finding)."""
    from src.backtest.score_cache import CachedScore, recompose_composite

    # Same setup as test_one_analyzer_many_bullish_signals_does_not_dominate
    # but in CachedScore form: technical=5 bullish, fundamental=1 bearish.
    cached = CachedScore(
        sub_scores={
            "technical": 60.0,
            "fundamental": 60.0,
            "pattern": 60.0,
            "statistical": 60.0,
            "trend": 60.0,
        },
        bullish_by_source={
            "technical": 5,        # five sub-indicators agreed
            "fundamental": 0,
            "pattern": 0,
            "statistical": 0,
            "trend": 0,
        },
        bearish_by_source={
            "technical": 0,
            "fundamental": 1,
            "pattern": 0,
            "statistical": 0,
            "trend": 0,
        },
        pead_bonus=0.0,
        atr=0.0,
        close=0.0,
    )
    weights = _strategy_cfg()["weights"]
    composite, _ = recompose_composite(cached, weights, enabled_sources=None)
    # Same expected outcome as the engine: 60.0 (1 bullish vs 1 bearish
    # at the analyzer level → tie → no nudge).
    assert composite == pytest.approx(60.0, abs=0.01)
