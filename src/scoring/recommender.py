"""
Recommendation engine.
Generates buy/sell/hold recommendations with position sizing,
stop-loss/take-profit levels, and diversification checks.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# Time-stop fallback when a strategy config doesn't declare one.
# Reverted from 90 -> 365 on 2026-05-15 (see config/strategies.yaml comment
# on swing_trading.time_stop_days). The Stage-1 sweep that motivated a
# tighter default ran on a contaminated scoring engine; the post-silent-50
# clean-pipeline sweep shows no-time-stop outperforms. Keep the
# infrastructure live so re-enabling is a single-value edit when fresh
# evidence supports it.
_DEFAULT_TIME_STOP_DAYS = 365


def generate_recommendation(
    ticker: str,
    score_result: dict,
    price_data: Optional[pd.DataFrame],
    fundamentals: Optional[dict],
    config,
    strategy: Optional[dict] = None,
) -> dict:
    """Generate a full investment recommendation for a stock.

    Args:
        ticker: stock ticker symbol
        score_result: dict from scoring.engine.calculate_composite_score()
        price_data: DataFrame with OHLCV (None / empty → no risk plan)
        fundamentals: dict of fundamental data
        config: Config object
        strategy: optional strategy dict — if it contains a ``thresholds``
            block, those values override the global ones (per-strategy
            calibration)

    Returns:
        dict with action, confidence, reasoning, risk management params
    """
    from src.scoring.instrument_classifier import (
        MIN_HISTORY_DAYS,
        classify_instrument,
        evaluate_history,
    )

    composite = score_result["composite_score"]
    thresholds = dict(config.get_scoring_thresholds())
    if strategy:
        thresholds.update(strategy.get("thresholds", {}) or {})

    name = (fundamentals.get("name") if fundamentals else None) or ticker
    instrument = classify_instrument(ticker, name, fundamentals)
    insufficient, bars_available = evaluate_history(price_data)

    # --- Validity gates ---
    # Three independent reasons to refuse a confident Action:
    #   1. Engine reports score_valid=False (no required analyzer fired).
    #      Composite is the 50.0 placeholder, lifting it via PEAD or
    #      consensus would manufacture a BUY from zero signal.
    #   2. classify_instrument flagged a leveraged / inverse ETF or a
    #      non-stock instrument the composite isn't calibrated for.
    #   3. Insufficient price history (<252 daily bars, i.e. recent IPO
    #      or low-coverage ticker) so technical / statistical /
    #      alpha158 couldn't produce reliable sub-scores.
    #
    # When ANY gate fires we set ``action="HOLD"``/``confidence="None"``
    # and emit the per-gate flag so the FE can render a Data-Quality
    # warning panel above the action badge.
    score_valid = bool(score_result.get("score_valid", True))
    new_gates_failed = (instrument.warning is not None) or insufficient
    gates_failed = (not score_valid) or new_gates_failed
    if new_gates_failed:
        # New instrument / history gates: the system can't reliably
        # score this kind of input. Use confidence="None" so the FE
        # treats this as "we refuse" rather than "we ran but are
        # unsure" (which is what confidence="Low" historically meant).
        action, confidence = "HOLD", "None"
    elif not score_valid:
        # Pre-existing engine-validity gate. Composite is the 50.0
        # placeholder over a broken analyzer chain. Keep the legacy
        # "HOLD/Low" output here so existing callers / tests that
        # check this exact shape don't shift.
        action, confidence = "HOLD", "Low"
    else:
        action, confidence = _determine_action(composite, thresholds)

    # --- Collect Key Reasoning ---
    reasoning = _build_reasoning(score_result, fundamentals)

    # --- Risk Management ---
    risk = {}
    if price_data is not None and not price_data.empty and not gates_failed:
        # Skip risk-management math when gates failed — the entry/stop/
        # target levels would be misleading for an instrument the
        # system can't reliably score.
        risk = _calculate_risk_management(
            ticker, price_data, fundamentals, config, action, strategy
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
        # ``or X`` rather than .get("k", X) — the stub fundamentals
        # for non-stock instruments carry explicit ``None`` values
        # which .get's default doesn't catch.
        "name": (fundamentals.get("name") if fundamentals else None) or ticker,
        "sector": (fundamentals.get("sector") if fundamentals else None) or "Unknown",
        "industry": (fundamentals.get("industry") if fundamentals else None) or "Unknown",
        "market_cap": fundamentals.get("market_cap") if fundamentals else None,
        # Earnings calendar — unix epoch seconds (UTC). The FE decides
        # the display timezone. earnings_call_ts is typically 1 h
        # after earnings_announcement_ts; the window fields are only
        # set when yfinance has an approximate date range rather than
        # an exact timestamp.
        "earnings_announcement_ts": (
            fundamentals.get("earnings_announcement_ts") if fundamentals else None
        ),
        "earnings_call_ts": (
            fundamentals.get("earnings_call_ts") if fundamentals else None
        ),
        "earnings_window_start": (
            fundamentals.get("earnings_window_start") if fundamentals else None
        ),
        "earnings_window_end": (
            fundamentals.get("earnings_window_end") if fundamentals else None
        ),
        # Engine-level validity flags surfaced for downstream gates
        # (paper-trade, backtest, web UI). The FE renders a warning
        # whenever any of these flag a problem.
        "score_valid": score_valid,
        "error_count": int(score_result.get("error_count", 0) or 0),
        "error_slots": list(score_result.get("error_slots", []) or []),
        "analyzer_status": dict(score_result.get("analyzer_status", {}) or {}),
        "instrument_warning": instrument.warning,
        "instrument_warning_reason": instrument.reason,
        "insufficient_history": insufficient,
        "history_bars_available": bars_available,
        "history_bars_required": MIN_HISTORY_DAYS,
    }


def _determine_action(
    composite: float, thresholds: dict,
) -> tuple[str, str]:
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


def _build_reasoning(
    score_result: dict, fundamentals: Optional[dict],
) -> list[str]:
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


def _calculate_risk_management(
    ticker: str,
    price_data: pd.DataFrame,
    fundamentals: Optional[dict],
    config,
    action: str,
    strategy: Optional[dict] = None,
) -> dict:
    """Calculate position sizing, stop-loss, take-profit, and time-stop."""
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

    # --- Time stop (triple-barrier upper bound on hold duration) ---
    result["time_stop"] = _calculate_time_stop(strategy)

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


def _calculate_time_stop(strategy: dict | None, as_of: date | None = None) -> dict:
    """Triple-barrier time stop: forced exit after N calendar days from entry.

    Sourced from ``strategy['time_stop_days']`` so each strategy can match
    its alpha half-life (literature: PEAD ≈60d, Numerai/Alpha158 ≈20d,
    swing ≈10d, long-term/value/dividend ≈180d). Falls back to the legacy
    90-day default if the strategy config doesn't declare one.

    The returned dict ships the absolute `exit_date` so the UI doesn't
    have to know the analysis time. `as_of` is a parameter for testability;
    callers should leave it unset to use `date.today()`.
    """
    days = _DEFAULT_TIME_STOP_DAYS
    if strategy and isinstance(strategy, dict):
        v = strategy.get("time_stop_days")
        if isinstance(v, (int, float)) and v > 0:
            days = int(v)
    today = as_of or date.today()
    exit_date = today + timedelta(days=days)
    return {
        "method": "calendar",
        "days": days,
        "exit_date": exit_date.isoformat(),
        "detail": f"Force exit by {exit_date.isoformat()} ({days} calendar days)",
    }


def _calculate_stop_loss(price_data, current_price, sl_config):
    """Calculate stop-loss price using configured method.

    Tier-1 audit X#7: every fallback path must rewrite `method` and
    `detail` to reflect what was actually computed. The previous code
    left `method="support"` even when it fell back to a flat percentage,
    so the UI showed "below support $X.XX" when the stop was actually
    at a flat -5%. Mirror the take_profit fallback convention here.
    """
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
            # Fallback to percentage — record the override, otherwise the
            # UI claims an ATR-based level when ATR was actually 0.
            pct = sl_config.get("percentage", 5.0) / 100
            sl_price = current_price * (1 - pct)
            result["method"] = "percentage"
            result["price"] = round(sl_price, 2)
            result["pct_from_current"] = round(-pct * 100, 2)
            result["detail"] = (
                f"Fallback flat {pct*100:.1f}% (ATR was 0): ${sl_price:.2f}"
            )

    elif method == "percentage":
        pct = sl_config.get("percentage", 5.0) / 100
        sl_price = current_price * (1 - pct)
        result["price"] = round(sl_price, 2)
        result["pct_from_current"] = round(-pct * 100, 2)
        result["detail"] = f"Fixed {pct*100:.1f}%: ${sl_price:.2f}"

    elif method == "support":
        # Use nearest support level
        from src.scoring.analyzers.patterns import _find_support_resistance
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
            # Fallback to percentage — same override pattern as the ATR
            # branch above (audit X#7).
            pct = sl_config.get("percentage", 5.0) / 100
            sl_price = current_price * (1 - pct)
            result["method"] = "percentage"
            result["price"] = round(sl_price, 2)
            result["pct_from_current"] = round(-pct * 100, 2)
            result["detail"] = (
                f"Fallback flat {pct*100:.1f}% (no support found): ${sl_price:.2f}"
            )

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
        from src.scoring.analyzers.patterns import _find_support_resistance
        sr = _find_support_resistance(
            price_data["High"], price_data["Low"], price_data["Close"]
        )
        resistances = sr.get("resistance", [])
        # Pick the nearest resistance ABOVE current that gives at least
        # `min_risk_reward_ratio` payoff. The raw nearest resistance can
        # be 1-2% above current — useless when the stop sits 5-7% below
        # because the R/R math goes negative.
        min_rr = tp_config.get("min_risk_reward_ratio", 1.5)
        chosen = None
        if risk > 0:
            for r in resistances:
                if (r - current_price) / risk >= min_rr:
                    chosen = r
                    break

        if chosen is not None:
            result["price"] = round(chosen, 2)
            result["pct_from_current"] = round((chosen / current_price - 1) * 100, 2)
            result["detail"] = f"Resistance: ${chosen:.2f}"
        else:
            # Fall back to a flat R/R multiple. Record what actually
            # happened in `method` so the UI doesn't claim a chart-
            # derived level when it isn't one.
            ratio = tp_config.get("risk_reward_ratio", 3.0)
            tp_price = current_price + (risk * ratio)
            result["method"] = "risk_reward"
            result["price"] = round(tp_price, 2)
            result["pct_from_current"] = round((tp_price / current_price - 1) * 100, 2)
            result["detail"] = (
                f"R:R {ratio}:1 (no resistance ≥ {min_rr}:1) -> ${tp_price:.2f}"
            )

    return result


_SUPPORTED_SIZING_METHODS = ("fixed_fractional",)


def _calculate_position_size(
    current_price: float,
    stop_loss: dict,
    sizing_config: dict,
    action: str,
) -> dict:
    """Calculate recommended position size.

    Only ``fixed_fractional`` is implemented. The pre-2026-05-17
    revision carried a dead ``kelly`` branch that was always refused
    at runtime (the historical Kelly implementation was degenerate —
    win_prob=0.55 hardcoded, avg_win=avg_loss=stop_pct, yielding a
    constant 0.05 fraction regardless of strategy). The dead branch
    is gone; an unknown ``method`` now raises a clear ValueError at
    config-load time. To add Kelly, wire ``win_prob`` and
    ``avg_win``/``avg_loss`` to a per-strategy calibration table.

    Per-trade risk budget reads ``risk_per_trade_pct`` (default 1%);
    legacy ``vol_target_risk_pct`` is accepted as an alias so old
    strategy yamls don't need migration.
    """
    method = sizing_config.get("method", "fixed_fractional")
    if method not in _SUPPORTED_SIZING_METHODS:
        raise ValueError(
            f"Unsupported position_sizing.method={method!r}. "
            f"Supported: {_SUPPORTED_SIZING_METHODS}. "
            "See src/scoring/recommender.py for the rationale."
        )
    portfolio = sizing_config.get("default_portfolio_value", 100000)
    max_pct = sizing_config.get("max_portfolio_pct", 10) / 100
    # risk_per_trade_pct = ``vol_target_risk_pct`` alias, default 1%.
    risk_pct = (
        sizing_config.get("risk_per_trade_pct")
        or sizing_config.get("vol_target_risk_pct")
        or 1.0
    ) / 100
    result = {"method": method, "portfolio_value": portfolio}

    if action in ("SELL", "STRONG SELL", "HOLD"):
        result["recommended_shares"] = 0
        result["dollar_amount"] = 0
        result["pct_of_portfolio"] = 0
        return result

    sl_price = stop_loss.get("price", current_price * 0.95)
    risk_per_share = abs(current_price - sl_price)

    if method == "fixed_fractional":
        # Combine fixed-position cap with vol-target risk budget. The
        # two-cap design is intentional: max_position keeps any single
        # trade from blowing up the portfolio if the stop is wide, and
        # risk_budget keeps risk-per-trade proportional to account size
        # regardless of the stop distance.
        max_position = portfolio * max_pct
        if risk_per_share > 0:
            risk_budget = portfolio * risk_pct
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
        result["risk_budget_pct"] = round(risk_pct * 100, 4)

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
