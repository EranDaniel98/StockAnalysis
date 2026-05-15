"""
Composite scoring engine.
Combines all analysis results into a weighted score using strategy-defined weights.
"""

import logging
from typing import Literal

import numpy as np

logger = logging.getLogger(__name__)


# Status semantics for every sub-analyzer slot. Drives whether the slot
# enters the weighted denominator. Tier-1 fix: before this, missing or
# crashed analyzers contributed a silent neutral 50 to the composite —
# a broken alpha158 or fundamentals module could never harm a score.
AnalyzerStatus = Literal["ok", "disabled", "error"]


def _infer_status(result, *, required: bool) -> AnalyzerStatus:
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


def calculate_composite_score(
    technical_result,
    fundamental_result,
    pattern_result,
    statistical_result,
    trend_result,
    strategy_config,
    alpha158_result=None,
    pead_result=None,
    rel_strength_result=None,
    insider_flow_result=None,
    catalyst_result=None,
    short_interest_result=None,
    sector_flows_result=None,
    analyst_revisions_result=None,
    options_skew_result=None,
):
    """
    Combine all analysis sub-scores into a weighted composite.

    Args:
        technical_result: dict from analysis.technical.analyze()
        fundamental_result: dict from analysis.fundamental.analyze()
        pattern_result: dict from analysis.patterns.analyze()
        statistical_result: dict from analysis.statistical.analyze()
        trend_result: dict from analysis.trend_detector.analyze_stock_trend()
        strategy_config: dict with 'weights' key from strategies.yaml
        alpha158_result: optional dict from analysis.alpha158.analyze()
        pead_result: optional dict from analysis.pead.analyze() — additive
            bonus rather than weighted average

    Returns:
        dict with composite_score, sub_scores, all_signals, breakdown, plus
        analyzer_status (slot -> "ok"/"disabled"/"error"), error_count, and
        score_valid (True iff at least one "ok" slot contributed).
    """
    weights = strategy_config.get("weights", {
        "technical": 0.30,
        "fundamental": 0.25,
        "pattern": 0.15,
        "statistical": 0.20,
        "trend": 0.10,
    })

    raw_results = {
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
            # bury real issues. The structured `analyzer_status` field on
            # every CompositeScore already surfaces this for dashboards
            # and downstream gating; the per-call log is a debug-level
            # diagnostic only. Composite-engine UNCAUGHT exceptions are
            # still logged at WARNING in batch_score (the original audit
            # ask was about uncaught exceptions disappearing silently,
            # not this per-analyzer score-missing surface — see commit
            # 9345a74 for the original intent).
            logger.debug(
                "Analyzer %s returned no usable score (status=%s); excluding "
                "from weighted denominator. result=%r",
                slot, status,
                # Don't dump full result — analyzer dicts can be large.
                {k: result.get(k) for k in ("error", "score")} if isinstance(result, dict) else result,
            )

    error_count = sum(1 for s in analyzer_status.values() if s == "error")
    error_slots = [slot for slot, s in analyzer_status.items() if s == "error"]

    # Collect signals only from "ok" slots — a broken analyzer's stale
    # signals would skew the bullish/bearish consensus adjustment.
    all_signals: list[dict] = []
    for slot in sub_scores:
        result = raw_results[slot]
        if isinstance(result, dict):
            all_signals.extend(result.get("signals", []) or [])

    # PEAD is handled separately as an additive bonus; collect its signals
    # too (when not None and structurally valid).
    if pead_result is not None and isinstance(pead_result, dict):
        all_signals.extend(pead_result.get("signals", []) or [])

    # Calculate weighted composite over ok slots only. Renormalize so the
    # denominator reflects what actually contributed; otherwise weights
    # silently sum to <1 and the composite floats too low.
    total_weight = sum(weights.get(slot, 0) for slot in sub_scores)
    if total_weight > 0:
        composite = sum(
            sub_scores[slot] * weights.get(slot, 0) for slot in sub_scores
        ) / total_weight
        score_valid = True
    else:
        # All required slots errored or had zero weight. Composite is
        # mathematically undefined; fall back to 50 but flag invalid.
        composite = 50.0
        score_valid = False

    # Post-composite adjustments — PEAD bonus, Carver consensus scaling,
    # signal-consensus ±5. These ONLY apply when score_valid is True. When
    # all required analyzers errored, composite is the 50.0 placeholder
    # and lifting it via PEAD (which can be +5/+10) plus a bullish signal
    # consensus (+5) would manufacture a BUY threshold (~65) out of zero
    # real signal. Reviewer-flagged B2: keep the placeholder at 50 so the
    # downstream score_valid gate refuses cleanly. Always compute the
    # signal counts (callers display them) and the consensus diag (so
    # operators see "scaling skipped: score_valid=False").
    bullish_count = sum(1 for s in all_signals if s.get("type") == "bullish")
    bearish_count = sum(1 for s in all_signals if s.get("type") == "bearish")
    consensus_diag: dict = {}

    if score_valid:
        # PEAD bonus (additive, not weighted) — captures earnings drift premium.
        if pead_result is not None and isinstance(pead_result, dict):
            pead_bonus = pead_result.get("composite_bonus", 0.0) or 0.0
            try:
                composite += float(pead_bonus)
            except (TypeError, ValueError):
                pass

        # Carver-style consensus scaling: when sub-scores disagree, pull
        # composite toward 50 (neutral). Opt-in via strategy config.
        if strategy_config.get("use_consensus_scaling", False) and sub_scores:
            from src.scoring.diversification import apply_consensus_scaling
            composite, consensus_diag = apply_consensus_scaling(composite, sub_scores)

        total_signals = bullish_count + bearish_count
        if total_signals > 0:
            consensus_ratio = (bullish_count - bearish_count) / total_signals
            # Slight adjustment based on signal consensus (max +/- 5 points).
            composite += consensus_ratio * 5

    composite = max(0, min(100, composite))

    # Breakdown for display — only include slots that had a status entry
    # (so disabled optional slots stay hidden, but error slots show with
    # status="error" so operators can see WHY a number looks off).
    breakdown = []
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
                # Reviewer I6: post-renormalization share so the
                # breakdown table doesn't mislead when error slots are
                # excluded. ok rows' effective_weight values sum to 1.0;
                # nominal ``weight`` values don't (they sum to <1 in
                # error scenarios), which previously made the table
                # look like only some of the composite was accounted for.
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
