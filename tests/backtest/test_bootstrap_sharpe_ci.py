"""Bootstrap Sharpe CI tests (Tier 1 #3).

Pins:
  * bootstrap_cis returns ann_sharpe_ci when an equity_curve is supplied.
  * Without an equity_curve, ann_sharpe_ci is None (back-compat).
  * The CI's bounds bracket the point-estimate Sharpe ±loose tolerance
    on synthetic data with known true Sharpe.
  * Sparse equity curves (<3 points) return ann_sharpe_ci=None instead
    of crashing.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from src.backtest.metrics import bootstrap_cis, equity_curve_stats


@dataclass
class _StubTrade:
    """Minimal trade shape — bootstrap reads pnl + pnl_pct."""

    pnl: float
    pnl_pct: float


def _synthetic_equity_curve(n_weeks: int, weekly_mean: float, weekly_std: float,
                            seed: int = 42) -> list[dict]:
    """Generate a synthetic weekly equity curve with known Sharpe-shaped
    returns. Used to verify the bootstrap CI brackets the point estimate."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(loc=weekly_mean, scale=weekly_std, size=n_weeks)
    equity = 100_000.0
    out = []
    start = pd.Timestamp("2024-01-01")
    for i in range(n_weeks):
        out.append({
            "date": (start + pd.Timedelta(weeks=i)).strftime("%Y-%m-%d"),
            "equity": round(equity, 2),
        })
        equity *= (1.0 + returns[i])
    return out


def _trades(n: int, win_rate: float = 0.45) -> list[_StubTrade]:
    """N trades with ~win_rate fraction profitable. Real bootstrap needs
    at least 5 trades to compute."""
    rng = np.random.default_rng(seed=7)
    out = []
    for _ in range(n):
        is_win = rng.random() < win_rate
        pct = rng.normal(loc=3.0 if is_win else -1.5, scale=2.0)
        out.append(_StubTrade(pnl=pct * 100, pnl_pct=pct))
    return out


# --- back-compat: no equity_curve -> no Sharpe CI ---------------------------


def test_bootstrap_without_equity_curve_omits_sharpe_ci():
    out = bootstrap_cis(_trades(20), starting_cash=10_000.0, n_resamples=200)
    # New field always present, set to None when input doesn't allow.
    assert "ann_sharpe_ci" in out
    assert out["ann_sharpe_ci"] is None
    # Existing fields preserved:
    assert out["total_return_ci_pct"] is not None
    assert out["win_rate_ci_pct"] is not None


def test_bootstrap_too_few_trades_returns_none_sharpe_ci():
    """3-trade run skips the bootstrap entirely + returns None for every CI."""
    out = bootstrap_cis(_trades(3), starting_cash=10_000.0, n_resamples=200,
                        equity_curve=_synthetic_equity_curve(52, 0.002, 0.01))
    assert out["ann_sharpe_ci"] is None
    assert out["total_return_ci_pct"] is None


# --- Sharpe CI on synthetic curves ------------------------------------------


def test_sharpe_ci_brackets_point_estimate():
    """On synthetic 2-year curve with known weekly mean/std, the headline
    Sharpe (from equity_curve_stats) must lie inside the bootstrap CI."""
    eq = _synthetic_equity_curve(n_weeks=104, weekly_mean=0.003, weekly_std=0.02)
    headline = equity_curve_stats(eq, compound=True)["ann_sharpe"]
    out = bootstrap_cis(
        _trades(20),
        starting_cash=100_000.0,
        n_resamples=500,
        equity_curve=eq,
    )
    ci = out["ann_sharpe_ci"]
    assert ci is not None and len(ci) == 2
    lo, hi = ci
    assert lo <= headline <= hi, (
        f"headline Sharpe {headline} fell outside bootstrap CI {ci}"
    )


def test_sharpe_ci_wider_on_short_curve():
    """A 20-week curve has wider CI than a 200-week one with the same
    underlying distribution — small-sample uncertainty test."""
    eq_short = _synthetic_equity_curve(n_weeks=20, weekly_mean=0.003,
                                       weekly_std=0.02, seed=1)
    eq_long = _synthetic_equity_curve(n_weeks=200, weekly_mean=0.003,
                                      weekly_std=0.02, seed=1)
    out_short = bootstrap_cis(_trades(20), 100_000.0, n_resamples=500,
                              equity_curve=eq_short)
    out_long = bootstrap_cis(_trades(20), 100_000.0, n_resamples=500,
                             equity_curve=eq_long)
    short_width = out_short["ann_sharpe_ci"][1] - out_short["ann_sharpe_ci"][0]
    long_width = out_long["ann_sharpe_ci"][1] - out_long["ann_sharpe_ci"][0]
    assert short_width > long_width, (
        f"expected wider CI on short curve ({short_width}) than long "
        f"({long_width})"
    )


def test_truly_zero_std_curve_returns_zero_sharpe_ci():
    """An equity curve with literally identical points (zero variance) hits
    the divide-by-zero branch in the bootstrap and must return [0, 0],
    not raise. We round to the dollar so floating-point precision can't
    leak in microscopic variance and inflate Sharpe."""
    eq = []
    start = pd.Timestamp("2024-01-01")
    for i in range(20):
        eq.append({
            "date": (start + pd.Timedelta(weeks=i)).strftime("%Y-%m-%d"),
            "equity": 100_000.0,  # IDENTICAL every week — std==0 in every resample
        })
    out = bootstrap_cis(_trades(20), 100_000.0, n_resamples=200,
                        equity_curve=eq)
    ci = out["ann_sharpe_ci"]
    assert ci is not None
    assert ci == [0.0, 0.0]
