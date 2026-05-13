"""
Composite scoring engine.
Combines all analysis results into a weighted score using strategy-defined weights.
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)


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
        dict with composite_score, sub_scores, all_signals, breakdown
    """
    weights = strategy_config.get("weights", {
        "technical": 0.30,
        "fundamental": 0.25,
        "pattern": 0.15,
        "statistical": 0.20,
        "trend": 0.10,
    })

    sub_scores = {
        "technical": technical_result.get("score", 50),
        "fundamental": fundamental_result.get("score", 50),
        "pattern": pattern_result.get("score", 50),
        "statistical": statistical_result.get("score", 50),
        "trend": trend_result.get("score", 50),
    }
    if alpha158_result is not None:
        sub_scores["alpha158"] = alpha158_result.get("score", 50)
    if rel_strength_result is not None:
        sub_scores["rel_strength"] = rel_strength_result.get("score", 50)
    if insider_flow_result is not None:
        sub_scores["insider_flow"] = insider_flow_result.get("score", 50)

    # Collect all signals
    result_list = [technical_result, fundamental_result, pattern_result,
                   statistical_result, trend_result]
    if alpha158_result is not None:
        result_list.append(alpha158_result)
    if pead_result is not None:
        result_list.append(pead_result)
    if rel_strength_result is not None:
        result_list.append(rel_strength_result)
    if insider_flow_result is not None:
        result_list.append(insider_flow_result)
    all_signals = []
    for result in result_list:
        all_signals.extend(result.get("signals", []))

    # Calculate weighted composite
    total_weight = 0
    weighted_sum = 0

    for category, score in sub_scores.items():
        w = weights.get(category, 0)
        weighted_sum += score * w
        total_weight += w

    composite = weighted_sum / total_weight if total_weight > 0 else 50

    # PEAD bonus (additive, not weighted) — captures earnings drift premium
    if pead_result is not None:
        pead_bonus = pead_result.get("composite_bonus", 0.0)  # in score points
        composite += pead_bonus

    # Carver-style consensus scaling: when sub-scores disagree, pull composite
    # toward 50 (neutral). Opt-in via strategy config to preserve baseline.
    consensus_diag: dict = {}
    if strategy_config.get("use_consensus_scaling", False):
        from src.scoring.diversification import apply_consensus_scaling
        composite, consensus_diag = apply_consensus_scaling(composite, sub_scores)

    # Signal consensus adjustment
    bullish_count = sum(1 for s in all_signals if s.get("type") == "bullish")
    bearish_count = sum(1 for s in all_signals if s.get("type") == "bearish")
    total_signals = bullish_count + bearish_count

    if total_signals > 0:
        consensus_ratio = (bullish_count - bearish_count) / total_signals
        # Slight adjustment based on signal consensus (max +/- 5 points)
        composite += consensus_ratio * 5

    composite = max(0, min(100, composite))

    # Breakdown for display — include alpha158 if present
    breakdown_keys = ["technical", "fundamental", "pattern", "statistical", "trend"]
    if alpha158_result is not None:
        breakdown_keys.append("alpha158")
    if rel_strength_result is not None:
        breakdown_keys.append("rel_strength")
    if insider_flow_result is not None:
        breakdown_keys.append("insider_flow")
    breakdown = []
    for category in breakdown_keys:
        w = weights.get(category, 0)
        s = sub_scores.get(category, 50)
        contribution = s * w / total_weight if total_weight > 0 else 0
        breakdown.append({
            "category": category.capitalize(),
            "score": round(s, 1),
            "weight": f"{w*100:.0f}%",
            "contribution": round(contribution, 1),
        })

    return {
        "composite_score": round(float(composite), 2),
        "sub_scores": sub_scores,
        "all_signals": all_signals,
        "bullish_signals": bullish_count,
        "bearish_signals": bearish_count,
        "breakdown": breakdown,
        "consensus": consensus_diag,
    }


def batch_score(analysis_results, strategy_config):
    """
    Score multiple stocks and rank them.

    Args:
        analysis_results: dict of {ticker: {technical, fundamental, pattern, statistical, trend}}
        strategy_config: strategy configuration

    Returns:
        list of (ticker, score_result) tuples sorted by composite score descending
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
            )
            scored.append((ticker, score_result))
        except Exception as e:
            logger.error(f"Error scoring {ticker}: {e}")

    # Sort by composite score
    scored.sort(key=lambda x: x[1]["composite_score"], reverse=True)
    return scored
