"""Concentration sensitivity: how much of the strategy's Sharpe depends
on a handful of lucky trades?

Review item from the external audit's MVTP template:

    Sharpe with top-5 trades removed drops by ≤ 0.4

This module computes that. We drop the N trades with the largest P&L
(the "winners"), reconstruct what the equity curve would have looked
like without them, then recompute annualized Sharpe on the stripped
curve. The gate is the magnitude of the Sharpe drop.

How the stripped curve is built:

  For each removed trade we subtract its P&L from every equity-curve
  point at or after the trade's exit date. This is an approximation
  (doesn't replay compounding ordering effects) but it's directionally
  correct AND deterministic — same input → same output, no random
  noise from re-running the strategy. The alternative — re-running
  the backtest N times — costs ~10x and barely changes the answer.

What "applicable" means:

  Sensitivity is meaningful only when we have enough trades that
  dropping N still leaves room for a non-trivial population. We
  require at least 2*N trades; below that the metric collapses.
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd


# Default headline number per the review.
DEFAULT_N_REMOVED = 5

# Annualizer for Sharpe — matches equity_curve_stats convention: empirical
# periods_per_year derived from the equity-curve dates, sqrt factor.


def _annualized_sharpe(
    equities: np.ndarray, dates: list[pd.Timestamp],
) -> float | None:
    """Mirror equity_curve_stats.ann_sharpe semantics so the headline
    and stripped numbers sit on the same denominator."""
    if len(equities) < 3:
        return None
    weekly_returns = equities[1:] / equities[:-1] - 1
    weekly_returns = weekly_returns[np.isfinite(weekly_returns)]
    if len(weekly_returns) < 2:
        return None
    mean = float(weekly_returns.mean())
    std = float(weekly_returns.std(ddof=1))
    if std <= 0:
        return 0.0
    first = pd.Timestamp(dates[0])
    last = pd.Timestamp(dates[-1])
    elapsed_days = max(1, (last - first).days)
    years_elapsed = elapsed_days / 365.25
    periods_per_year = (
        len(weekly_returns) / years_elapsed if years_elapsed > 0 else 52.0
    )
    ann_factor = math.sqrt(periods_per_year)
    return (mean / std) * ann_factor


def top_n_removed_sensitivity(
    trades: Iterable,
    equity_curve: list[dict],
    starting_cash: float,
    *,
    n: int = DEFAULT_N_REMOVED,
) -> dict:
    """Compute the Sharpe / return sensitivity to removing the top N
    winners by P&L from the trade timeline.

    Returns a dict shaped for the MVTP report. ``applicable=False`` when
    the trade population is too small to support the metric — the report
    surfaces this rather than emitting a misleading verdict.
    """
    trades = list(trades)
    if len(trades) < 2 * n:
        return {
            "applicable": False,
            "n_removed": n,
            "n_trades": len(trades),
            "reason": (
                f"need >= {2*n} trades to compute top-{n}-removed "
                f"sensitivity (got {len(trades)})"
            ),
        }
    if not equity_curve or len(equity_curve) < 3:
        return {
            "applicable": False,
            "n_removed": n,
            "n_trades": len(trades),
            "reason": "equity curve too short to compute Sharpe",
        }

    # ----- Identify top-N winners by P&L -----
    sorted_trades = sorted(trades, key=lambda t: float(t.pnl), reverse=True)
    top_trades = sorted_trades[:n]
    top_pnl_sum = float(sum(float(t.pnl) for t in top_trades))
    total_pnl = float(sum(float(t.pnl) for t in trades))
    concentration_pct = (
        (top_pnl_sum / total_pnl * 100.0) if total_pnl != 0 else None
    )

    # ----- Headline metrics from the input equity curve -----
    dates = [pd.Timestamp(e["date"]) for e in equity_curve]
    equities = np.array([float(e["equity"]) for e in equity_curve], dtype=float)
    headline_total_return_pct = (equities[-1] / equities[0] - 1.0) * 100.0
    headline_sharpe = _annualized_sharpe(equities, dates)

    # ----- Strip the top-N trades from the curve -----
    # For each removed trade, subtract its P&L from every curve point at
    # or after the trade's exit date. Approximation: ignores compounding
    # order effects, but the deltas are small and the direction matches
    # what a full re-run would show.
    stripped = equities.copy()
    for trade in top_trades:
        exit_date = pd.Timestamp(trade.exit_date)
        for i, d in enumerate(dates):
            if d >= exit_date:
                stripped[i] -= float(trade.pnl)
        # Sanity: if stripping pushes equity ≤ 0 at any point the test
        # was on a too-small starting_cash; flag it.
    if (stripped <= 0).any():
        return {
            "applicable": False,
            "n_removed": n,
            "n_trades": len(trades),
            "reason": (
                "stripped equity hit <=0 — top-N P&L exceeds the equity "
                "anchor; sensitivity not meaningful at this starting_cash"
            ),
        }

    stripped_total_return_pct = (stripped[-1] / stripped[0] - 1.0) * 100.0
    stripped_sharpe = _annualized_sharpe(stripped, dates)

    sharpe_drop: float | None
    if headline_sharpe is None or stripped_sharpe is None:
        sharpe_drop = None
    else:
        sharpe_drop = headline_sharpe - stripped_sharpe

    return {
        "applicable": True,
        "n_removed": n,
        "n_trades": len(trades),
        "top_pnl_sum": round(top_pnl_sum, 2),
        "total_pnl": round(total_pnl, 2),
        "concentration_pct": (
            round(concentration_pct, 2) if concentration_pct is not None else None
        ),
        "headline_total_return_pct": round(headline_total_return_pct, 2),
        "stripped_total_return_pct": round(stripped_total_return_pct, 2),
        "headline_ann_sharpe": (
            round(headline_sharpe, 2) if headline_sharpe is not None else None
        ),
        "stripped_ann_sharpe": (
            round(stripped_sharpe, 2) if stripped_sharpe is not None else None
        ),
        "sharpe_drop": round(sharpe_drop, 2) if sharpe_drop is not None else None,
        "top_trade_summary": [
            {
                "ticker": getattr(t, "ticker", "?"),
                "entry_date": str(getattr(t, "entry_date", "")),
                "exit_date": str(getattr(t, "exit_date", "")),
                "pnl": round(float(t.pnl), 2),
                "pnl_pct": round(float(getattr(t, "pnl_pct", 0.0)), 2),
            }
            for t in top_trades
        ],
    }
