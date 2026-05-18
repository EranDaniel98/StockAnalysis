"""ATR + percentage bracket-level tests.

Both helpers must produce a clean (stop, take_profit) pair with the
configured risk-reward, or return None when inputs don't support a clean
computation. Bracket orders go to the broker — a None return must never
silently round to a junk level.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.execution.risk_sizing import (
    BracketLevels,
    PositionPlan,
    atr_bracket_levels,
    is_position_flip,
    percentage_bracket_levels,
    size_position,
)


def _trending_ohlc(start: float = 100.0, n: int = 30) -> pd.DataFrame:
    """Synthetic OHLC frame with a steady $1/day drift + $1 intraday range."""
    rows = []
    for i in range(n):
        c = start + i * 0.5
        rows.append({
            "Open": c - 0.3,
            "High": c + 0.6,
            "Low":  c - 0.6,
            "Close": c,
        })
    return pd.DataFrame(rows)


def test_atr_bracket_returns_clean_levels() -> None:
    ohlc = _trending_ohlc(start=100.0, n=30)
    entry = float(ohlc["Close"].iloc[-1])
    levels = atr_bracket_levels(entry=entry, ohlc=ohlc,
                                atr_multiplier=2.0, risk_reward=3.0)
    assert levels is not None
    assert levels.basis == "atr"
    risk = entry - levels.stop
    reward = levels.take_profit - entry
    assert risk > 0
    assert reward == pytest.approx(3.0 * risk, rel=1e-3)


def test_atr_bracket_returns_none_with_insufficient_history() -> None:
    ohlc = _trending_ohlc(n=10)  # less than period+1 = 15
    levels = atr_bracket_levels(entry=110.0, ohlc=ohlc)
    assert levels is None


def test_atr_bracket_returns_none_when_missing_columns() -> None:
    df = pd.DataFrame({"Close": [100, 101, 102]})
    levels = atr_bracket_levels(entry=100.0, ohlc=df)
    assert levels is None


def test_atr_bracket_returns_none_when_entry_invalid() -> None:
    ohlc = _trending_ohlc(n=30)
    assert atr_bracket_levels(entry=0.0, ohlc=ohlc) is None
    assert atr_bracket_levels(entry=-1.0, ohlc=ohlc) is None


def test_atr_bracket_refuses_negative_stop() -> None:
    """If ATR is so wide that 2*ATR > entry, the stop would go negative.
    Refuse rather than ship a junk level."""
    ohlc = pd.DataFrame({
        "High": [100, 105, 80, 110, 70, 105, 90, 75, 120, 80,
                 110, 90, 100, 70, 130, 80],
        "Low":  [50, 50, 50, 50, 50, 50, 50, 50, 50, 50,
                 50, 50, 50, 50, 50, 50],
        "Close": [80] * 16,
    })
    levels = atr_bracket_levels(entry=10.0, ohlc=ohlc,
                                atr_multiplier=2.0, risk_reward=3.0)
    assert levels is None


def test_percentage_bracket_returns_clean_levels() -> None:
    levels = percentage_bracket_levels(entry=100.0, stop_pct=0.10,
                                       risk_reward=3.0)
    assert levels is not None
    assert levels.basis == "percentage"
    assert levels.stop == pytest.approx(90.0)
    assert levels.take_profit == pytest.approx(130.0)


def test_percentage_bracket_refuses_invalid_stop_pct() -> None:
    assert percentage_bracket_levels(entry=100.0, stop_pct=0.0) is None
    assert percentage_bracket_levels(entry=100.0, stop_pct=1.0) is None
    assert percentage_bracket_levels(entry=100.0, stop_pct=-0.05) is None


def test_bracket_levels_is_immutable() -> None:
    levels = BracketLevels(stop=90.0, take_profit=130.0, basis="atr")
    with pytest.raises(Exception):
        levels.stop = 80.0  # type: ignore[misc]


from src.execution.risk_sizing import (  # noqa: E402
    short_atr_bracket_levels,
    short_percentage_bracket_levels,
)


def test_short_atr_bracket_stop_above_tp() -> None:
    ohlc = _trending_ohlc(start=100.0, n=30)
    entry = float(ohlc["Close"].iloc[-1])
    levels = short_atr_bracket_levels(
        entry=entry, ohlc=ohlc, atr_multiplier=2.0, risk_reward=3.0,
    )
    assert levels is not None
    assert levels.stop > entry, "short stop must be ABOVE entry"
    assert levels.take_profit < entry, "short TP must be BELOW entry"
    assert levels.stop > levels.take_profit
    risk = levels.stop - entry
    reward = entry - levels.take_profit
    assert reward == pytest.approx(3.0 * risk, rel=1e-3)


def test_short_atr_refuses_when_tp_goes_negative() -> None:
    # Pathologically wide ATR on a low entry → 3x risk would go negative.
    ohlc = pd.DataFrame({
        "High": [100, 105, 80, 110, 70, 105, 90, 75, 120, 80,
                 110, 90, 100, 70, 130, 80],
        "Low":  [50, 50, 50, 50, 50, 50, 50, 50, 50, 50,
                 50, 50, 50, 50, 50, 50],
        "Close": [80] * 16,
    })
    levels = short_atr_bracket_levels(
        entry=10.0, ohlc=ohlc, atr_multiplier=2.0, risk_reward=3.0,
    )
    assert levels is None


def test_short_percentage_bracket_levels() -> None:
    levels = short_percentage_bracket_levels(
        entry=100.0, stop_pct=0.10, risk_reward=3.0,
    )
    assert levels is not None
    assert levels.stop == pytest.approx(110.0)
    # 3:1 RR: risk = 10, reward = 30 → TP = 70.
    assert levels.take_profit == pytest.approx(70.0)


def test_short_percentage_refuses_when_tp_negative() -> None:
    # stop_pct=0.5 → stop at 1.5x entry, risk=50, reward=150 → TP = -50.
    levels = short_percentage_bracket_levels(
        entry=100.0, stop_pct=0.5, risk_reward=3.0,
    )
    assert levels is None


# ── size_position: high-price-short footgun + general sizing ───────────


def test_size_long_within_slot() -> None:
    plan = size_position(
        price=100.0, per_slot=834.0, current_shares=0, is_long=True,
    )
    assert plan.skip_reason is None
    # int(834 // 100) = 8 shares
    assert plan.target_shares == 8
    assert plan.delta_shares == 8


def test_size_short_within_slot() -> None:
    plan = size_position(
        price=100.0, per_slot=834.0, current_shares=0, is_long=False,
    )
    assert plan.skip_reason is None
    assert plan.target_shares == -8
    assert plan.delta_shares == -8


def test_size_short_price_exceeds_slot_returns_skip() -> None:
    """The COST footgun: $1000 price vs $834 slot → previously silently
    sized to 0 and dropped the pick. Now must return a skip with reason."""
    plan = size_position(
        price=1000.0, per_slot=834.0, current_shares=0, is_long=False,
    )
    assert plan.skip_reason is not None
    assert "exceeds per-position slot" in plan.skip_reason
    assert plan.target_shares == 0
    assert plan.delta_shares == 0


def test_size_long_price_exceeds_slot_returns_skip() -> None:
    """Same skip path applies on the long side — a $1500 BRK.B with $834
    per-long would otherwise size to 0 silently."""
    plan = size_position(
        price=1500.0, per_slot=834.0, current_shares=0, is_long=True,
    )
    assert plan.skip_reason is not None
    assert plan.target_shares == 0


def test_size_held_position_at_high_price_resizes_to_zero() -> None:
    """If we already hold the high-price name, the plan computes a
    DELTA that closes it. We don't want ghost positions hanging around
    just because a re-open wouldn't fit the slot."""
    plan = size_position(
        price=1000.0, per_slot=834.0, current_shares=2, is_long=True,
    )
    # target=0, current=2, delta=-2 (sell 2 to close)
    assert plan.skip_reason is None
    assert plan.target_shares == 0
    assert plan.delta_shares == -2


def test_size_resize_existing_long_down() -> None:
    """Slot shrank from prior rebalance; resize the held position down."""
    plan = size_position(
        price=100.0, per_slot=500.0, current_shares=10, is_long=True,
    )
    # New target: int(500 // 100) = 5. Delta: 5 - 10 = -5.
    assert plan.target_shares == 5
    assert plan.delta_shares == -5
    assert plan.skip_reason is None


def test_size_flip_long_to_short() -> None:
    """Operator targets short, currently long → close long AND open
    short in one delta."""
    plan = size_position(
        price=100.0, per_slot=500.0, current_shares=5, is_long=False,
    )
    # target: -5, current: +5, delta: -10
    assert plan.target_shares == -5
    assert plan.delta_shares == -10


def test_size_zero_price_returns_skip() -> None:
    plan = size_position(
        price=0.0, per_slot=834.0, current_shares=0, is_long=True,
    )
    assert plan.skip_reason is not None
    assert "non_positive_price" in plan.skip_reason


def test_size_zero_slot_returns_skip() -> None:
    plan = size_position(
        price=100.0, per_slot=0.0, current_shares=0, is_long=True,
    )
    assert plan.skip_reason is not None
    assert "non_positive_slot" in plan.skip_reason


# ── is_position_flip ───────────────────────────────────────────────────


def test_flip_long_to_short() -> None:
    """Today's TSLA: current +4, target -2 → flip."""
    assert is_position_flip(current_shares=4, target_shares=-2) is True


def test_flip_short_to_long() -> None:
    """Symmetric: current -3, target +5 → flip."""
    assert is_position_flip(current_shares=-3, target_shares=5) is True


def test_no_flip_when_already_flat() -> None:
    """Fresh entry: current 0, target ±N is NOT a flip — clean entry."""
    assert is_position_flip(current_shares=0, target_shares=5) is False
    assert is_position_flip(current_shares=0, target_shares=-5) is False


def test_no_flip_when_target_zero() -> None:
    """Closing-only: current ±N, target 0 is NOT a flip — clean close."""
    assert is_position_flip(current_shares=4, target_shares=0) is False
    assert is_position_flip(current_shares=-3, target_shares=0) is False


def test_no_flip_when_same_side_resize() -> None:
    """Resizing within the same direction is NOT a flip."""
    assert is_position_flip(current_shares=10, target_shares=5) is False
    assert is_position_flip(current_shares=-10, target_shares=-5) is False
    assert is_position_flip(current_shares=5, target_shares=10) is False
    assert is_position_flip(current_shares=-5, target_shares=-10) is False
