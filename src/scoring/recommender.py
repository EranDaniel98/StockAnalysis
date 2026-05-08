"""
Recommendation engine.
Generates buy/sell/hold recommendations with position sizing,
stop-loss/take-profit levels, and diversification checks.
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)


def generate_recommendation(ticker, score_result, price_data, fundamentals, config):
    """
    Generate a full investment recommendation for a stock.

    Args:
        ticker: stock ticker symbol
        score_result: dict from scoring.engine.calculate_composite_score()
        price_data: DataFrame with OHLCV
        fundamentals: dict of fundamental data
        config: Config object

    Returns:
        dict with action, confidence, reasoning, risk management params
    """
    composite = score_result["composite_score"]
    thresholds = config.get_scoring_thresholds()

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


def check_diversification(recommendations, config):
    """
    Check portfolio diversification and add warnings.

    Args:
        recommendations: list of recommendation dicts (BUY/STRONG BUY only)
        config: Config object

    Returns:
        list of warning strings
    """
    max_sector_pct = config.get(
        "risk_management", "position_sizing", "max_sector_pct", default=30
    )
    portfolio_value = config.get(
        "risk_management", "position_sizing", "default_portfolio_value", default=100000
    )

    warnings = []

    # Count positions per sector
    sector_exposure = {}
    for rec in recommendations:
        if rec["action"] not in ("BUY", "STRONG BUY"):
            continue
        sector = rec.get("sector", "Unknown")
        amount = rec.get("risk_management", {}).get("position", {}).get("dollar_amount", 0)
        sector_exposure[sector] = sector_exposure.get(sector, 0) + amount

    # Check sector concentration
    for sector, amount in sector_exposure.items():
        pct = amount / portfolio_value * 100
        if pct > max_sector_pct:
            warnings.append(
                f"Sector concentration warning: {sector} at {pct:.1f}% "
                f"(max {max_sector_pct}%). Consider reducing exposure."
            )

    # Check total position count
    buy_count = sum(
        1 for r in recommendations if r["action"] in ("BUY", "STRONG BUY")
    )
    if buy_count > 20:
        warnings.append(
            f"Too many positions ({buy_count}). Consider focusing on "
            f"top-scoring stocks for better concentration."
        )
    elif buy_count == 0:
        warnings.append("No BUY signals found. Market conditions may be unfavorable.")

    return warnings


def allocate_portfolio(recommendations, budget, config):
    """
    Allocate a budget across BUY/STRONG BUY stocks using score-weighted sizing.

    Args:
        recommendations: list of recommendation dicts (sorted by score)
        budget: total dollar amount to invest
        config: Config object

    Returns:
        dict with:
            allocations: list of {ticker, name, action, score, allocation_pct,
                          dollar_amount, shares, price, stop_loss, take_profit,
                          order_type, order_detail, sector}
            cash_reserve: unallocated cash
            total_invested: sum of allocations
            warnings: list of strings
            summary: dict with stats
    """
    max_position_pct = config.get(
        "risk_management", "position_sizing", "max_portfolio_pct", default=10
    ) / 100
    max_sector_pct = config.get(
        "risk_management", "position_sizing", "max_sector_pct", default=30
    ) / 100

    # Filter to BUY and STRONG BUY only
    buy_recs = [
        r for r in recommendations
        if r["action"] in ("BUY", "STRONG BUY")
    ]

    if not buy_recs:
        return {
            "allocations": [],
            "cash_reserve": budget,
            "total_invested": 0,
            "warnings": ["No BUY signals found. Keeping 100% cash."],
            "summary": {
                "budget": budget,
                "num_positions": 0,
                "total_invested": 0,
                "cash_reserve": budget,
                "cash_pct": 100.0,
                "sectors": 0,
                "avg_score": 0,
                "sector_breakdown": {},
            },
        }

    # Calculate raw weights based on composite score
    # Higher score = more allocation
    min_threshold = config.get_scoring_thresholds().get("buy", 65)
    raw_weights = {}
    for rec in buy_recs:
        # Weight = how far above the buy threshold (squared for stronger emphasis)
        excess = max(1, rec["composite_score"] - min_threshold + 10)
        # STRONG BUY gets 1.5x weight boost
        if rec["action"] == "STRONG BUY":
            excess *= 1.5
        raw_weights[rec["ticker"]] = excess

    total_weight = sum(raw_weights.values())

    # Normalize and apply max position cap
    allocations = []
    sector_totals = {}
    total_invested = 0
    warnings = []

    # First pass: calculate ideal allocation
    ideal = {}
    for rec in buy_recs:
        ticker = rec["ticker"]
        pct = raw_weights[ticker] / total_weight
        # Cap at max position size
        pct = min(pct, max_position_pct)
        ideal[ticker] = pct

    # Normalize after capping
    ideal_total = sum(ideal.values())
    if ideal_total > 0:
        for ticker in ideal:
            ideal[ticker] /= ideal_total

    # Second pass: allocate dollars, enforce sector limits, calculate shares
    for rec in buy_recs:
        ticker = rec["ticker"]
        sector = rec.get("sector", "Unknown")
        risk = rec.get("risk_management", {})
        price = risk.get("current_price", 0)

        if price <= 0:
            continue

        # Dollar allocation
        dollar_amount = budget * ideal[ticker]

        # Enforce max position size
        max_position = budget * max_position_pct
        dollar_amount = min(dollar_amount, max_position)

        # Enforce sector cap
        current_sector_total = sector_totals.get(sector, 0)
        max_sector = budget * max_sector_pct
        if current_sector_total + dollar_amount > max_sector:
            dollar_amount = max(0, max_sector - current_sector_total)
            if dollar_amount <= 0:
                warnings.append(
                    f"Skipped {ticker}: sector '{sector}' at cap ({max_sector_pct*100:.0f}%)"
                )
                continue

        # Calculate shares (whole shares only)
        shares = int(dollar_amount / price)
        if shares <= 0:
            continue

        actual_amount = shares * price
        sector_totals[sector] = sector_totals.get(sector, 0) + actual_amount
        total_invested += actual_amount

        # Get order recommendation
        order = suggest_order_type(rec, risk)

        sl = risk.get("stop_loss", {})
        tp = risk.get("take_profit", {})

        allocations.append({
            "ticker": ticker,
            "name": rec.get("name", ticker),
            "action": rec["action"],
            "score": rec["composite_score"],
            "sector": sector,
            "price": price,
            "shares": shares,
            "dollar_amount": round(actual_amount, 2),
            "allocation_pct": round(actual_amount / budget * 100, 2),
            "stop_loss": sl.get("price"),
            "stop_loss_pct": sl.get("pct_from_current"),
            "take_profit": tp.get("price"),
            "take_profit_pct": tp.get("pct_from_current"),
            "risk_reward": risk.get("risk_reward_ratio", 0),
            "order_type": order["type"],
            "order_detail": order["detail"],
            "order_price": order.get("price"),
        })

    cash_reserve = budget - total_invested

    # Summary stats
    summary = {
        "budget": budget,
        "num_positions": len(allocations),
        "total_invested": round(total_invested, 2),
        "cash_reserve": round(cash_reserve, 2),
        "cash_pct": round(cash_reserve / budget * 100, 2) if budget > 0 else 0,
        "sectors": len(sector_totals),
        "avg_score": round(
            np.mean([a["score"] for a in allocations]), 1
        ) if allocations else 0,
        "sector_breakdown": {
            sector: round(total / budget * 100, 1)
            for sector, total in sector_totals.items()
        },
    }

    return {
        "allocations": allocations,
        "cash_reserve": round(cash_reserve, 2),
        "total_invested": round(total_invested, 2),
        "warnings": warnings,
        "summary": summary,
    }


def suggest_order_type(rec, risk):
    """
    Suggest the best order type for entering a position.

    Order types:
        Market:         Buy immediately at current price
        Limit:          Buy only at specified price or better
        Stop:           Buy when price rises to trigger (breakout)
        Stop Limit:     Stop trigger + limit price (precise breakout)
        Trailing Stop:  For existing positions, protect gains

    Args:
        rec: recommendation dict
        risk: risk_management dict from recommendation

    Returns:
        dict with type, detail, price (if applicable)
    """
    action = rec["action"]
    signals = rec.get("all_signals", [])
    score = rec["composite_score"]
    current_price = risk.get("current_price", 0)
    sl = risk.get("stop_loss", {})
    tp = risk.get("take_profit", {})

    # Classify the signal environment
    has_breakout = any(
        "squeeze" in s.get("detail", "").lower()
        or "breakout" in s.get("detail", "").lower()
        for s in signals
    )
    has_support = any(
        s.get("source") == "Support" for s in signals
    )
    has_strong_momentum = any(
        "strong" in s.get("detail", "").lower()
        and s.get("source") in ("Momentum", "Trend", "TrendConfirm")
        for s in signals
    )
    has_volume_spike = any(
        "volume spike" in s.get("detail", "").lower() for s in signals
    )
    near_resistance = any(
        s.get("source") == "Resistance" for s in signals
    )

    # --- SELL / STRONG SELL ---
    if action in ("SELL", "STRONG SELL"):
        return {
            "type": "Market",
            "detail": "Sell at market - bearish signals, exit promptly",
        }

    # --- HOLD (already own) ---
    if action == "HOLD":
        if sl.get("price"):
            return {
                "type": "Trailing Stop",
                "detail": f"Set trailing stop at ${sl['price']:.2f} to protect gains",
                "price": sl.get("price"),
            }
        return {
            "type": "Trailing Stop",
            "detail": "Set trailing stop to protect existing position",
        }

    # --- BUY / STRONG BUY ---

    # STRONG BUY + strong momentum + volume = Market Order (don't miss it)
    if action == "STRONG BUY" and has_strong_momentum and has_volume_spike:
        return {
            "type": "Market",
            "detail": "Strong momentum + volume - enter at market to avoid missing the move",
        }

    # Breakout setup (squeeze, near resistance) = Stop Order above resistance
    if has_breakout or near_resistance:
        # Trigger slightly above current price to confirm breakout
        trigger = round(current_price * 1.02, 2)
        return {
            "type": "Stop",
            "detail": f"Breakout play - trigger at ${trigger:.2f} (2% above current) to confirm move",
            "price": trigger,
        }

    # Near support = Limit Order at support
    if has_support:
        # Set limit slightly above the stop loss (which is below support)
        limit_price = round(current_price * 0.98, 2)
        return {
            "type": "Limit",
            "detail": f"Near support - set limit at ${limit_price:.2f} for better entry",
            "price": limit_price,
        }

    # STRONG BUY with high score = Market Order
    if action == "STRONG BUY" and score >= 80:
        return {
            "type": "Market",
            "detail": "High-conviction signal - enter at market price",
        }

    # Default BUY = Limit Order slightly below current
    limit_price = round(current_price * 0.97, 2)
    return {
        "type": "Limit",
        "detail": f"Set limit at ${limit_price:.2f} (3% below current) for better entry",
        "price": limit_price,
    }
