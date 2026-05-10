"""
Backtest metrics: per-bucket calibration, summary stats, vs-SPY comparison.
"""

import logging
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

BUCKET_ORDER = ["<50", "50-59", "60-69", "70-79", "80+"]


def calibration_table(closed_trades) -> list[dict]:
    """
    Group closed trades by score bucket. Returns one row per bucket with stats.
    """
    buckets: dict[str, list] = defaultdict(list)
    for t in closed_trades:
        buckets[t.score_bucket].append(t)

    rows = []
    for bucket in BUCKET_ORDER:
        trades = buckets.get(bucket, [])
        if not trades:
            rows.append({
                "bucket": bucket,
                "n": 0,
                "win_rate": None,
                "avg_return_pct": None,
                "median_return_pct": None,
                "avg_hold_days": None,
                "total_pnl": 0.0,
            })
            continue
        returns = [t.pnl_pct for t in trades]
        wins = sum(1 for r in returns if r > 0)
        rows.append({
            "bucket": bucket,
            "n": len(trades),
            "win_rate": round(wins / len(trades) * 100, 1),
            "avg_return_pct": round(float(np.mean(returns)), 2),
            "median_return_pct": round(float(np.median(returns)), 2),
            "avg_hold_days": round(float(np.mean([t.hold_days for t in trades])), 1),
            "total_pnl": round(sum(t.pnl for t in trades), 2),
        })
    return rows


def exit_reason_breakdown(closed_trades) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for t in closed_trades:
        counts[t.exit_reason] += 1
    return dict(counts)


def deployment_matched_spy_return(
    equity_curve: list[dict],
    spy_df: Optional[pd.DataFrame],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> Optional[float]:
    """
    Compound a SPY return weighted by the strategy's actual capital-deployment
    ratio each week. Removes the "I was in cash" advantage SPY-buy-hold has over
    a strategy that deploys gradually. The fair active-vs-passive comparison.
    """
    if not equity_curve or spy_df is None or spy_df.empty:
        return None
    spy = spy_df.copy()
    if not isinstance(spy.index, pd.DatetimeIndex):
        spy.index = pd.to_datetime(spy.index)
    if spy.index.tz is not None:
        spy.index = spy.index.tz_localize(None)
    spy = spy.loc[(spy.index >= start) & (spy.index <= end)]
    if len(spy) < 2:
        return None

    def _close_at_or_before(df, day):
        sub = df.loc[df.index <= day]
        if sub.empty:
            return None
        return float(sub["Close"].iloc[-1])

    cum = 1.0
    for i in range(len(equity_curve) - 1):
        e_t = equity_curve[i]
        e_next = equity_curve[i + 1]
        equity_t = e_t.get("equity", 0)
        cash_t = e_t.get("cash", 0)
        if equity_t <= 0:
            continue
        deployment = max(0.0, min(1.0, (equity_t - cash_t) / equity_t))
        spy_t = _close_at_or_before(spy, pd.Timestamp(e_t["date"]))
        spy_next = _close_at_or_before(spy, pd.Timestamp(e_next["date"]))
        if spy_t is None or spy_next is None or spy_t == 0:
            continue
        period_return = (spy_next / spy_t - 1) * deployment
        cum *= (1 + period_return)
    return (cum - 1) * 100


def summary_stats(
    closed_trades,
    starting_cash: float,
    ending_equity: float,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    spy_return_pct: Optional[float] = None,
    spy_deployment_matched_pct: Optional[float] = None,
    total_costs: Optional[dict] = None,
) -> dict:
    """Top-level backtest summary."""
    n = len(closed_trades)
    total_pnl = ending_equity - starting_cash
    total_return_pct = (ending_equity / starting_cash - 1) * 100 if starting_cash > 0 else 0
    days = max(1, (end_date - start_date).days)
    years = days / 365.25
    cagr_pct = ((ending_equity / starting_cash) ** (1 / years) - 1) * 100 if years > 0 and starting_cash > 0 else 0

    if n > 0:
        returns = np.array([t.pnl_pct for t in closed_trades])
        wins = int((returns > 0).sum())
        win_rate = wins / n * 100
        avg_win = float(returns[returns > 0].mean()) if wins > 0 else 0.0
        avg_loss = float(returns[returns < 0].mean()) if (n - wins) > 0 else 0.0
        expectancy = float(returns.mean())
        avg_hold = float(np.mean([t.hold_days for t in closed_trades]))
        # Sharpe approximation per trade (not annualized) — useful as relative metric
        sharpe = float(returns.mean() / returns.std()) if returns.std() > 0 else 0.0
    else:
        win_rate = 0.0
        avg_win = 0.0
        avg_loss = 0.0
        expectancy = 0.0
        avg_hold = 0.0
        sharpe = 0.0

    costs = total_costs or {}
    total_cost_paid = round(
        costs.get("commissions", 0.0) + costs.get("slippage", 0.0) + costs.get("regulatory", 0.0), 2
    )

    return {
        "n_trades": n,
        "starting_cash": round(starting_cash, 2),
        "ending_equity": round(ending_equity, 2),
        "total_pnl": round(total_pnl, 2),
        "total_return_pct": round(total_return_pct, 2),
        "cagr_pct": round(cagr_pct, 2),
        "win_rate_pct": round(win_rate, 1),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "expectancy_pct": round(expectancy, 2),
        "avg_hold_days": round(avg_hold, 1),
        "sharpe_per_trade": round(sharpe, 2),
        "spy_return_pct": round(spy_return_pct, 2) if spy_return_pct is not None else None,
        "alpha_vs_spy_pct": round(total_return_pct - spy_return_pct, 2) if spy_return_pct is not None else None,
        "spy_deployment_matched_pct": round(spy_deployment_matched_pct, 2) if spy_deployment_matched_pct is not None else None,
        "alpha_vs_spy_matched_pct": round(total_return_pct - spy_deployment_matched_pct, 2) if spy_deployment_matched_pct is not None else None,
        "total_costs_paid": total_cost_paid,
        "commissions_paid": round(costs.get("commissions", 0.0), 2),
        "slippage_cost": round(costs.get("slippage", 0.0), 2),
        "regulatory_fees": round(costs.get("regulatory", 0.0), 2),
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
    }


def verdict(calibration_rows: list[dict]) -> str:
    """
    Compare high-score bucket avg-return vs low-score bucket avg-return.
    Returns a short human-readable verdict.
    """
    high = [r for r in calibration_rows if r["bucket"] in ("70-79", "80+") and r["n"] > 0]
    low = [r for r in calibration_rows if r["bucket"] in ("<50", "50-59") and r["n"] > 0]

    if not high or not low:
        return "Insufficient sample in one or both buckets — run a longer/larger backtest."

    high_n = sum(r["n"] for r in high)
    low_n = sum(r["n"] for r in low)
    high_avg = sum(r["avg_return_pct"] * r["n"] for r in high) / high_n
    low_avg = sum(r["avg_return_pct"] * r["n"] for r in low) / low_n
    diff = high_avg - low_avg

    if high_n < 20 or low_n < 20:
        confidence = "weak (small samples)"
    elif high_n < 50 or low_n < 50:
        confidence = "moderate"
    else:
        confidence = "reasonable"

    if diff > 2:
        return (
            f"Score appears predictive: high-bucket avg {high_avg:+.2f}% vs "
            f"low-bucket avg {low_avg:+.2f}% (Δ={diff:+.2f}%, {confidence})."
        )
    if diff < -2:
        return (
            f"Score appears INVERSELY predictive: high {high_avg:+.2f}% vs "
            f"low {low_avg:+.2f}% (Δ={diff:+.2f}%, {confidence}). Investigate."
        )
    return (
        f"Score does not separate winners from losers: high {high_avg:+.2f}% vs "
        f"low {low_avg:+.2f}% (Δ={diff:+.2f}%, {confidence})."
    )
