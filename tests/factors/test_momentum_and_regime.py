"""Tests for momentum + regime factors.

These are deterministic synthetic-data tests — no yfinance, no
network. They pin down the math (sign of momentum, lookahead
boundary, SMA threshold).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.factors.momentum import LOOKBACK_DAYS, SKIP_DAYS, momentum_12_1
from src.factors.regime import SMA_WINDOW, is_risk_on, trend_state_series


def _synthetic_price_series(
    start: str, days: int, drift: float = 0.0, seed: int = 0,
) -> pd.DataFrame:
    """Geometric Brownian-ish price path. drift is per-trading-day."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start=start, periods=days)
    returns = rng.normal(loc=drift, scale=0.01, size=days)
    closes = 100.0 * np.exp(np.cumsum(returns))
    return pd.DataFrame({"Close": closes}, index=idx)


def test_momentum_winner_outranks_loser() -> None:
    """Construction test: a strongly trending ticker beats a falling one.

    Drift of ±0.005/day over 231-day lookback dwarfs the 0.01/day vol
    (signal SNR ≈ 5x), so the sign is deterministic across seeds.
    """
    winner = _synthetic_price_series("2020-01-01", days=400, drift=+0.005, seed=1)
    loser = _synthetic_price_series("2020-01-01", days=400, drift=-0.005, seed=2)
    as_of = winner.index[-1]
    out = momentum_12_1({"WIN": winner, "LOSE": loser}, as_of)
    assert len(out) == 2
    win_rank = int(out.loc[out["ticker"] == "WIN", "rank"].iloc[0])
    lose_rank = int(out.loc[out["ticker"] == "LOSE", "rank"].iloc[0])
    assert win_rank < lose_rank
    assert out.loc[out["ticker"] == "WIN", "raw"].iloc[0] > 0
    assert out.loc[out["ticker"] == "LOSE", "raw"].iloc[0] < 0


def test_momentum_drops_tickers_without_enough_history() -> None:
    """Ticker with <252d of pre-as_of history gets dropped."""
    short = _synthetic_price_series("2024-01-01", days=100, drift=0.001, seed=3)
    long = _synthetic_price_series("2020-01-01", days=400, drift=0.001, seed=4)
    as_of = long.index[-1]
    out = momentum_12_1({"SHORT": short, "LONG": long}, as_of)
    assert set(out["ticker"]) == {"LONG"}


def test_momentum_skips_last_21_days() -> None:
    """A spike in the final 21 days should NOT change rank.

    Construction: WIN-A and WIN-B are identical for the first 379
    trading days; in the final 21 days A is flat and B spikes +50%.
    The 12-1 momentum factor reads neither's last-21d window, so the
    ranking must come from the prior 12-1 period — where they're
    identical. They should therefore tie.
    """
    base = _synthetic_price_series("2020-01-01", days=400, drift=0.0005, seed=10)
    a = base.copy()
    b = base.copy()
    # Last 21 trading days: A flat at the pre-period close; B spikes.
    last21_idx = b.index[-SKIP_DAYS:]
    b.loc[last21_idx, "Close"] = b["Close"].iloc[-SKIP_DAYS - 1] * 1.50
    a.loc[last21_idx, "Close"] = a["Close"].iloc[-SKIP_DAYS - 1]
    as_of = base.index[-1]
    out = momentum_12_1({"A": a, "B": b}, as_of)
    raw_a = float(out.loc[out["ticker"] == "A", "raw"].iloc[0])
    raw_b = float(out.loc[out["ticker"] == "B", "raw"].iloc[0])
    # Tolerance for FP rounding only — they ARE identical in the
    # 12-1 window.
    assert raw_a == pytest.approx(raw_b, abs=1e-12)


def test_momentum_empty_input_returns_empty_frame() -> None:
    out = momentum_12_1({}, pd.Timestamp("2023-01-01"))
    assert out.empty
    assert list(out.columns) == ["ticker", "raw", "rank", "z_score"]


def test_regime_risk_on_when_above_sma() -> None:
    """Steady-uptrend SPY should be risk-on once SMA is computable."""
    spy = _synthetic_price_series("2020-01-01", days=400, drift=0.001, seed=5)
    state = trend_state_series(spy)
    # First SMA_WINDOW - 1 rows are False (SMA not yet computable).
    assert state.iloc[:SMA_WINDOW - 1].sum() == 0
    # By the end of a steady uptrend, state should be True.
    assert state.iloc[-1] == True  # noqa: E712


def test_regime_risk_off_in_steady_downtrend() -> None:
    spy = _synthetic_price_series("2020-01-01", days=400, drift=-0.001, seed=6)
    state = trend_state_series(spy)
    # By the end of a steady downtrend, state should be False.
    assert state.iloc[-1] == False  # noqa: E712


def test_regime_is_risk_on_no_data_returns_false() -> None:
    spy = _synthetic_price_series("2020-01-01", days=400, drift=0.001, seed=7)
    # as_of before the first index date — no eligible data.
    result = is_risk_on(spy, "2019-01-01")
    assert result is False
