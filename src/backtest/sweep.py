"""
Parameter sweep with mandatory IS/OOS split (Tier 5.1).

Re-runs run_backtest across a grid of parameter combinations and ranks results
by OOS Sharpe. Without the OOS split this would be a textbook overfitting
machine — sweeping over IS metrics would always find a "best" combo that
doesn't generalize.
"""

import logging
import math
from dataclasses import replace
from itertools import product
from typing import Optional

import pandas as pd
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from src.backtest.engine import LookaheadGuardError, run_backtest

logger = logging.getLogger(__name__)


DEFAULT_GRID = {
    "min_score": [55, 60, 65, 70],
    "atr_stop_mult": [1.5, 2.0, 2.5, 3.0],
}


def parse_grid(spec: Optional[str]) -> dict:
    """
    Parse a grid spec like 'min_score=55,60,65;atr_stop_mult=1.5,2,2.5'.
    Each segment separated by ';'; key/values by '='; values by ','.
    Numbers parsed automatically (int if possible, else float).
    """
    if not spec:
        return DEFAULT_GRID
    grid: dict = {}
    for segment in spec.split(";"):
        segment = segment.strip()
        if not segment:
            continue
        if "=" not in segment:
            raise ValueError(f"Bad sweep segment '{segment}' (expected key=v1,v2,...)")
        key, raw = segment.split("=", 1)
        key = key.strip()
        values = []
        for v in raw.split(","):
            v = v.strip()
            try:
                values.append(int(v))
            except ValueError:
                values.append(float(v))
        grid[key] = values
    return grid or DEFAULT_GRID


def parameter_sweep(
    price_data,
    fundamentals,
    config,
    strategy,
    base_bt_cfg,
    grid: dict,
    spy_df=None,
    vix_df=None,
    earnings_dates=None,
) -> list[dict]:
    """
    Run a full backtest for each combination of params in `grid`. Returns one
    row per combo, sorted by OOS Sharpe descending.
    """
    keys = list(grid.keys())
    values = [grid[k] for k in keys]
    combos = list(product(*values))
    if not combos:
        return []

    rows: list[dict] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]Parameter sweep[/bold]"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("{task.fields[combo]}"),
        transient=True,
    ) as progress:
        task = progress.add_task("sweep", total=len(combos), combo="")
        for combo in combos:
            overrides = dict(zip(keys, combo))
            label = ", ".join(f"{k}={v}" for k, v in overrides.items())
            progress.update(task, combo=label)
            try:
                bt_cfg = replace(base_bt_cfg, **overrides)
            except TypeError as e:
                rows.append({"params": overrides, "error": f"unknown param: {e}"})
                progress.advance(task)
                continue

            try:
                result = run_backtest(
                    price_data, fundamentals, config, strategy, bt_cfg,
                    spy_df=spy_df, vix_df=vix_df, earnings_dates=earnings_dates,
                )
            except LookaheadGuardError as e:
                rows.append({"params": overrides, "error": "lookahead blocked"})
                progress.advance(task)
                continue
            except Exception as e:
                logger.error(f"Sweep run failed for {label}: {e}")
                rows.append({"params": overrides, "error": str(e)[:60]})
                progress.advance(task)
                continue

            full_summary = result["full"]["summary"]
            oos_summary = result["out_of_sample"]["summary"]
            full_eq = result["full"]["equity_stats"]
            oos_eq = result["out_of_sample"]["equity_stats"]
            rows.append({
                "params": overrides,
                "n_trades": full_summary["n_trades"],
                "n_oos_trades": oos_summary["n_trades"],
                "full_return_pct": full_summary["total_return_pct"],
                "oos_return_pct": oos_summary["total_return_pct"],
                "full_sharpe": full_eq["ann_sharpe"],
                "oos_sharpe": oos_eq["ann_sharpe"],
                "max_dd_pct": full_eq["max_drawdown_pct"],
                "win_rate_pct": full_summary["win_rate_pct"],
            })
            progress.advance(task)

    # Sort: failures last, then by OOS Sharpe desc
    rows.sort(key=lambda r: r.get("oos_sharpe", -1e9), reverse=True)
    return rows


def bonferroni_threshold(n_runs: int, alpha: float = 0.05) -> float:
    """Bonferroni-corrected significance threshold for n_runs comparisons."""
    if n_runs < 1:
        return alpha
    return alpha / n_runs
