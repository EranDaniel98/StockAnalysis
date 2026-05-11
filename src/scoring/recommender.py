"""
Recommendation engine.
Generates buy/sell/hold recommendations with position sizing,
stop-loss/take-profit levels, and diversification checks.
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)


def generate_recommendation(ticker, score_result, price_data, fundamentals, config, strategy=None):
    """
    Generate a full investment recommendation for a stock.

    Args:
        ticker: stock ticker symbol
        score_result: dict from scoring.engine.calculate_composite_score()
        price_data: DataFrame with OHLCV
        fundamentals: dict of fundamental data
        config: Config object
        strategy: optional strategy dict — if it contains a `thresholds` block,
                  those values override the global ones (per-strategy calibration)

    Returns:
        dict with action, confidence, reasoning, risk management params
    """
    composite = score_result["composite_score"]
    thresholds = dict(config.get_scoring_thresholds())
    if strategy:
        thresholds.update(strategy.get("thresholds", {}) or {})

    # --- Determine Action ---
    action, confidence = _determine_action(composite, thresholds)

    # --- Collect Key Reasoning ---
    reasoning = _build_reasoning(score_result, fundamentals)

    # --- Risk Management ---
    risk = {}
    if price_data is not None and not price_data.empty:
        risk = _calculate_risk_management(
            ticker, price_data, fundamentals, config, action
        )

    return {
        "ticker": ticker,
        "action": action,
        "composite_score": composite,
        "confidence": confidence,
        "sub_scores": score_result.get("sub_scores", {}),
        "breakdown": score_result.get("breakdown", []),
        "reasoning": reasoning,
        "bullish_signals": score_result.get("bullish_signals", 0),
        "bearish_signals": score_result.get("bearish_signals", 0),
        "all_signals": score_result.get("all_signals", []),
        "risk_management": risk,
        "name": fundamentals.get("name", ticker) if fundamentals else ticker,
        "sector": fundamentals.get("sector", "Unknown") if fundamentals else "Unknown",
        "industry": fundamentals.get("industry", "Unknown") if fundamentals else "Unknown",
        "market_cap": fundamentals.get("market_cap") if fundamentals else None,
    }


def _determine_action(composite, thresholds):
    """Map composite score to action label and confidence."""
    if composite >= thresholds.get("strong_buy", 80):
        return "STRONG BUY", "High"
    elif composite >= thresholds.get("buy", 65):
        return "BUY", "Medium-High"
    elif composite >= thresholds.get("hold_upper", 50):
        return "HOLD", "Medium"
    elif composite >= thresholds.get("hold_lower", 35):
        return "HOLD", "Low"
    elif composite >= thresholds.get("sell", 20):
        return "SELL", "Medium-High"
    else:
        return "STRONG SELL", "High"


def _build_reasoning(score_result, fundamentals):
    """Build a list of key reasons for the recommendation."""
    reasons = []
    signals = score_result.get("all_signals", [])

    # Top bullish signals
    bullish = [s for s in signals if s.get("type") == "bullish"]
    bearish = [s for s in signals if s.get("type") == "bearish"]

    for s in bullish[:5]:
        reasons.append(f"+ {s['source']}: {s['detail']}")

    for s in bearish[:5]:
        reasons.append(f"- {s['source']}: {s['detail']}")

    # Sub-score summary
    sub_scores = score_result.get("sub_scores", {})
    strongest = max(sub_scores, key=sub_scores.get) if sub_scores else None
    weakest = min(sub_scores, key=sub_scores.get) if sub_scores else None

    if strongest:
        reasons.append(f"Strongest: {strongest.capitalize()} ({sub_scores[strongest]:.0f}/100)")
    if weakest and weakest != strongest:
        reasons.append(f"Weakest: {weakest.capitalize()} ({sub_scores[weakest]:.0f}/100)")

    return reasons


def _calculate_risk_management(ticker, price_data, fundamentals, config, action):
    """Calculate position sizing, stop-loss, and take-profit."""
    close = price_data["Close"]
    current_price = float(close.iloc[-1])
    risk_config = config.get("risk_management", default={})

    result = {"current_price": round(current_price, 2)}

    # --- Stop Loss ---
    result["stop_loss"] = _calculate_stop_loss(
        price_data, current_price, risk_config.get("stop_loss", {})
    )

    # --- Take Profit ---
    result["take_profit"] = _calculate_take_profit(
        price_data, current_price, result["stop_loss"],
        risk_config.get("take_profit", {})
    )

    # --- Position Sizing ---
    result["position"] = _calculate_position_size(
        current_price, result["stop_loss"], risk_config.get("position_sizing", {}),
        action
    )

    # --- Risk/Reward Ratio ---
    sl_price = result["stop_loss"].get("price", current_price * 0.95)
    tp_price = result["take_profit"].get("price", current_price * 1.15)
    risk_amount = abs(current_price - sl_price)
    reward_amount = abs(tp_price - current_price)
    result["risk_reward_ratio"] = (
        round(reward_amount / risk_amount, 2) if risk_amount > 0 else 0
    )

    return result


def _calculate_stop_loss(price_data, current_price, sl_config):
    """Calculate stop-loss price using configured method."""
    method = sl_config.get("method", "atr")
    result = {"method": method}

    if method == "atr":
        multiplier = sl_config.get("atr_multiplier", 2.0)
        atr = _calc_atr(price_data)
        if atr > 0:
            sl_price = current_price - (atr * multiplier)
            result["price"] = round(sl_price, 2)
            result["pct_from_current"] = round((sl_price / current_price - 1) * 100, 2)
            result["detail"] = f"ATR({multiplier}x): ${sl_price:.2f}"
        else:
            # Fallback to percentage
            pct = sl_config.get("percentage", 5.0) / 100
            result["price"] = round(current_price * (1 - pct), 2)
            result["pct_from_current"] = round(-pct * 100, 2)

    elif method == "percentage":
        pct = sl_config.get("percentage", 5.0) / 100
        sl_price = current_price * (1 - pct)
        result["price"] = round(sl_price, 2)
        result["pct_from_current"] = round(-pct * 100, 2)
        result["detail"] = f"Fixed {pct*100:.1f}%: ${sl_price:.2f}"

    elif method == "support":
        # Use nearest support level
        from src.analysis.patterns import _find_support_resistance
        sr = _find_support_resistance(
            price_data["High"], price_data["Low"], price_data["Close"]
        )
        supports = sr.get("support", [])
        if supports:
            # Set stop just below nearest support (2% buffer)
            sl_price = supports[0] * 0.98
            result["price"] = round(sl_price, 2)
            result["pct_from_current"] = round((sl_price / current_price - 1) * 100, 2)
            result["detail"] = f"Below support ${supports[0]:.2f}: ${sl_price:.2f}"
        else:
            pct = sl_config.get("percentage", 5.0) / 100
            result["price"] = round(current_price * (1 - pct), 2)
            result["pct_from_current"] = round(-pct * 100, 2)

    return result


def _calculate_take_profit(price_data, current_price, stop_loss, tp_config):
    """Calculate take-profit price using configured method."""
    method = tp_config.get("method", "risk_reward")
    result = {"method": method}

    sl_price = stop_loss.get("price", current_price * 0.95)
    risk = abs(current_price - sl_price)

    if method == "risk_reward":
        ratio = tp_config.get("risk_reward_ratio", 3.0)
        tp_price = current_price + (risk * ratio)
        result["price"] = round(tp_price, 2)
        result["pct_from_current"] = round((tp_price / current_price - 1) * 100, 2)
        result["detail"] = f"R:R {ratio}:1 -> ${tp_price:.2f}"

    elif method == "atr":
        multiplier = tp_config.get("atr_multiplier", 4.0)
        atr = _calc_atr(price_data)
        tp_price = current_price + (atr * multiplier)
        result["price"] = round(tp_price, 2)
        result["pct_from_current"] = round((tp_price / current_price - 1) * 100, 2)
        result["detail"] = f"ATR({multiplier}x): ${tp_price:.2f}"

    elif method == "resistance":
        from src.analysis.patterns import _find_support_resistance
        sr = _find_support_resistance(
            price_data["High"], price_data["Low"], price_data["Close"]
        )
        resistances = sr.get("resistance", [])
        if resistances:
            tp_price = resistances[0]
            result["price"] = round(tp_price, 2)
            result["pct_from_current"] = round((tp_price / current_price - 1) * 100, 2)
            result["detail"] = f"Resistance: ${tp_price:.2f}"
        else:
            ratio = tp_config.get("risk_reward_ratio", 3.0)
            tp_price = current_price + (risk * ratio)
            result["price"] = round(tp_price, 2)
            result["pct_from_current"] = round((tp_price / current_price - 1) * 100, 2)

    return result


def _calculate_position_size(current_price, stop_loss, sizing_config, action):
    """Calculate recommended position size."""
    method = sizing_config.get("method", "fixed_fractional")
    portfolio = sizing_config.get("default_portfolio_value", 100000)
    max_pct = sizing_config.get("max_portfolio_pct", 10) / 100
    result = {"method": method, "portfolio_value": portfolio}

    if action in ("SELL", "STRONG SELL", "HOLD"):
        result["recommended_shares"] = 0
        result["dollar_amount"] = 0
        result["pct_of_portfolio"] = 0
        return result

    sl_price = stop_loss.get("price", current_price * 0.95)
    risk_per_share = abs(current_price - sl_price)

    if method == "fixed_fractional":
        # Risk a fixed % of portfolio per trade
        max_position = portfolio * max_pct
        if risk_per_share > 0:
            # Risk at most 1% of portfolio on this trade
            risk_budget = portfolio * 0.01
            shares_by_risk = int(risk_budget / risk_per_share)
            shares_by_max = int(max_position / current_price)
            shares = min(shares_by_risk, shares_by_max)
        else:
            shares = int(max_position / current_price)

        dollar_amount = shares * current_price
        result["recommended_shares"] = max(1, shares)
        result["dollar_amount"] = round(dollar_amount, 2)
        result["pct_of_portfolio"] = round(dollar_amount / portfolio * 100, 2)
        result["risk_per_trade"] = round(shares * risk_per_share, 2)
        result["risk_pct"] = round(shares * risk_per_share / portfolio * 100, 2)

    elif method == "kelly":
        # Kelly Criterion: f = (bp - q) / b
        # Simplified: use win rate from signals as probability
        # This is a rough approximation
        win_prob = 0.55  # default assumption
        avg_win = abs(stop_loss.get("pct_from_current", 5))  # approximate
        avg_loss = abs(stop_loss.get("pct_from_current", 5))
        if avg_loss > 0:
            b = avg_win / avg_loss
            kelly_fraction = (b * win_prob - (1 - win_prob)) / b
            kelly_fraction = max(0, min(kelly_fraction, max_pct))
        else:
            kelly_fraction = max_pct * 0.5

        # Half-Kelly for safety
        kelly_fraction *= 0.5
        dollar_amount = portfolio * kelly_fraction
        shares = int(dollar_amount / current_price)

        result["recommended_shares"] = max(1, shares)
        result["dollar_amount"] = round(dollar_amount, 2)
        result["pct_of_portfolio"] = round(kelly_fraction * 100, 2)
        result["kelly_fraction"] = round(kelly_fraction, 4)

    return result


def _calc_atr(price_data, period=14):
    """Calculate ATR from price data."""
    if len(price_data) < period + 1:
        return 0

    high = price_data["High"]
    low = price_data["Low"]
    close = price_data["Close"]

    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))

    import pandas as pd
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return float(atr.iloc[-1]) if not atr.empty else 0




# --- Portfolio-level functions moved to src/portfolio/allocation.py in
#     Stream B slice 2. The re-exports below keep src/main.py imports
#     (`from src.scoring.recommender import check_diversification,
#     allocate_portfolio`) working through Phase 0; Phase 1 will migrate
#     callers to import directly from src.portfolio.allocation.
from src.portfolio.allocation import (  # noqa: F401  (re-exports for back-compat)
    allocate_portfolio,
    check_diversification,
    suggest_order_type,
)
