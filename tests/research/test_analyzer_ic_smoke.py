"""End-to-end synthetic-data smoke test for _compute_factor_stats.

We construct a tiny panel where the factor is HIGHLY correlated with
the forward 5-day return (factor = future_return + small noise). The
script should produce a positive IC and the verdict math should flag
it as a real signal. A bug in the alphalens wiring (column-name
mismatch, factor-series alignment, panel pivot) would either crash or
return IC≈0 even with a perfect factor; the test pins it.

We do NOT exercise the heavy main() — that depends on yfinance, the
config loader, and 1000 tickers of price history. The synthetic test
is the cheapest thing that proves the math from panel → IC is wired
correctly end-to-end.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.analyzer_ic_report import _compute_factor_stats


def _build_synthetic_panel_and_prices(
    n_tickers: int = 20,
    n_weeks: int = 60,
    seed: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build a panel where `technical` strongly predicts forward 5D
    return.

    Returns:
      panel: long-form with columns (date, ticker, technical, composite)
      prices: wide Close-price matrix indexed by business day, columns=tickers
    """
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2022-01-03")
    # Weekly rebalance schedule
    rebalance_dates = pd.date_range(start=start, periods=n_weeks, freq="W-MON")
    # Daily price index covers the entire window + 30 days forward runway
    price_idx = pd.bdate_range(
        start=start - pd.Timedelta(days=7),
        end=rebalance_dates[-1] + pd.Timedelta(days=45),
    )

    tickers = [f"T{i:02d}" for i in range(n_tickers)]

    # Build daily prices: each ticker gets its own random walk
    prices = pd.DataFrame(index=price_idx, columns=tickers, dtype=float)
    for t in tickers:
        log_returns = rng.normal(loc=0.0002, scale=0.02, size=len(price_idx))
        prices[t] = 100.0 * np.exp(np.cumsum(log_returns))

    # Build the panel: at each rebalance date, technical = future 5D
    # return + small noise. That gives a strong positive IC.
    rows = []
    for d in rebalance_dates:
        try:
            d_idx = price_idx.get_loc(d)
        except KeyError:
            # date isn't a business day — snap to next available
            d_idx = price_idx.searchsorted(d)
            if d_idx >= len(price_idx):
                continue
            d = price_idx[d_idx]
        if d_idx + 5 >= len(price_idx):
            continue
        d_plus5 = price_idx[d_idx + 5]
        for t in tickers:
            p_now = prices.at[d, t]
            p_future = prices.at[d_plus5, t]
            fwd5 = p_future / p_now - 1.0
            # Factor leads forward return cleanly, with small noise
            technical = fwd5 * 1000.0 + rng.normal(0, 1.0)
            rows.append({
                "date": d,
                "ticker": t,
                "technical": technical,
                "composite": technical,
            })

    panel = pd.DataFrame(rows)
    return panel, prices


@pytest.fixture(scope="module")
def synthetic_factor_panel():
    return _build_synthetic_panel_and_prices()


def test_compute_factor_stats_returns_positive_ic_for_perfect_factor(
    synthetic_factor_panel,
):
    panel, prices = synthetic_factor_panel
    stats = _compute_factor_stats(
        panel, prices, "technical",
        periods=(5,), quantiles=5,
    )
    assert stats is not None, "alphalens pipeline returned None on a clean panel"
    horizon = stats["by_horizon"].get("5D")
    assert horizon is not None, "5D horizon stats missing"
    # The factor IS the forward return + noise → IC must be strongly positive.
    assert horizon["ic_mean"] > 0.3, (
        f"Expected strong positive IC for perfect factor, got "
        f"{horizon['ic_mean']:.4f}"
    )
    assert horizon["t_stat"] > 2, "t-stat should be highly significant"
    # Top-minus-bottom spread should also be positive (top quintile > bottom).
    assert horizon["top_minus_bottom_pct"] > 0, (
        "Top-quintile spread should be positive when factor predicts returns"
    )


def test_compute_factor_stats_missing_factor_returns_none(synthetic_factor_panel):
    panel, prices = synthetic_factor_panel
    out = _compute_factor_stats(
        panel, prices, "this_column_does_not_exist",
        periods=(5,), quantiles=5,
    )
    assert out is None


def test_compute_factor_stats_skips_when_too_few_observations(synthetic_factor_panel):
    _, prices = synthetic_factor_panel
    # Tiny panel — under the 100-obs floor
    tiny = pd.DataFrame({
        "date": pd.date_range("2022-01-03", periods=5, freq="W-MON"),
        "ticker": ["T00"] * 5,
        "technical": [1.0, 2.0, 3.0, 4.0, 5.0],
    })
    out = _compute_factor_stats(
        tiny, prices, "technical",
        periods=(5,), quantiles=5,
    )
    assert out is None
