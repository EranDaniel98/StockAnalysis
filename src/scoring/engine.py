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

    # Collect all signals
    all_signals = []
    for result in [technical_result, fundamental_result, pattern_result,
                   statistical_result, trend_result]:
        all_signals.extend(result.get("signals", []))

    # Calculate weighted composite
    total_weight = 0
    weighted_sum = 0

    for category, score in sub_scores.items():
        w = weights.get(category, 0)
        weighted_sum += score * w
        total_weight += w

    composite = weighted_sum / total_weight if total_weight > 0 else 50

    # Signal consensus adjustment
    bullish_count = sum(1 for s in all_signals if s.get("type") == "bullish")
    bearish_count = sum(1 for s in all_signals if s.get("type") == "bearish")
    total_signals = bullish_count + bearish_count

    if total_signals > 0:
        consensus_ratio = (bullish_count - bearish_count) / total_signals
        # Slight adjustment based on signal consensus (max +/- 5 points)
        composite += consensus_ratio * 5

    composite = max(0, min(100, composite))

    # Breakdown for display
    breakdown = []
    for category in ["technical", "fundamental", "pattern", "statistical", "trend"]:
        w = weights.get(category, 0)
        s = sub_scores[category]
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
            )
            scored.append((ticker, score_result))
        except Exception as e:
            logger.error(f"Error scoring {ticker}: {e}")

    # Sort by composite score
    scored.sort(key=lambda x: x[1]["composite_score"], reverse=True)
    return scored
