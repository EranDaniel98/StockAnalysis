"""Tier-2 audit #19 + #26 regression for `_calculate_position_size`.

#19 — pre-fix the per-trade risk budget was hardcoded at 1% of
portfolio in the live recommender, while the backtest engine reads
``vol_target_risk_pct`` from strategy config. Two layers using two
different sizing rules for nominally the same strategy. After:
``risk_per_trade_pct`` flows through sizing_config; backtest's
``vol_target_risk_pct`` is also accepted (alias for legacy configs).

#26 — the "kelly" branch was mathematically degenerate. ``win_prob =
0.55`` hardcoded and ``avg_win == avg_loss == stop_pct`` gave
``kelly_fraction = (1*0.55 - 0.45) / 1 = 0.10`` always, half-Kelly to
5%, capped at max_pct. Same answer regardless of strategy. The branch
now refuses + falls back to fixed_fractional + logs a warning.
"""

from __future__ import annotations

import logging

import pytest

from src.scoring.recommender import _calculate_position_size


# --- #19: risk_per_trade_pct is configurable -------------------------------


def test_risk_budget_defaults_to_one_percent():
    """Sanity: no risk knob set anywhere → default to 1%, matching
    pre-fix hardcoded behavior."""
    result = _calculate_position_size(
        current_price=100.0,
        stop_loss={"price": 95.0, "pct_from_current": -5},
        sizing_config={
            "method": "fixed_fractional",
            "default_portfolio_value": 100_000,
            "max_portfolio_pct": 10,
        },
        action="BUY",
    )
    # 1% of 100k = $1000 risk budget. Stop is $5 below entry → 200 shares
    # by risk. Max position is 10% of 100k = $10k → 100 shares by cap.
    # min(200, 100) = 100 shares.
    assert result["recommended_shares"] == 100
    assert result["risk_budget_pct"] == pytest.approx(1.0)


def test_risk_budget_reads_risk_per_trade_pct():
    """New canonical key: ``risk_per_trade_pct`` overrides default."""
    result = _calculate_position_size(
        current_price=100.0,
        stop_loss={"price": 95.0, "pct_from_current": -5},
        sizing_config={
            "method": "fixed_fractional",
            "default_portfolio_value": 100_000,
            "max_portfolio_pct": 10,
            "risk_per_trade_pct": 0.5,  # half of default
        },
        action="BUY",
    )
    # 0.5% of 100k = $500. $5 stop → 100 shares by risk. Cap = 100. min = 100.
    assert result["recommended_shares"] == 100
    assert result["risk_budget_pct"] == pytest.approx(0.5)


def test_risk_budget_accepts_vol_target_risk_pct_alias():
    """Strategy yamls authored before #19 only set
    ``vol_target_risk_pct`` (the backtest's key). Live must accept the
    alias so the two layers stay in sync without a migration."""
    result = _calculate_position_size(
        current_price=100.0,
        stop_loss={"price": 95.0, "pct_from_current": -5},
        sizing_config={
            "method": "fixed_fractional",
            "default_portfolio_value": 100_000,
            "max_portfolio_pct": 100,  # high enough to not cap by max
            "vol_target_risk_pct": 2.0,  # backtest's name
        },
        action="BUY",
    )
    # 2.0% of 100k = $2000. $5 stop → 400 shares by risk.
    assert result["recommended_shares"] == 400
    assert result["risk_budget_pct"] == pytest.approx(2.0)


def test_risk_per_trade_pct_takes_precedence_over_alias():
    """If BOTH risk_per_trade_pct and vol_target_risk_pct are set,
    the canonical key wins. Prevents silent surprise when migrating."""
    result = _calculate_position_size(
        current_price=100.0,
        stop_loss={"price": 95.0, "pct_from_current": -5},
        sizing_config={
            "method": "fixed_fractional",
            "default_portfolio_value": 100_000,
            "max_portfolio_pct": 100,
            "risk_per_trade_pct": 0.5,   # canonical (should win)
            "vol_target_risk_pct": 5.0,  # alias (should lose)
        },
        action="BUY",
    )
    # 0.5% wins → $500 budget → 100 shares.
    assert result["recommended_shares"] == 100
    assert result["risk_budget_pct"] == pytest.approx(0.5)


# --- #26: kelly refused + fallback -----------------------------------------


def test_kelly_method_refused_and_falls_back(caplog):
    """Kelly is degenerate; recommender must refuse it, fall back to
    fixed_fractional, and emit a WARNING that surfaces in the log."""
    caplog.set_level(logging.WARNING)
    result = _calculate_position_size(
        current_price=100.0,
        stop_loss={"price": 95.0, "pct_from_current": -5},
        sizing_config={
            "method": "kelly",
            "default_portfolio_value": 100_000,
            "max_portfolio_pct": 10,
        },
        action="BUY",
    )
    assert result["method"] == "fixed_fractional"
    assert result["original_method"] == "kelly"
    assert "kelly_refused_reason" in result
    # The result must be a real fixed-fractional sizing, NOT zero shares.
    assert result["recommended_shares"] >= 1
    # Operator-visible warning.
    assert any("kelly" in r.message.lower() for r in caplog.records)


def test_kelly_no_longer_emits_kelly_fraction_field():
    """The legacy ``kelly_fraction`` field is no longer emitted (the
    branch that computed it is gone). Pin so a future caller doesn't
    accidentally re-add it without re-validating the math."""
    result = _calculate_position_size(
        current_price=100.0,
        stop_loss={"price": 95.0, "pct_from_current": -5},
        sizing_config={
            "method": "kelly",
            "default_portfolio_value": 100_000,
            "max_portfolio_pct": 10,
        },
        action="BUY",
    )
    assert "kelly_fraction" not in result


# --- general sanity --------------------------------------------------------


def test_sell_action_returns_zero_shares():
    """Behavior preserved: SELL/HOLD never recommends shares."""
    for action in ("SELL", "STRONG SELL", "HOLD"):
        result = _calculate_position_size(
            current_price=100.0,
            stop_loss={"price": 95.0, "pct_from_current": -5},
            sizing_config={
                "method": "fixed_fractional",
                "default_portfolio_value": 100_000,
                "max_portfolio_pct": 10,
            },
            action=action,
        )
        assert result["recommended_shares"] == 0
        assert result["dollar_amount"] == 0
