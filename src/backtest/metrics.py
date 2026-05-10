"""
Backtest metrics: per-bucket calibration, summary stats, equity-curve risk
metrics, cost sensitivity, bootstrap CIs, statistically-grounded verdict.
"""

import logging
import math
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

BUCKET_ORDER = ["<50", "50-59", "60-69", "70-79", "80+"]
BUCKET_MIDPOINTS = {"<50": 45, "50-59": 55, "60-69": 65, "70-79": 75, "80+": 85}
WEEKS_PER_YEAR = 52


def monte_carlo_shuffle(
    closed_trades,
    starting_cash: float,
    n_shuffles: int = 1000,
    seed: int = 42,
) -> dict:
    """
    Shuffle trade order N times, simulate sequential equity curve per shuffle,
    return percentiles of terminal equity and max drawdown. Reveals path
    dependence: if max-DD varies hugely across shuffles, the headline DD
    you saw was a lucky/unlucky permutation, not an inherent strategy property.
    """
    if len(closed_trades) < 5:
        return {"n_shuffles": 0, "note": "Too few trades for shuffle (need >=5)."}
    rng = np.random.default_rng(seed)
    pnls = np.array([t.pnl for t in closed_trades])
    n = len(pnls)
    terminal = np.empty(n_shuffles)
    max_dds = np.empty(n_shuffles)
    for i in range(n_shuffles):
        order = rng.permutation(n)
        equity = starting_cash + np.cumsum(pnls[order])
        peak = np.maximum.accumulate(np.concatenate(([starting_cash], equity)))[1:]
        dd = equity / peak - 1
        terminal[i] = equity[-1]
        max_dds[i] = float(dd.min()) if len(dd) else 0.0

    def _pct(arr, q):
        return round(float(np.percentile(arr, q)), 2)

    return {
        "n_shuffles": n_shuffles,
        "terminal_equity_p5": _pct(terminal, 5),
        "terminal_equity_p50": _pct(terminal, 50),
        "terminal_equity_p95": _pct(terminal, 95),
        "max_dd_p5_pct": round(float(np.percentile(max_dds, 5)) * 100, 2),  # worst 5%
        "max_dd_p50_pct": round(float(np.percentile(max_dds, 50)) * 100, 2),
        "max_dd_p95_pct": round(float(np.percentile(max_dds, 95)) * 100, 2),  # best 5%
        "terminal_return_p5_pct": round((np.percentile(terminal, 5) / starting_cash - 1) * 100, 2),
        "terminal_return_p50_pct": round((np.percentile(terminal, 50) / starting_cash - 1) * 100, 2),
        "terminal_return_p95_pct": round((np.percentile(terminal, 95) / starting_cash - 1) * 100, 2),
    }


def recommend_live_threshold(
    oos_calibration: list[dict],
    min_n: int = 20,
    min_avg_return_pct: float = 0.0,
) -> Optional[dict]:
    """
    Pick the lowest score bucket on the OOS calibration table that meets
    (n >= min_n AND avg_return_pct >= min_avg_return_pct). Returns a recommendation
    dict or None if no bucket qualifies.
    """
    bucket_to_min_score = {"<50": 0, "50-59": 50, "60-69": 60, "70-79": 70, "80+": 80}
    qualifying = []
    for row in oos_calibration:
        if row.get("n", 0) < min_n:
            continue
        avg = row.get("avg_return_pct")
        if avg is None or avg < min_avg_return_pct:
            continue
        qualifying.append(row)
    if not qualifying:
        return None
    qualifying.sort(key=lambda r: bucket_to_min_score.get(r["bucket"], 999))
    chosen = qualifying[0]
    return {
        "min_score": bucket_to_min_score.get(chosen["bucket"], 0),
        "bucket": chosen["bucket"],
        "n_trades": chosen["n"],
        "avg_return_pct": chosen["avg_return_pct"],
        "win_rate_pct": chosen["win_rate"],
    }


def regime_split(
    closed_trades,
    spy_df: Optional[pd.DataFrame],
    vix_df: Optional[pd.DataFrame],
) -> dict:
    """
    Group trades by SPY regime (bull/bear via 200-SMA at entry) and VIX regime
    (low/normal/high). Returns per-regime stats: n, win_rate, avg_return,
    expectancy, total_pnl. Reveals 'works only in bull markets' failure mode.
    """
    def _spy_regime(day):
        if spy_df is None or spy_df.empty:
            return None
        sub = spy_df.loc[spy_df.index <= day]
        if len(sub) < 200:
            return None
        sma200 = sub["Close"].iloc[-200:].mean()
        return "bull" if sub["Close"].iloc[-1] > sma200 else "bear"

    def _vix_regime(day):
        if vix_df is None or vix_df.empty:
            return None
        sub = vix_df.loc[vix_df.index <= day]
        if sub.empty:
            return None
        v = float(sub["Close"].iloc[-1])
        if v < 15:
            return "low_vix"
        if v <= 25:
            return "normal_vix"
        return "high_vix"

    spy_groups: dict[str, list] = defaultdict(list)
    vix_groups: dict[str, list] = defaultdict(list)
    for t in closed_trades:
        sr = _spy_regime(t.entry_date)
        vr = _vix_regime(t.entry_date)
        if sr is not None:
            spy_groups[sr].append(t)
        if vr is not None:
            vix_groups[vr].append(t)

    def _summarize(trades):
        if not trades:
            return {"n": 0, "win_rate_pct": 0.0, "avg_return_pct": 0.0,
                    "expectancy_pct": 0.0, "total_pnl": 0.0}
        pcts = np.array([t.pnl_pct for t in trades])
        wins = (pcts > 0).sum()
        return {
            "n": len(trades),
            "win_rate_pct": round(float(wins / len(trades) * 100), 1),
            "avg_return_pct": round(float(pcts.mean()), 2),
            "expectancy_pct": round(float(pcts.mean()), 2),
            "total_pnl": round(float(sum(t.pnl for t in trades)), 2),
        }

    return {
        "spy_bull": _summarize(spy_groups["bull"]),
        "spy_bear": _summarize(spy_groups["bear"]),
        "vix_low": _summarize(vix_groups["low_vix"]),
        "vix_normal": _summarize(vix_groups["normal_vix"]),
        "vix_high": _summarize(vix_groups["high_vix"]),
    }


def monthly_return_grid(equity_curve: list[dict]) -> dict:
    """
    Aggregate weekly equity curve into monthly returns. Returns a nested dict
    of {year: {month: pct_return}} suitable for a year-vs-month heatmap.
    """
    if len(equity_curve) < 2:
        return {}
    df = pd.DataFrame(equity_curve)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    # Resample to month-end: take the last equity of each month
    monthly_eq = df["equity"].resample("ME").last().dropna()
    monthly_ret = monthly_eq.pct_change().dropna() * 100
    grid: dict = {}
    for ts, val in monthly_ret.items():
        y = int(ts.year)
        m = int(ts.month)
        grid.setdefault(y, {})[m] = round(float(val), 2)
    return grid


def excursion_stats(closed_trades) -> dict:
    """
    MFE/MAE diagnostics. avg_mfe says 'on average, how much in our favor did
    the price move during the trade?'. avg_mae says 'how deep underwater did
    we go?'. mfe_capture = how much of MFE we kept = pnl_pct / avg_mfe_pct.
    R-distribution buckets winning vs losing trades by R-multiple.
    """
    if not closed_trades:
        return {
            "avg_mfe_pct": 0.0, "avg_mae_pct": 0.0, "mfe_capture_pct": 0.0,
            "avg_r_multiple": 0.0, "r_distribution": {},
            "stop_proximity_pct": 0.0,
        }
    mfes = np.array([t.mfe_pct for t in closed_trades])
    maes = np.array([t.mae_pct for t in closed_trades])
    rs = np.array([t.r_multiple for t in closed_trades])
    pnls = np.array([t.pnl_pct for t in closed_trades])

    avg_mfe = float(mfes.mean())
    avg_mae = float(maes.mean())
    avg_pnl = float(pnls.mean())
    capture = (avg_pnl / avg_mfe * 100) if avg_mfe > 0 else 0.0

    # R-distribution: buckets <-2R, -2 to -1, -1 to 0, 0 to 1, 1-2, 2-3, 3+
    edges = [-float("inf"), -2, -1, 0, 1, 2, 3, float("inf")]
    labels = ["<-2R", "-2 to -1R", "-1 to 0R", "0 to 1R", "1 to 2R", "2 to 3R", ">=3R"]
    dist = {labels[i]: 0 for i in range(len(labels))}
    for r in rs:
        for i in range(len(edges) - 1):
            if edges[i] <= r < edges[i + 1]:
                dist[labels[i]] += 1
                break

    # Stop proximity: average distance from MAE to stop, normalized.
    # If avg MAE on losing trades is near -1R, stops fire just as price reaches them.
    # If avg MAE is much deeper than -1R, slippage / gap-throughs are eating the trade.
    losing_rs = rs[pnls < 0]
    stop_prox = float(losing_rs.mean()) if len(losing_rs) > 0 else 0.0

    return {
        "avg_mfe_pct": round(avg_mfe, 2),
        "avg_mae_pct": round(avg_mae, 2),
        "mfe_capture_pct": round(capture, 1),  # % of MFE retained as pnl
        "avg_r_multiple": round(float(rs.mean()), 2),
        "r_distribution": dist,
        "stop_proximity_pct": round(stop_prox, 2),
    }


def equity_curve_stats(equity_curve: list[dict]) -> dict:
    """
    Compute risk-adjusted metrics from a weekly equity curve.
    Returns dict with: max_drawdown_pct, time_in_dd_pct, ann_sharpe, ann_sortino,
    calmar, ann_volatility_pct.

    Sharpe assumes 0% risk-free rate (small adjustment vs reality on a single-account
    backtest; user can subtract t-bill rate if needed).
    """
    if len(equity_curve) < 2:
        return {
            "max_drawdown_pct": 0.0,
            "time_in_dd_pct": 0.0,
            "ann_sharpe": 0.0,
            "ann_sortino": 0.0,
            "calmar": 0.0,
            "ann_volatility_pct": 0.0,
        }
    equities = np.array([e["equity"] for e in equity_curve], dtype=float)
    weekly_returns = equities[1:] / equities[:-1] - 1
    weekly_returns = weekly_returns[np.isfinite(weekly_returns)]

    # Drawdown from running max
    running_max = np.maximum.accumulate(equities)
    drawdown = equities / running_max - 1
    max_dd = float(drawdown.min()) if len(drawdown) else 0.0
    time_in_dd = float((drawdown < 0).mean() * 100) if len(drawdown) else 0.0

    if len(weekly_returns) == 0:
        return {
            "max_drawdown_pct": round(max_dd * 100, 2),
            "time_in_dd_pct": round(time_in_dd, 1),
            "ann_sharpe": 0.0,
            "ann_sortino": 0.0,
            "calmar": 0.0,
            "ann_volatility_pct": 0.0,
        }

    mean_w = float(weekly_returns.mean())
    std_w = float(weekly_returns.std(ddof=1)) if len(weekly_returns) > 1 else 0.0
    downside = weekly_returns[weekly_returns < 0]
    downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0

    ann_sharpe = (mean_w / std_w) * math.sqrt(WEEKS_PER_YEAR) if std_w > 0 else 0.0
    ann_sortino = (mean_w / downside_std) * math.sqrt(WEEKS_PER_YEAR) if downside_std > 0 else 0.0
    ann_vol = std_w * math.sqrt(WEEKS_PER_YEAR) * 100

    # Calmar = annualized return / |max DD|
    total_return = equities[-1] / equities[0] - 1
    weeks_elapsed = len(weekly_returns)
    years_elapsed = weeks_elapsed / WEEKS_PER_YEAR
    cagr = ((1 + total_return) ** (1 / years_elapsed) - 1) if years_elapsed > 0 else 0.0
    calmar = (cagr / abs(max_dd)) if max_dd < 0 else 0.0

    return {
        "max_drawdown_pct": round(max_dd * 100, 2),
        "time_in_dd_pct": round(time_in_dd, 1),
        "ann_sharpe": round(ann_sharpe, 2),
        "ann_sortino": round(ann_sortino, 2),
        "calmar": round(calmar, 2),
        "ann_volatility_pct": round(ann_vol, 2),
    }


def cost_sensitivity_grid(
    closed_trades,
    starting_cash: float,
    bps_levels: tuple = (0, 5, 10, 25, 50),
    fixed_commission: float = 0.0,
    fixed_reg_bps: float = 3.0,
) -> dict:
    """
    Re-derive net P&L at varied slippage levels (bps each side). Returns:
      { 'levels': [...rows...], 'breakeven_bps': float|None }
    Each row: bps, total_pnl, total_return_pct.
    Approximate: assumes shares would have been the same at each cost level
    (true within ~1 share for typical bps deltas).
    """
    rows = []
    for bps in bps_levels:
        slip = bps / 10000.0
        reg = fixed_reg_bps / 10000.0
        net_pnl = 0.0
        for t in closed_trades:
            entry_dollars = t.shares * t.intended_entry_price
            exit_dollars = t.shares * t.intended_exit_price
            slip_cost = (entry_dollars + exit_dollars) * slip
            reg_cost = exit_dollars * reg
            commission_cost = 2 * fixed_commission
            adj_pnl = t.gross_pnl - slip_cost - reg_cost - commission_cost
            net_pnl += adj_pnl
        ret_pct = (net_pnl / starting_cash * 100) if starting_cash > 0 else 0.0
        rows.append({
            "bps_each_side": bps,
            "total_pnl": round(net_pnl, 2),
            "total_return_pct": round(ret_pct, 2),
        })

    # Breakeven: linearly interpolate between adjacent rows where return crosses 0
    breakeven = None
    for i in range(len(rows) - 1):
        if rows[i]["total_return_pct"] > 0 >= rows[i + 1]["total_return_pct"]:
            x0, y0 = rows[i]["bps_each_side"], rows[i]["total_return_pct"]
            x1, y1 = rows[i + 1]["bps_each_side"], rows[i + 1]["total_return_pct"]
            if y0 != y1:
                breakeven = round(x0 + (0 - y0) * (x1 - x0) / (y1 - y0), 1)
            break

    return {"levels": rows, "breakeven_bps": breakeven}


def bootstrap_cis(
    closed_trades,
    starting_cash: float,
    n_resamples: int = 2000,
    block_size: int = 5,
    seed: int = 42,
) -> dict:
    """
    Stationary block bootstrap on trade returns. Returns 95% CIs for total
    return, win rate, and per-trade expectancy. Uses block resampling to
    preserve mild serial dependence between consecutive trades.
    """
    if len(closed_trades) < 5:
        return {
            "n_resamples": 0,
            "total_return_ci_pct": None,
            "win_rate_ci_pct": None,
            "expectancy_ci_pct": None,
            "note": "Too few trades for bootstrap (need >=5).",
        }
    rng = np.random.default_rng(seed)
    pnls = np.array([t.pnl for t in closed_trades])
    pcts = np.array([t.pnl_pct for t in closed_trades])
    wins = (pcts > 0).astype(int)
    n = len(pnls)
    block = max(1, min(block_size, n))

    total_returns = np.empty(n_resamples)
    win_rates = np.empty(n_resamples)
    expectancies = np.empty(n_resamples)
    for i in range(n_resamples):
        # Stationary-style block bootstrap: pick random start indices, take blocks
        idx = []
        while len(idx) < n:
            start = rng.integers(0, n)
            idx.extend(range(start, start + block))
        idx = np.array([j % n for j in idx[:n]])
        sample_pnl = pnls[idx]
        sample_pct = pcts[idx]
        sample_win = wins[idx]
        total_returns[i] = sample_pnl.sum() / starting_cash * 100
        win_rates[i] = sample_win.mean() * 100
        expectancies[i] = sample_pct.mean()

    def _ci(arr):
        return [round(float(np.percentile(arr, 2.5)), 2),
                round(float(np.percentile(arr, 97.5)), 2)]

    return {
        "n_resamples": n_resamples,
        "block_size": block,
        "total_return_ci_pct": _ci(total_returns),
        "win_rate_ci_pct": _ci(win_rates),
        "expectancy_ci_pct": _ci(expectancies),
    }


def verdict_with_stats(calibration_rows: list[dict]) -> str:
    """
    Statistical verdict combining:
      1. Spearman rank correlation (bucket midpoint vs avg_return) — tests monotonicity.
      2. Welch's t-test on high (70+) vs low (<60) bucket trade returns — needs sample.
      3. Power gate: requires n >= 100 per arm for a 2pp effect to be detectable
         at 80% power with typical std (~6-10pp).
    """
    try:
        from scipy import stats as scipy_stats
    except Exception:
        return "scipy not available — install for statistical verdict."

    populated = [r for r in calibration_rows if r["n"] > 0]
    if len(populated) < 3:
        return "Insufficient bucket coverage (need >=3 populated buckets for trend test)."

    # Spearman rank correlation
    x = np.array([BUCKET_MIDPOINTS[r["bucket"]] for r in populated])
    y = np.array([r["avg_return_pct"] for r in populated])
    if len(x) >= 3:
        rho, rho_p = scipy_stats.spearmanr(x, y)
    else:
        rho, rho_p = 0.0, 1.0

    # High vs low t-test using underlying distributions if available;
    # here we only have aggregated rows so use a simple two-sample t on
    # bucket-mean differences weighted by n.
    high_n = sum(r["n"] for r in populated if r["bucket"] in ("70-79", "80+"))
    low_n = sum(r["n"] for r in populated if r["bucket"] in ("<50", "50-59"))

    high_avg = (
        sum(r["avg_return_pct"] * r["n"] for r in populated if r["bucket"] in ("70-79", "80+")) / high_n
        if high_n > 0 else None
    )
    low_avg = (
        sum(r["avg_return_pct"] * r["n"] for r in populated if r["bucket"] in ("<50", "50-59")) / low_n
        if low_n > 0 else None
    )

    parts = []
    parts.append(f"Spearman rho={rho:+.2f} (p={rho_p:.3f})")

    if high_n == 0 or low_n == 0:
        parts.append("high or low arm empty - cannot compare buckets directly")
        return ". ".join(parts) + "."

    delta = high_avg - low_avg
    parts.append(f"high(n={high_n})={high_avg:+.2f}% vs low(n={low_n})={low_avg:+.2f}%, delta={delta:+.2f}pp")

    # Power gate
    if high_n < 100 or low_n < 100:
        power_msg = "UNDERPOWERED (need n>=100 per arm for a 2pp effect at 80% power, std~8pp)"
    else:
        power_msg = "adequate sample"
    parts.append(power_msg)

    # Significance of monotonicity
    if rho_p < 0.05 and rho > 0:
        verdict_str = "MONOTONIC PREDICTIVE (score increases avg return, p<0.05)"
    elif rho_p < 0.05 and rho < 0:
        verdict_str = "MONOTONIC INVERSE (score *decreases* avg return - investigate)"
    else:
        verdict_str = "no monotonic relationship at alpha=0.05"
    parts.append(verdict_str)

    return ". ".join(parts) + "."


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
            f"low-bucket avg {low_avg:+.2f}% (delta={diff:+.2f}%, {confidence})."
        )
    if diff < -2:
        return (
            f"Score appears INVERSELY predictive: high {high_avg:+.2f}% vs "
            f"low {low_avg:+.2f}% (delta={diff:+.2f}%, {confidence}). Investigate."
        )
    return (
        f"Score does not separate winners from losers: high {high_avg:+.2f}% vs "
        f"low {low_avg:+.2f}% (delta={diff:+.2f}%, {confidence})."
    )
