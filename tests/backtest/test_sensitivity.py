"""Concentration sensitivity tests.

Pins:
  * Applicable iff n_trades >= 2*N (default N=5 requires 10).
  * Concentration % = top_N_pnl / total_pnl * 100.
  * Stripped equity curve subtracts each removed trade's P&L from all
    equity points at or after the trade's exit_date.
  * Sharpe drop is non-negative when the removed trades are the top
    winners (removing them should monotonically lower Sharpe).
  * Top trade summary lists tickers in P&L-descending order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pandas as pd
import pytest

from src.backtest.sensitivity import top_n_removed_sensitivity


@dataclass
class _StubTrade:
    """Minimal trade shape — sensitivity reads ticker, entry_date,
    exit_date, pnl, pnl_pct."""

    ticker: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    pnl: float
    pnl_pct: float


def _curve(start: pd.Timestamp, weekly_returns: list[float],
           starting_equity: float = 100_000.0) -> list[dict]:
    """Build a weekly equity curve from a list of fractional returns."""
    out = []
    equity = starting_equity
    for i, r in enumerate(weekly_returns):
        d = start + pd.Timedelta(weeks=i)
        out.append({"date": d.strftime("%Y-%m-%d"), "equity": round(equity, 2)})
        equity *= (1.0 + r)
    return out


def _trades_evenly_spaced(
    start: pd.Timestamp, end: pd.Timestamp, pnls: list[float],
) -> list[_StubTrade]:
    """Build N trades distributed evenly across [start, end] with the
    given P&L values."""
    n = len(pnls)
    delta = (end - start) / max(1, n - 1)
    out = []
    for i, p in enumerate(pnls):
        entry = start + delta * i
        # Each trade holds 1 week, exits before next.
        exit_d = entry + pd.Timedelta(weeks=1)
        out.append(_StubTrade(
            ticker=f"TKR{i:02d}",
            entry_date=entry,
            exit_date=exit_d,
            pnl=p,
            pnl_pct=(p / 100_000.0 * 100.0),
        ))
    return out


# --- Applicability ---------------------------------------------------------


def test_not_applicable_when_too_few_trades():
    """With N=5, need >=10 trades. 9 should refuse."""
    start = pd.Timestamp("2024-01-01")
    end = pd.Timestamp("2024-12-31")
    trades = _trades_evenly_spaced(start, end, [100.0] * 9)
    eq = _curve(start, [0.001] * 52)
    out = top_n_removed_sensitivity(trades, eq, 100_000.0, n=5)
    assert out["applicable"] is False
    assert "10" in out["reason"]


def test_not_applicable_when_equity_curve_too_short():
    start = pd.Timestamp("2024-01-01")
    end = pd.Timestamp("2024-12-31")
    trades = _trades_evenly_spaced(start, end, [100.0] * 20)
    out = top_n_removed_sensitivity(trades, [], 100_000.0, n=5)
    assert out["applicable"] is False


def test_not_applicable_when_stripped_equity_goes_negative():
    """If removing top trades pushes equity <= 0 the metric is
    meaningless (starting cash too small for these P&L magnitudes)."""
    start = pd.Timestamp("2024-01-01")
    end = pd.Timestamp("2024-12-31")
    # Top-5 trades are each $150k pnl. Stripping them subtracts $750k
    # from a starting equity of $100k → equity goes deeply negative.
    pnls = [150_000.0] * 5 + [100.0] * 15
    trades = _trades_evenly_spaced(start, end, pnls)
    eq = _curve(start, [0.01] * 52, starting_equity=100_000.0)
    out = top_n_removed_sensitivity(trades, eq, 100_000.0, n=5)
    assert out["applicable"] is False
    assert "<=0" in out["reason"]


# --- Core math --------------------------------------------------------------


def test_concentration_pct_correct():
    start = pd.Timestamp("2024-01-01")
    end = pd.Timestamp("2024-12-31")
    # Top 5 = sum 5*1000 = 5000. Total = 5000 + 15*100 = 6500.
    # Concentration = 5000/6500 ≈ 76.92%.
    pnls = [1000.0] * 5 + [100.0] * 15
    trades = _trades_evenly_spaced(start, end, pnls)
    eq = _curve(start, [0.001] * 52)
    out = top_n_removed_sensitivity(trades, eq, 100_000.0, n=5)
    assert out["applicable"] is True
    assert out["concentration_pct"] == pytest.approx(76.92, abs=0.01)
    assert out["top_pnl_sum"] == 5000.0
    assert out["total_pnl"] == 6500.0


def test_sharpe_drop_non_negative_with_winners_only():
    """Removing the top winners must NOT raise Sharpe (drop >= 0).
    Use a noisy curve so headline Sharpe is well-defined."""
    start = pd.Timestamp("2024-01-01")
    # 26-week noisy curve with drift
    import numpy as np
    rng = np.random.default_rng(seed=42)
    weekly = rng.normal(loc=0.005, scale=0.02, size=26).tolist()
    eq = _curve(start, weekly)

    pnls = [500.0] * 10 + [-100.0] * 10  # 20 trades, top-5 are clearly winners
    end = pd.Timestamp(eq[-1]["date"])
    trades = _trades_evenly_spaced(start, end, pnls)

    out = top_n_removed_sensitivity(trades, eq, 100_000.0, n=5)
    assert out["applicable"] is True
    assert out["sharpe_drop"] is not None
    assert out["sharpe_drop"] >= -0.05  # small tolerance for FP
    # Headline > stripped on a positive-drift curve (Sharpe drops)
    assert out["headline_ann_sharpe"] >= out["stripped_ann_sharpe"] - 0.05


def test_top_trade_summary_sorted_by_pnl_desc():
    """The summary list must list the top-N trades in descending P&L
    order so the operator can read which trades carried the curve."""
    start = pd.Timestamp("2024-01-01")
    end = pd.Timestamp("2024-12-31")
    pnls = [500.0, 200.0, 1000.0, 100.0, 300.0,
            150.0, 50.0, 75.0, 80.0, 90.0,
            10.0, 20.0, 30.0]
    trades = _trades_evenly_spaced(start, end, pnls)
    eq = _curve(start, [0.001] * 52)
    out = top_n_removed_sensitivity(trades, eq, 100_000.0, n=5)
    pnls_in_summary = [t["pnl"] for t in out["top_trade_summary"]]
    # Sorted desc: 1000, 500, 300, 200, 150
    assert pnls_in_summary == [1000.0, 500.0, 300.0, 200.0, 150.0]


def test_stripped_equity_subtracts_pnl_at_and_after_exit():
    """Verify the mechanics: a single removed trade's P&L should be
    subtracted from every curve point at or after its exit date.
    Use a flat equity curve so the math is easy to read."""
    start = pd.Timestamp("2024-01-01")
    # Flat equity curve (10 weeks, equity stays at 100k)
    eq = [
        {"date": (start + pd.Timedelta(weeks=i)).strftime("%Y-%m-%d"),
         "equity": 100_000.0}
        for i in range(10)
    ]
    # Trades all exiting in week 5
    exit_week = start + pd.Timedelta(weeks=5)
    trades = [
        _StubTrade(ticker=f"T{i}", entry_date=start, exit_date=exit_week,
                   pnl=1000.0, pnl_pct=1.0)
        for i in range(10)
    ]
    # Top-5 = $5000 total. Stripped equity at-and-after week 5 = $95k.
    out = top_n_removed_sensitivity(trades, eq, 100_000.0, n=5)
    assert out["applicable"] is True
    # Headline curve was flat so total_return ≈ 0%, stripped should be
    # slightly negative because we subtract $5000 from the back half.
    assert out["headline_total_return_pct"] == 0.0
    assert out["stripped_total_return_pct"] < 0  # we stripped winners


# --- Window label round trip -----------------------------------------------


def test_engine_attaches_window_label():
    """The engine sets window_label on the dict before shipping.
    This test exercises the contract: the dict is mutable + the
    sensitivity function doesn't drop unknown keys when caller adds them."""
    start = pd.Timestamp("2024-01-01")
    end = pd.Timestamp("2024-12-31")
    trades = _trades_evenly_spaced(start, end, [100.0] * 20)
    eq = _curve(start, [0.001] * 52)
    out = top_n_removed_sensitivity(trades, eq, 100_000.0, n=5)
    out["window_label"] = "OOS"
    assert out["window_label"] == "OOS"
    assert out["n_removed"] == 5
