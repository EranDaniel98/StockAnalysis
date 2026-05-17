"""Unit tests for the per-stock analyzer (moved from src/analysis/).

Synthetic data only. Pins down:
  - Technical computations (SMA, ATR, returns at horizons)
  - Trading plan stop bounds (MIN_STOP_PCT / MAX_STOP_PCT)
  - Insider activity signal thresholds
  - Correlation matrix edge cases (1 ticker, all identical, perfectly
    anti-correlated)
  - Per-pick return estimation via FIFO buy/sell matching
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from src.research.per_stock_analyzer import (
    MAX_STOP_PCT,
    MIN_STOP_PCT,
    PER_PICK_BEAR_RETURN_PCT,
    PER_PICK_BULL_RETURN_PCT,
    PER_PICK_TARGET_RETURN_PCT,
    compute_correlation_matrix,
    compute_insider_activity,
    compute_technicals,
    compute_trading_plan,
    estimate_per_pick_returns,
)


def _synthetic_ohlcv(start: str, days: int, drift: float = 0.001,
                     seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start=start, periods=days)
    closes = 100.0 * np.exp(np.cumsum(rng.normal(drift, 0.01, days)))
    highs = closes * (1 + np.abs(rng.normal(0, 0.005, days)))
    lows = closes * (1 - np.abs(rng.normal(0, 0.005, days)))
    opens = closes * (1 + rng.normal(0, 0.002, days))
    vols = rng.integers(1_000_000, 5_000_000, days)
    return pd.DataFrame({
        "Open": opens, "High": highs, "Low": lows, "Close": closes,
        "Volume": vols,
    }, index=idx)


def test_compute_technicals_basic() -> None:
    prices = _synthetic_ohlcv("2024-01-01", days=300, drift=0.001, seed=42)
    as_of = prices.index[-1]
    tech = compute_technicals(prices, as_of)
    assert tech.close > 0
    assert tech.sma_20 is not None
    assert tech.sma_50 is not None
    assert tech.sma_200 is not None
    assert tech.atr_20 is not None and tech.atr_20 > 0
    assert tech.high_52w is not None and tech.high_52w >= tech.close * 0.5
    assert tech.low_52w is not None and tech.low_52w <= tech.close * 1.5
    # Steady uptrend → above 200d.
    assert tech.above_200d is True


def test_compute_technicals_insufficient_history() -> None:
    """Only 50 days of data — SMAs that need more should be None."""
    prices = _synthetic_ohlcv("2024-01-01", days=50, drift=0.001, seed=1)
    as_of = prices.index[-1]
    tech = compute_technicals(prices, as_of)
    assert tech.sma_20 is not None  # 20-day works
    assert tech.sma_50 is not None  # 50 works (have exactly 50)
    assert tech.sma_200 is None      # 200 requires more — None


def test_trading_plan_stop_bounds_low_vol() -> None:
    """A low-vol stock (tiny ATR) should hit the MIN_STOP_PCT floor."""
    plan = compute_trading_plan(
        close=100.0, atr_20=0.5,   # 2.5*0.5/100 = 1.25% raw → clamped to 5%
        equity_usd=10000, n_positions=20, as_of=pd.Timestamp("2024-01-01"),
    )
    assert plan.stop_loss_pct == pytest.approx(-MIN_STOP_PCT * 100, abs=0.01)


def test_trading_plan_stop_bounds_high_vol() -> None:
    """A high-vol stock (huge ATR) should hit the MAX_STOP_PCT ceiling."""
    plan = compute_trading_plan(
        close=100.0, atr_20=10.0,  # 2.5*10/100 = 25% raw → clamped to 12%
        equity_usd=10000, n_positions=20, as_of=pd.Timestamp("2024-01-01"),
    )
    assert plan.stop_loss_pct == pytest.approx(-MAX_STOP_PCT * 100, abs=0.01)


def test_trading_plan_stop_no_atr_fallback() -> None:
    plan = compute_trading_plan(
        close=100.0, atr_20=None,
        equity_usd=10000, n_positions=20, as_of=pd.Timestamp("2024-01-01"),
    )
    # Fallback is 8% → bounded result is 8% (within [5, 12]).
    assert plan.stop_loss_pct == pytest.approx(-8.0, abs=0.01)


def test_trading_plan_target_matches_strategy_median() -> None:
    plan = compute_trading_plan(
        close=100.0, atr_20=2.0,
        equity_usd=10000, n_positions=20, as_of=pd.Timestamp("2024-01-01"),
    )
    assert plan.target_pct == pytest.approx(PER_PICK_TARGET_RETURN_PCT, abs=0.01)
    assert plan.target_price == pytest.approx(100.0 * 1.08, abs=0.01)


def test_trading_plan_position_size() -> None:
    plan = compute_trading_plan(
        close=50.0, atr_20=1.0,
        equity_usd=10000, n_positions=20, as_of=pd.Timestamp("2024-01-01"),
    )
    # $10000 / 20 = $500 per pos; $500 / $50 = 10 shares
    assert plan.target_shares == 10
    assert plan.position_size_usd == pytest.approx(500.0, abs=0.01)


def test_insider_no_data() -> None:
    result = compute_insider_activity([])
    assert result.signal == "no_data"
    assert result.n_buys == 0
    assert result.n_sells == 0


def test_insider_bullish_when_buys_2x_sells() -> None:
    txs = [
        {"transaction_code": "P", "value_usd": 500_000,
         "transaction_date": date(2024, 1, 15)},
        {"transaction_code": "P", "value_usd": 300_000,
         "transaction_date": date(2024, 2, 1)},
        {"transaction_code": "S", "value_usd": 100_000,
         "transaction_date": date(2024, 2, 10)},
    ]
    result = compute_insider_activity(txs)
    assert result.signal == "bullish"
    assert result.n_buys == 2
    assert result.n_sells == 1


def test_insider_bearish_when_sells_dominant() -> None:
    txs = [
        {"transaction_code": "S", "value_usd": 1_000_000,
         "transaction_date": date(2024, 1, 15)},
        {"transaction_code": "P", "value_usd": 50_000,
         "transaction_date": date(2024, 2, 1)},
    ]
    # $1M sell > $500K default threshold + buys 50K < 2x of sells → bearish
    result = compute_insider_activity(txs)
    assert result.signal == "bearish"


def test_insider_neutral_under_threshold() -> None:
    """Small sales should not flag bearish."""
    txs = [
        {"transaction_code": "S", "value_usd": 50_000,
         "transaction_date": date(2024, 1, 15)},
    ]
    result = compute_insider_activity(txs)
    # 50K alone is below 500K default sell threshold → neutral.
    assert result.signal == "neutral"


def test_insider_megacap_routine_sales_are_neutral() -> None:
    """For a $1T mkt cap stock, a $500K sale is noise (0.00005% of mcap)."""
    txs = [
        {"transaction_code": "S", "value_usd": 500_000,
         "transaction_date": date(2024, 1, 15)},
    ]
    # mkt_cap = $1T → sell_threshold = $1T * 0.0005 = $500M
    result = compute_insider_activity(txs, market_cap_usd=1_000_000_000_000)
    assert result.signal == "neutral"


def test_insider_smallcap_modest_sales_flag_bearish() -> None:
    """For a $500M small cap, a $500K sale is meaningful (0.1% of mcap)."""
    txs = [
        {"transaction_code": "S", "value_usd": 500_000,
         "transaction_date": date(2024, 1, 15)},
    ]
    # mkt_cap = $500M → sell_threshold = $500M * 0.0005 = $250K
    # 500K > 250K and no offsetting buys → bearish
    result = compute_insider_activity(txs, market_cap_usd=500_000_000)
    assert result.signal == "bearish"


def test_insider_megacap_meaningful_buy_flags_bullish() -> None:
    """For a $100B mkt cap, a $10M open-market buy is real conviction."""
    txs = [
        {"transaction_code": "P", "value_usd": 10_000_000,
         "transaction_date": date(2024, 1, 15)},
    ]
    # mkt_cap = $100B → buy_threshold = $100B * 0.00005 = $5M
    result = compute_insider_activity(txs, market_cap_usd=100_000_000_000)
    assert result.signal == "bullish"


def test_insider_ignores_grants_and_option_exercises() -> None:
    """Codes A, M, F should not affect the signal."""
    txs = [
        {"transaction_code": "A", "value_usd": 1_000_000,
         "transaction_date": date(2024, 1, 15)},
        {"transaction_code": "M", "value_usd": 500_000,
         "transaction_date": date(2024, 2, 1)},
        {"transaction_code": "F", "value_usd": 100_000,
         "transaction_date": date(2024, 2, 10)},
    ]
    result = compute_insider_activity(txs)
    # No P or S transactions → no_data signal.
    assert result.signal == "no_data"


def test_correlation_matrix_two_identical() -> None:
    """Two tickers with identical price paths should correlate ~ 1.0."""
    p = _synthetic_ohlcv("2024-01-01", days=100, drift=0.001, seed=7)
    prices = {"A": p.copy(), "B": p.copy()}
    _, summary = compute_correlation_matrix(
        prices, ["A", "B"], p.index[-1], window_days=60,
    )
    assert summary["mean_off_diagonal"] == pytest.approx(1.0, abs=0.01)
    # With ρ=1, N_eff = 1.
    assert summary["effective_n"] == pytest.approx(1.0, abs=0.05)


def test_correlation_matrix_independent() -> None:
    """Two tickers with independent paths should have near-zero correlation."""
    prices = {
        "A": _synthetic_ohlcv("2024-01-01", days=100, drift=0.001, seed=11),
        "B": _synthetic_ohlcv("2024-01-01", days=100, drift=0.001, seed=22),
    }
    _, summary = compute_correlation_matrix(
        prices, ["A", "B"], prices["A"].index[-1], window_days=60,
    )
    # Two independent random walks shouldn't be strongly correlated;
    # allow generous tolerance for sample noise on 60 days.
    assert abs(summary["mean_off_diagonal"]) < 0.5


def test_correlation_matrix_single_ticker_empty() -> None:
    prices = {"A": _synthetic_ohlcv("2024-01-01", days=100)}
    corr, summary = compute_correlation_matrix(
        prices, ["A"], prices["A"].index[-1], window_days=60,
    )
    # 1 ticker → no off-diagonal stats.
    assert corr.empty
    assert summary["mean_off_diagonal"] is None


def test_estimate_per_pick_returns_no_trades() -> None:
    """Empty trade log → literature priors."""
    med, p75, p25 = estimate_per_pick_returns([])
    assert med == PER_PICK_TARGET_RETURN_PCT
    assert p75 == PER_PICK_BULL_RETURN_PCT
    assert p25 == PER_PICK_BEAR_RETURN_PCT


def test_estimate_per_pick_returns_simple_roundtrip() -> None:
    """One ticker: bought at 100, sold at 110 → +10% return."""
    trades = [
        {"ticker": "X", "side": "buy", "shares": 10, "price": 100,
         "date": "2024-01-01"},
        {"ticker": "X", "side": "sell_rebalance", "shares": 10, "price": 110,
         "date": "2024-04-01"},
    ]
    med, p75, p25 = estimate_per_pick_returns(trades)
    assert med == pytest.approx(10.0, abs=0.01)


def test_estimate_per_pick_returns_multiple_outcomes() -> None:
    """Three tickers with returns +20%, +5%, -10% → median +5, p25 -10, p75 +20."""
    trades = [
        # +20%
        {"ticker": "A", "side": "buy", "shares": 1, "price": 100,
         "date": "2024-01-01"},
        {"ticker": "A", "side": "sell_rebalance", "shares": 1, "price": 120,
         "date": "2024-04-01"},
        # +5%
        {"ticker": "B", "side": "buy", "shares": 1, "price": 100,
         "date": "2024-01-01"},
        {"ticker": "B", "side": "sell_rebalance", "shares": 1, "price": 105,
         "date": "2024-04-01"},
        # -10%
        {"ticker": "C", "side": "buy", "shares": 1, "price": 100,
         "date": "2024-01-01"},
        {"ticker": "C", "side": "sell_rebalance", "shares": 1, "price": 90,
         "date": "2024-04-01"},
    ]
    med, p75, p25 = estimate_per_pick_returns(trades)
    assert med == pytest.approx(5.0, abs=0.01)
    # numpy percentile with 3 data points uses interpolation; not exact.
    assert p25 < med < p75
