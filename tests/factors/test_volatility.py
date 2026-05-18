"""Realized-vol factor + low_vol_filter tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.volatility import (
    DEFAULT_WINDOW,
    low_vol_filter,
    realized_vol_factor,
)


def _make_prices(volatility: float, n: int = 200,
                  start: float = 100.0, seed: int = 0) -> pd.DataFrame:
    """Synthetic GBM-ish price frame with target realized vol (annualized)."""
    rng = np.random.default_rng(seed)
    daily_sigma = volatility / np.sqrt(252)
    log_rets = rng.normal(loc=0.0, scale=daily_sigma, size=n)
    log_price = np.log(start) + np.cumsum(log_rets)
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame({"Close": np.exp(log_price)}, index=idx)


def test_realized_vol_factor_orders_by_volatility() -> None:
    prices = {
        "LOW":  _make_prices(volatility=0.10, seed=1),  # 10% vol
        "MID":  _make_prices(volatility=0.25, seed=2),  # 25% vol
        "HIGH": _make_prices(volatility=0.50, seed=3),  # 50% vol
    }
    panel = realized_vol_factor(prices, as_of=prices["LOW"].index[-1])
    assert list(panel["ticker"]) == ["LOW", "MID", "HIGH"]
    assert panel.iloc[0]["rank"] == 1
    assert panel.iloc[-1]["rank"] == 3


def test_realized_vol_factor_skips_thin_data() -> None:
    prices = {
        "A": _make_prices(volatility=0.20, n=200, seed=1),
        "B": _make_prices(volatility=0.20, n=5, seed=2),  # too few bars
    }
    panel = realized_vol_factor(prices, as_of=prices["A"].index[-1])
    assert "A" in set(panel["ticker"])
    assert "B" not in set(panel["ticker"])


def test_realized_vol_factor_handles_empty_prices() -> None:
    assert realized_vol_factor({}, as_of="2024-06-01").empty


def test_low_vol_filter_drops_top_vol_names() -> None:
    prices = {
        f"T{i}": _make_prices(volatility=0.05 + i * 0.05, seed=i)
        for i in range(10)
    }
    # Sorted ascending by vol: T0 (5%), T1 (10%), ..., T9 (50%)
    tickers = list(prices.keys())
    kept = low_vol_filter(
        prices, tickers, as_of=prices["T0"].index[-1], keep_pct=0.80,
    )
    # keep_pct=0.80 → bottom 80% of 10 names = 8 names.
    # The dropped names are the top 2 by vol: T8 (45%) and T9 (50%).
    assert "T9" not in kept
    assert "T8" not in kept
    assert "T0" in kept
    assert len(kept) == 8


def test_low_vol_filter_passes_through_tickers_without_data() -> None:
    prices = {
        "WITH": _make_prices(volatility=0.40, seed=1),
    }
    kept = low_vol_filter(
        prices, ["WITH", "MISSING"],
        as_of=prices["WITH"].index[-1], keep_pct=0.50,
    )
    # MISSING has no vol panel entry → pass-through.
    assert "MISSING" in kept


def test_low_vol_filter_empty_input_returns_empty() -> None:
    assert low_vol_filter({}, [], as_of="2024-06-01") == []
    assert low_vol_filter({}, ["A"], as_of="2024-06-01") == ["A"]


def test_default_window_matches_expectation() -> None:
    assert DEFAULT_WINDOW == 63  # quarterly rebalance cadence
