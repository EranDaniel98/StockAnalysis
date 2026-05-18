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
    atr_bracket_levels,
    percentage_bracket_levels,
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
