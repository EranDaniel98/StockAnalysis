"""Portfolio allocation + diversification + order-type advisor.

Moved from src/scoring/recommender.py:318-756 in Stream B slice 2 — these
are portfolio-level concerns, not single-ticker scoring concerns. The
recommender keeps the per-ticker pipeline (generate_recommendation,
_determine_action, _calculate_risk_management); portfolio operations
(allocate_portfolio, check_diversification, suggest_order_type) live here.

src/scoring/recommender.py re-exports these names for backward compat so
existing callers (src/main.py) keep working through Phase 0.
"""

from __future__ import annotations

import numpy as np

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


def allocate_portfolio(recommendations, budget, config, strategy=None):
    """
    Allocate a budget across BUY/STRONG BUY stocks using score-weighted sizing.

    Args:
        recommendations: list of recommendation dicts (sorted by score)
        budget: total dollar amount to invest
        config: Config object
        strategy: optional strategy dict for per-strategy threshold overrides

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
    thresholds = dict(config.get_scoring_thresholds())
    if strategy:
        thresholds.update(strategy.get("thresholds", {}) or {})
    min_threshold = thresholds.get("buy", 65)
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
        order = suggest_order_type(rec, risk, shares=shares)

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
            "order_steps": order.get("steps", []),
            "order_why": order.get("why", ""),
            "order_risk_summary": order.get("risk_summary", ""),
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


def suggest_order_type(rec, risk, shares=None):
    """
    Suggest the best order type with step-by-step broker instructions.

    Args:
        rec: recommendation dict
        risk: risk_management dict from recommendation
        shares: number of shares (optional, for concrete step instructions)

    Returns:
        dict with type, detail, price, steps, why, risk_summary
    """
    action = rec["action"]
    signals = rec.get("all_signals", [])
    score = rec["composite_score"]
    ticker = rec.get("ticker", "???")
    current_price = risk.get("current_price", 0)
    sl = risk.get("stop_loss", {})
    tp = risk.get("take_profit", {})
    sl_price = sl.get("price")
    tp_price = tp.get("price")

    shares_label = f"{shares} share{'s' if shares != 1 else ''} of" if shares else "shares of"

    # Helper: build risk summary string
    def _risk_summary():
        if not shares or not sl_price:
            return ""
        risk_per_share = abs(current_price - sl_price)
        reward_per_share = abs(tp_price - current_price) if tp_price else 0
        total_risk = round(risk_per_share * shares, 0)
        total_reward = round(reward_per_share * shares, 0) if tp_price else 0
        rr = risk.get("risk_reward_ratio", 0)
        parts = [f"Risk: ${total_risk:,.0f}"]
        if total_reward:
            parts.append(f"Reward: ${total_reward:,.0f}")
        if rr:
            parts.append(f"Ratio: {rr:.0f}:1")
        return " | ".join(parts)

    # Helper: after-fill steps (stop-loss + take-profit)
    def _after_fill_steps():
        steps = []
        if sl_price:
            steps.append(f"Once filled, immediately set a Sell Stop Loss at ${sl_price:.2f}")
        if tp_price:
            steps.append(f"Set a Sell Limit (take profit) at ${tp_price:.2f}")
        return steps

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
        steps = [
            f"Place a Market Sell Order for {shares_label} {ticker}",
            "Order will fill immediately at best available price",
        ]
        return {
            "type": "Market",
            "detail": "Sell at market - bearish signals, exit promptly",
            "steps": steps,
            "why": "Multiple bearish signals detected — exit promptly to limit losses",
            "risk_summary": "",
        }

    # --- HOLD (already own) ---
    if action == "HOLD":
        steps = [f"Set a Trailing Stop order for {ticker}"]
        if sl_price:
            steps[0] = f"Set a Trailing Stop at ${sl_price:.2f} for {ticker}"
            steps.append("This automatically follows the price up and sells if it drops back")
        steps.append("No new purchase needed — monitor the position")
        return {
            "type": "Trailing Stop",
            "detail": f"Set trailing stop at ${sl_price:.2f} to protect gains" if sl_price else "Set trailing stop to protect existing position",
            "price": sl_price,
            "steps": steps,
            "why": "Position is in HOLD territory — protect existing gains with a trailing stop",
            "risk_summary": "",
        }

    # --- BUY / STRONG BUY ---

    # STRONG BUY + strong momentum + volume = Market Order
    if action == "STRONG BUY" and has_strong_momentum and has_volume_spike:
        steps = [
            f"Place a Market Buy Order for {shares_label} {ticker}",
            "Order fills immediately at current market price",
        ] + _after_fill_steps()
        return {
            "type": "Market",
            "detail": "Strong momentum + volume - enter at market to avoid missing the move",
            "steps": steps,
            "why": "Strong momentum confirmed by volume spike — enter now to avoid missing the move",
            "risk_summary": _risk_summary(),
        }

    # Breakout setup = Stop Order above resistance
    if has_breakout or near_resistance:
        trigger = round(current_price * 1.02, 2)
        # Find resistance detail for explanation
        resist_info = ""
        for s in signals:
            if s.get("source") == "Resistance":
                resist_info = s.get("detail", "")
                break

        steps = [
            f"Place a Buy Stop Order for {shares_label} {ticker} at ${trigger:.2f}",
            f"Wait — order only fills if price breaks above ${trigger:.2f}",
        ] + _after_fill_steps()
        steps.append(f"If price never reaches ${trigger:.2f}, you don't buy and lose nothing")

        why = f"Price is near resistance (${current_price:.2f}) — buying now risks a rejection. Waiting for a breakout above ${trigger:.2f} confirms buyers have overwhelmed sellers"
        if resist_info:
            why = f"{resist_info} — buying at resistance risks a rejection. The Stop Order waits for a confirmed breakout above ${trigger:.2f}"

        return {
            "type": "Stop",
            "detail": f"Breakout play - trigger at ${trigger:.2f} (2% above current) to confirm move",
            "price": trigger,
            "steps": steps,
            "why": why,
            "risk_summary": _risk_summary(),
        }

    # Near support = Limit Order at support
    if has_support:
        limit_price = round(current_price * 0.98, 2)
        support_info = ""
        for s in signals:
            if s.get("source") == "Support":
                support_info = s.get("detail", "")
                break

        steps = [
            f"Place a Buy Limit Order for {shares_label} {ticker} at ${limit_price:.2f}",
            f"Order only fills if price dips to ${limit_price:.2f} or lower",
        ] + _after_fill_steps()
        steps.append(f"If price never dips to ${limit_price:.2f}, you can adjust the limit higher or wait")

        why = f"Price is near a support level — a Limit Order below current price gets you a better entry if it dips"
        if support_info:
            why = f"{support_info} — Limit Order catches a dip for a better entry price"

        return {
            "type": "Limit",
            "detail": f"Near support - set limit at ${limit_price:.2f} for better entry",
            "price": limit_price,
            "steps": steps,
            "why": why,
            "risk_summary": _risk_summary(),
        }

    # STRONG BUY with high score = Market Order
    if action == "STRONG BUY" and score >= 80:
        steps = [
            f"Place a Market Buy Order for {shares_label} {ticker}",
            "Order fills immediately at current market price",
        ] + _after_fill_steps()
        return {
            "type": "Market",
            "detail": "High-conviction signal - enter at market price",
            "steps": steps,
            "why": f"High-conviction signal (score {score:.0f}/100) — no need to wait for a better price",
            "risk_summary": _risk_summary(),
        }

    # Default BUY = Limit Order slightly below current
    limit_price = round(current_price * 0.97, 2)
    steps = [
        f"Place a Buy Limit Order for {shares_label} {ticker} at ${limit_price:.2f}",
        f"Order only fills at ${limit_price:.2f} or lower — saves ~3% vs buying now",
    ] + _after_fill_steps()
    steps.append(f"If price doesn't dip to ${limit_price:.2f} within a few days, consider raising the limit")

    return {
        "type": "Limit",
        "detail": f"Set limit at ${limit_price:.2f} (3% below current) for better entry",
        "price": limit_price,
        "steps": steps,
        "why": f"No urgency signals — a Limit Order 3% below current (${current_price:.2f}) gives a better entry price",
        "risk_summary": _risk_summary(),
    }
