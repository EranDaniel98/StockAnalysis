"""
Composite scoring engine.
Combines all analysis results into a weighted score using strategy-defined weights.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np

logger = logging.getLogger(__name__)


# Status semantics for every sub-analyzer slot. Drives whether the slot
# enters the weighted denominator. Tier-1 fix: before this, missing or
# crashed analyzers contributed a silent neutral 50 to the composite —
# a broken alpha158 or fundamentals module could never harm a score.
AnalyzerStatus = Literal["ok", "disabled", "error"]

# Default weights when a strategy doesn't supply its own. Kept here so
# `calculate_composite_score` is callable in unit tests without a full
# strategy yaml.
DEFAULT_WEIGHTS: dict[str, float] = {
    "technical": 0.30,
    "fundamental": 0.25,
    "pattern": 0.15,
    "statistical": 0.20,
    "trend": 0.10,
}

# Maximum points the signal-consensus nudge can move the composite.
# Documented in config/strategies.yaml's envelope comment.
_CONSENSUS_NUDGE_CAP = 5

# Composite placeholder used when no required analyzer contributed.
# The ``score_valid=False`` flag travels with this number so callers
# can refuse the score; we keep it at 50 (neutral) rather than 0 so
# downstream UI doesn't show a misleading "FAIL" red bar.
_INVALID_COMPOSITE = 50.0


def _infer_status(result: Any, *, required: bool) -> AnalyzerStatus:
    """Map an analyzer result dict to a status label.

    Required analyzers (technical/fundamental/pattern/statistical/trend)
    must produce a numeric score; a None or shapeless dict is an error.
    Optional analyzers (alpha158, pead, insider_flow, ...) are "disabled"
    when not invoked (None passed in) and "error" when invoked but
    crashed (dict present but missing or non-numeric score).
    """
    if result is None:
        return "disabled" if not required else "error"
    if not isinstance(result, dict):
        return "error"
    if result.get("error"):
        return "error"
    score = result.get("score")
    if score is None:
        return "error"
    try:
        float(score)
    except (TypeError, ValueError):
        return "error"
    return "ok"


# Ordered metadata for every sub-score slot: (slot_name, required).
# Required slots are the strategy-mandated core analyzers; optional slots
# are passed as None when not enabled.
_SLOT_SPECS: list[tuple[str, bool]] = [
    ("technical", True),
    ("fundamental", True),
    ("pattern", True),
    ("statistical", True),
    ("trend", True),
    ("alpha158", False),
    ("rel_strength", False),
    ("insider_flow", False),
    ("catalyst", False),
    ("short_interest", False),
    ("sector_flows", False),
    ("analyst_revisions", False),
    ("options_skew", False),
]


def _collect_sub_scores(
    raw_results: dict[str, Any],
) -> tuple[dict[str, AnalyzerStatus], dict[str, float]]:
    """Build the (status, sub_score) maps for every slot.

    Excluded slots (status == error or disabled) don't appear in
    ``sub_scores`` so the weighted denominator only counts contributors.
    """
    analyzer_status: dict[str, AnalyzerStatus] = {}
    sub_scores: dict[str, float] = {}
    for slot, required in _SLOT_SPECS:
        result = raw_results[slot]
        status = _infer_status(result, required=required)
        analyzer_status[slot] = status
        if status == "ok":
            sub_scores[slot] = float(result["score"])
            continue
        if status == "error":
            # Don't WARN per call — a backtest scoring R1000 across 100+
            # Mondays will emit tens of thousands of identical lines and
            # bury real issues. The structured analyzer_status field on
            # every CompositeScore already surfaces this for dashboards
            # and downstream gating.
            logger.debug(
                "Analyzer %s returned no usable score (status=%s); excluding "
                "from weighted denominator. result=%r",
                slot, status,
                {k: result.get(k) for k in ("error", "score")}
                if isinstance(result, dict) else result,
            )
    return analyzer_status, sub_scores


def _collect_signals(
    raw_results: dict[str, Any],
    sub_scores: dict[str, float],
    pead_result: Any,
) -> list[dict]:
    """Aggregate signals from every contributing analyzer plus PEAD.

    Each signal is shallow-copied and tagged with ``_analyzer_slot`` so
    the per-source consensus normalization can dedupe (e.g. SMA20 +
    SMA50 from the technical analyzer count as one vote).
    """
    all_signals: list[dict] = []
    for slot in sub_scores:
        result = raw_results[slot]
        if isinstance(result, dict):
            for sig in (result.get("signals", []) or []):
                tagged = dict(sig)
                tagged.setdefault("_analyzer_slot", slot)
                all_signals.append(tagged)
    if pead_result is not None and isinstance(pead_result, dict):
        for sig in (pead_result.get("signals", []) or []):
            tagged = dict(sig)
            tagged.setdefault("_analyzer_slot", "pead")
            all_signals.append(tagged)
    return all_signals


def _weighted_composite(
    sub_scores: dict[str, float],
    weights: dict[str, float],
) -> tuple[float, float, bool]:
    """Return ``(composite, total_weight, score_valid)``.

    Renormalizes the denominator over the slots that actually
    contributed, so missing slots can't silently shrink the composite.
    When no slot contributed, falls back to the invalid placeholder.
    """
    total_weight = sum(weights.get(slot, 0) for slot in sub_scores)
    if total_weight > 0:
        composite = sum(
            sub_scores[slot] * weights.get(slot, 0) for slot in sub_scores
        ) / total_weight
        return composite, total_weight, True
    return _INVALID_COMPOSITE, 0.0, False


def _count_signals(all_signals: list[dict]) -> tuple[int, int, int, int]:
    """Return ``(display_bull, display_bear, consensus_bull, consensus_bear)``.

    Display counts vote every sub-indicator (UI honesty). Consensus
    counts dedupe to one bullish + one bearish vote per analyzer slot,
    so analyzers with many sub-indicators don't dominate the ±5 nudge.
    """
    bullish_count = sum(1 for s in all_signals if s.get("type") == "bullish")
    bearish_count = sum(1 for s in all_signals if s.get("type") == "bearish")

    per_analyzer_votes: dict[str, set[str]] = {}
    for s in all_signals:
        sig_type = s.get("type")
        if sig_type not in ("bullish", "bearish"):
            continue
        slot = s.get("_analyzer_slot", "unknown")
        per_analyzer_votes.setdefault(slot, set()).add(sig_type)
    consensus_bullish = sum(
        1 for votes in per_analyzer_votes.values() if "bullish" in votes
    )
    consensus_bearish = sum(
        1 for votes in per_analyzer_votes.values() if "bearish" in votes
    )
    return bullish_count, bearish_count, consensus_bullish, consensus_bearish


def _apply_pead_bonus(composite: float, pead_result: Any) -> float:
    """Additive PEAD bonus (range typically [-10, +10])."""
    if pead_result is None or not isinstance(pead_result, dict):
        return composite
    pead_bonus = pead_result.get("composite_bonus", 0.0) or 0.0
    try:
        return composite + float(pead_bonus)
    except (TypeError, ValueError):
        return composite


def _apply_consensus_scaling(
    composite: float,
    sub_scores: dict[str, float],
    strategy_config: dict,
) -> tuple[float, dict]:
    """Carver-style scaling: opt-in via strategy.use_consensus_scaling."""
    if not strategy_config.get("use_consensus_scaling", False) or not sub_scores:
        return composite, {}
    from src.scoring.diversification import apply_consensus_scaling

    return apply_consensus_scaling(composite, sub_scores)


def _apply_signal_consensus_nudge(
    composite: float,
    consensus_bullish: int,
    consensus_bearish: int,
) -> float:
    """Per-analyzer bullish/bearish consensus moves composite up to ±5."""
    total = consensus_bullish + consensus_bearish
    if total <= 0:
        return composite
    ratio = (consensus_bullish - consensus_bearish) / total
    return composite + ratio * _CONSENSUS_NUDGE_CAP


def _build_breakdown(
    analyzer_status: dict[str, AnalyzerStatus],
    sub_scores: dict[str, float],
    weights: dict[str, float],
    total_weight: float,
) -> list[dict]:
    """Display rows. Disabled optional slots are hidden; errored slots
    appear with ``status='error'`` so operators can see why a number
    looks off."""
    breakdown: list[dict] = []
    for slot, status in analyzer_status.items():
        if status == "disabled":
            continue
        w = weights.get(slot, 0)
        if status == "ok":
            s = sub_scores[slot]
            effective_w = w / total_weight if total_weight > 0 else 0
            contribution = s * effective_w
            breakdown.append({
                "category": slot.capitalize(),
                "score": round(s, 1),
                "weight": f"{w*100:.0f}%",
                "contribution": round(contribution, 1),
                "status": "ok",
                # effective_weight is the post-renormalization share so
                # the breakdown table doesn't mislead when error slots
                # are excluded. ok rows' effective_weight values sum to
                # 1.0; nominal ``weight`` values don't (they sum to <1
                # in error scenarios).
                "effective_weight": round(effective_w, 4),
            })
        else:
            breakdown.append({
                "category": slot.capitalize(),
                "score": None,
                "weight": f"{w*100:.0f}%",
                "contribution": 0.0,
                "status": status,
                "effective_weight": None,
            })
    return breakdown


def calculate_composite_score(
    technical_result: Any,
    fundamental_result: Any,
    pattern_result: Any,
    statistical_result: Any,
    trend_result: Any,
    strategy_config: dict,
    alpha158_result: Any = None,
    pead_result: Any = None,
    rel_strength_result: Any = None,
    insider_flow_result: Any = None,
    catalyst_result: Any = None,
    short_interest_result: Any = None,
    sector_flows_result: Any = None,
    analyst_revisions_result: Any = None,
    options_skew_result: Any = None,
) -> dict:
    """Combine all analysis sub-scores into a weighted composite.

    Pipeline (each step is a small helper above):

    1. Map every analyzer result → status (ok / disabled / error) and
       collect numeric sub-scores from ok slots only.
    2. Aggregate signals from contributing slots + PEAD, tagged by slot.
    3. Compute the renormalized weighted composite over contributors;
       set ``score_valid=False`` when no slot contributed.
    4. When valid, apply post-composite adjustments in fixed order:
       PEAD bonus → Carver scaling → signal-consensus nudge. The
       envelope these can move is documented in config/strategies.yaml.
    5. Clamp to [0, 100].
    6. Build the breakdown table for UI display.

    Returns
    -------
    dict with composite_score, sub_scores, all_signals, breakdown plus
    analyzer_status (slot → "ok"/"disabled"/"error"), error_count, and
    score_valid (True iff at least one "ok" slot contributed).
    """
    weights = strategy_config.get("weights", DEFAULT_WEIGHTS)

    raw_results: dict[str, Any] = {
        "technical": technical_result,
        "fundamental": fundamental_result,
        "pattern": pattern_result,
        "statistical": statistical_result,
        "trend": trend_result,
        "alpha158": alpha158_result,
        "rel_strength": rel_strength_result,
        "insider_flow": insider_flow_result,
        "catalyst": catalyst_result,
        "short_interest": short_interest_result,
        "sector_flows": sector_flows_result,
        "analyst_revisions": analyst_revisions_result,
        "options_skew": options_skew_result,
    }

    analyzer_status, sub_scores = _collect_sub_scores(raw_results)
    error_count = sum(1 for s in analyzer_status.values() if s == "error")
    error_slots = [slot for slot, s in analyzer_status.items() if s == "error"]

    all_signals = _collect_signals(raw_results, sub_scores, pead_result)

    composite, total_weight, score_valid = _weighted_composite(sub_scores, weights)

    bullish_count, bearish_count, consensus_bullish, consensus_bearish = (
        _count_signals(all_signals)
    )

    # Post-composite adjustments only fire when score_valid is True.
    # When all required analyzers errored, composite is the invalid
    # placeholder and lifting it via PEAD or consensus would manufacture
    # a BUY threshold out of zero real signal. Always compute signal
    # counts and the consensus diag (callers display them).
    consensus_diag: dict = {}
    if score_valid:
        composite = _apply_pead_bonus(composite, pead_result)
        composite, consensus_diag = _apply_consensus_scaling(
            composite, sub_scores, strategy_config,
        )
        composite = _apply_signal_consensus_nudge(
            composite, consensus_bullish, consensus_bearish,
        )

    composite = max(0.0, min(100.0, composite))

    breakdown = _build_breakdown(
        analyzer_status, sub_scores, weights, total_weight,
    )

    return {
        "composite_score": round(float(composite), 2),
        "sub_scores": sub_scores,
        "all_signals": all_signals,
        "bullish_signals": bullish_count,
        "bearish_signals": bearish_count,
        "breakdown": breakdown,
        "consensus": consensus_diag,
        "analyzer_status": analyzer_status,
        "error_count": error_count,
        "error_slots": error_slots,
        "score_valid": score_valid,
    }


def batch_score(analysis_results, strategy_config):
    """
    Score multiple stocks and rank them.

    Args:
        analysis_results: dict of {ticker: {technical, fundamental, pattern, statistical, trend}}
        strategy_config: strategy configuration

    Returns:
        list of (ticker, score_result) tuples sorted by composite score descending.
        Tickers whose scoring crashed at the engine level are still emitted with a
        sentinel result (composite_score=0, error_count populated) so the caller can
        see drift between len(input) and len(scored). Old behavior silently dropped
        them.
    """
    scored = []

    for ticker, results in analysis_results.items():
        try:
            score_result = calculate_composite_score(
                technical_result=results.get("technical", {}),
                fundamental_result=results.get("fundamental", {}),
                pattern_result=results.get("pattern", {}),
                statistical_result=results.get("statistical", {}),
                trend_result=results.get("trend", {}),
                strategy_config=strategy_config,
                alpha158_result=results.get("alpha158"),
                pead_result=results.get("pead"),
                rel_strength_result=results.get("rel_strength"),
                insider_flow_result=results.get("insider_flow"),
                catalyst_result=results.get("catalyst"),
                short_interest_result=results.get("short_interest"),
                sector_flows_result=results.get("sector_flows"),
                analyst_revisions_result=results.get("analyst_revisions"),
                options_skew_result=results.get("options_skew"),
            )
            scored.append((ticker, score_result))
        except Exception as e:
            # Promoted from logger.error: this path was previously silent
            # at warning levels even though the ticker disappeared from
            # `scored` entirely. Emit a sentinel so downstream count
            # comparisons see the drift instead of just a shorter list.
            logger.warning(
                "batch_score: scoring engine crashed for %s (%s: %s) — "
                "emitting sentinel result with error_count=999",
                ticker, type(e).__name__, e,
            )
            scored.append((ticker, {
                "composite_score": 0.0,
                "sub_scores": {},
                "all_signals": [],
                "bullish_signals": 0,
                "bearish_signals": 0,
                "breakdown": [],
                "consensus": {},
                "analyzer_status": {slot: "error" for slot, _ in _SLOT_SPECS},
                "error_count": 999,
                "error_slots": [slot for slot, _ in _SLOT_SPECS],
                "score_valid": False,
                "scoring_engine_error": f"{type(e).__name__}: {e}",
            }))

    # Sort by composite score
    scored.sort(key=lambda x: x[1]["composite_score"], reverse=True)
    return scored
