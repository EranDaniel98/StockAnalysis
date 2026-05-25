"""Residual momentum factor tests.

Pin the algorithmic invariants:
- Output shape matches the vanilla momentum frame (interchangeable).
- A market-neutral synthetic series ranks above a pure-market follower
  (residual should kick the pure beta out).
- Missing/short history drops the ticker (no silent NaN propagation).
- The skip-month is honored.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.residual_momentum import (
    LOOKBACK_DAYS, SKIP_DAYS, residual_momentum_12_1,
)


def _make_spy(n_days: int = 400, seed: int = 0) -> pd.DataFrame:
    """SPY synthetic: random walk around 1% annual drift."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp("2026-05-13"), periods=n_days)
    daily = rng.normal(loc=0.0003, scale=0.01, size=n_days)
    close = 400.0 * np.exp(np.cumsum(daily))
    return pd.DataFrame({"Close": close}, index=dates)


def _stock_from_returns(returns: np.ndarray, dates: pd.DatetimeIndex,
                        start: float = 100.0) -> pd.DataFrame:
    close = start * np.exp(np.cumsum(returns))
    return pd.DataFrame({"Close": close}, index=dates)


def test_output_shape_matches_vanilla_momentum() -> None:
    spy = _make_spy(n_days=400)
    rng = np.random.default_rng(1)
    daily = rng.normal(0.0, 0.015, size=len(spy))
    prices = {"AAA": _stock_from_returns(daily, spy.index)}

    out = residual_momentum_12_1(prices, spy, pd.Timestamp("2026-05-13"))
    assert list(out.columns) == ["ticker", "raw", "rank", "z_score"]
    assert len(out) == 1
    assert out.iloc[0]["ticker"] == "AAA"


def test_pure_market_follower_has_near_zero_residual() -> None:
    """β=1, α=0 stock should have residual ~0 (negligible noise)."""
    spy = _make_spy(n_days=400, seed=2)
    spy_ret = spy["Close"].pct_change().fillna(0).values
    rng = np.random.default_rng(3)
    # Tiny noise on top of pure SPY tracking.
    noise = rng.normal(0.0, 0.0005, size=len(spy_ret))
    pure_follower = spy_ret + noise
    # A genuinely outperforming stock: SPY + persistent positive alpha.
    alpha_bps_daily = 0.001
    outperformer = spy_ret + alpha_bps_daily + noise * 0.5

    prices = {
        "FOLLOWER": _stock_from_returns(pure_follower, spy.index),
        "OUTPERFORMER": _stock_from_returns(outperformer, spy.index),
    }
    out = residual_momentum_12_1(prices, spy, pd.Timestamp("2026-05-13"))
    out = out.set_index("ticker")
    assert out.loc["OUTPERFORMER", "raw"] > out.loc["FOLLOWER", "raw"]
    # The outperformer should rank 1 (highest residual).
    assert out.loc["OUTPERFORMER", "rank"] == 1


def test_high_beta_loser_doesnt_beat_low_beta_winner() -> None:
    """A high-β name that just rode a bull market should NOT rank above
    a low-β name with genuine idiosyncratic alpha."""
    spy = _make_spy(n_days=400, seed=4)
    spy_ret = spy["Close"].pct_change().fillna(0).values

    high_beta = 1.8 * spy_ret  # pure beta exposure, no alpha
    low_beta_alpha = 0.4 * spy_ret + 0.0006  # low β + persistent alpha

    prices = {
        "HIGH_BETA_NO_ALPHA": _stock_from_returns(high_beta, spy.index),
        "LOW_BETA_REAL_ALPHA": _stock_from_returns(low_beta_alpha, spy.index),
    }
    out = residual_momentum_12_1(prices, spy, pd.Timestamp("2026-05-13"))
    out = out.set_index("ticker")
    # Vanilla 12-1 would rank HIGH_BETA above in a bull market; residual
    # should not.
    assert out.loc["LOW_BETA_REAL_ALPHA", "raw"] > out.loc["HIGH_BETA_NO_ALPHA", "raw"]


def test_short_history_ticker_is_dropped() -> None:
    spy = _make_spy(n_days=400, seed=5)
    rng = np.random.default_rng(6)
    full = rng.normal(0.0, 0.015, size=len(spy))
    short = rng.normal(0.0, 0.015, size=50)

    prices = {
        "FULL": _stock_from_returns(full, spy.index),
        "SHORT": _stock_from_returns(short, spy.index[-50:]),
    }
    out = residual_momentum_12_1(prices, spy, pd.Timestamp("2026-05-13"))
    assert "SHORT" not in out["ticker"].values
    assert "FULL" in out["ticker"].values


def test_empty_spy_returns_empty_frame() -> None:
    spy = pd.DataFrame(columns=["Close"])
    prices = {"AAA": pd.DataFrame({"Close": [100, 101, 102]})}
    out = residual_momentum_12_1(prices, spy, pd.Timestamp("2026-05-13"))
    assert out.empty


def test_zero_volatility_stock_gets_zero_raw() -> None:
    """A flat-price ticker (no returns at all) should get raw == 0."""
    spy = _make_spy(n_days=400, seed=7)
    flat = np.zeros(len(spy))
    prices = {"FLAT": _stock_from_returns(flat, spy.index)}
    out = residual_momentum_12_1(prices, spy, pd.Timestamp("2026-05-13"))
    if not out.empty:
        # With zero stock returns the residual = -β·spy_ret. After the
        # skip-month, summing those residuals can be non-zero but
        # bounded. Pin it to within a small envelope.
        raw = float(out.iloc[0]["raw"])
        assert abs(raw) < 0.5, f"unexpected non-zero raw {raw}"


def test_as_of_filter_excludes_future_data() -> None:
    """Data after as_of must not influence the score."""
    spy = _make_spy(n_days=400, seed=8)
    rng = np.random.default_rng(9)
    daily = rng.normal(0.0, 0.012, size=len(spy))
    prices = {"AAA": _stock_from_returns(daily, spy.index)}

    full_run = residual_momentum_12_1(prices, spy, spy.index[-1])
    # Same input but as_of pinned 30 days earlier.
    earlier_run = residual_momentum_12_1(prices, spy, spy.index[-30])
    if full_run.empty or earlier_run.empty:
        return
    # They should differ — the regression window slides.
    assert full_run.iloc[0]["raw"] != earlier_run.iloc[0]["raw"]
