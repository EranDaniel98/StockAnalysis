"""Min-score selectivity sweep.

Sweeps the strategy's ``min_score`` floor on the swing_trading + themes
harness to map the win-rate / OOS-Sharpe tradeoff. Higher min_score
means stricter selectivity — fewer trades but theoretically higher
quality. Lower min_score takes more setups including marginal ones.

This script is the canonical example of the new sweep harness shape
post-2026-05-17 refactor: most of the boilerplate (universe + data
load) lives in ``src.research.sweep_runner``; this file only carries
(a) the parameter we're varying, (b) the BacktestConfig we build per
sweep value, (c) the Rich table renderer specific to this sweep.

Other ``scripts/sweep_*.py`` migrate to the same shape as they need
edits.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from src.backtest.engine import BacktestConfig, run_backtest
from src.research.sweep_runner import (
    prepare_sweep_inputs, summarize_result, write_sweep_rows,
)

console = Console()


def _print_table(rows: list[dict[str, Any]], strategy_name: str, universe_label: str) -> None:
    table = Table(
        title=f"min_score sweep — {strategy_name} on {universe_label}",
        show_lines=False,
    )
    table.add_column("min_score", style="bold", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("OOS n", justify="right")
    table.add_column("Full ret %", justify="right")
    table.add_column("OOS ret %", justify="right")
    table.add_column("Full Sharpe", justify="right")
    table.add_column("OOS Sharpe", justify="right", style="bold")
    table.add_column("Max DD %", justify="right")
    table.add_column("Win %", justify="right", style="green")
    for r in rows:
        table.add_row(
            f"{r['label']:.0f}",
            str(r["n_trades"]),
            str(r["n_oos_trades"]),
            f"{r['full_return_pct']:+.2f}",
            f"{r['oos_return_pct']:+.2f}",
            f"{r['full_sharpe']:+.2f}",
            f"{r['oos_sharpe']:+.2f}",
            f"{r['max_dd_pct']:.2f}",
            f"{r['win_rate_pct']:.1f}",
        )
    console.print(table)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="min_score selectivity sweep.")
    parser.add_argument("--strategy", default="swing_trading")
    parser.add_argument("--universe", choices=["themes", "watchlist"], default="themes")
    parser.add_argument("--years", type=float, default=3.0)
    parser.add_argument("--scores", default="50,55,60",
                        help="Comma-separated min_score values to test.")
    parser.add_argument("--atr-stop", type=float, default=2.0)
    parser.add_argument("--cash", type=float, default=10_000.0)
    parser.add_argument("--max-positions", type=int, default=20)
    parser.add_argument("--commission", type=float, default=0.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--regulatory-bps", type=float, default=3.0)
    parser.add_argument("--earnings-blackout", type=int, default=3)
    parser.add_argument("--bootstrap-resamples", type=int, default=0)
    parser.add_argument("--save", default="data/sweep_min_score.json")
    args = parser.parse_args()

    min_scores = [float(x) for x in args.scores.split(",") if x.strip()]
    if not min_scores:
        console.print("[red]No min_score values to test[/red]")
        return 1

    inputs = prepare_sweep_inputs(
        strategy_name=args.strategy,
        universe=args.universe,
        years=args.years,
        earnings_blackout_days=args.earnings_blackout,
    )

    console.print(f"\n[bold cyan]min_score sweep[/bold cyan]")
    console.print(f"  Strategy: [bold]{inputs.strategy_name}[/bold]")
    console.print(f"  Universe: [bold]{inputs.universe_label}[/bold]")
    console.print(
        f"  Window:   {inputs.start.strftime('%Y-%m-%d')} -> "
        f"{inputs.end.strftime('%Y-%m-%d')}"
    )
    console.print(f"  Scores:   {min_scores}\n")

    rows: list[dict[str, Any]] = []
    for min_score in min_scores:
        bt_cfg = BacktestConfig(
            start_date=inputs.start,
            end_date=inputs.end,
            min_score=min_score,
            atr_stop_mult=args.atr_stop,
            max_open_positions=args.max_positions,
            starting_cash=args.cash,
            commission_per_trade=args.commission,
            slippage_bps=args.slippage_bps,
            regulatory_bps_on_sale=args.regulatory_bps,
            earnings_blackout_days=args.earnings_blackout,
            bootstrap_resamples=args.bootstrap_resamples,
        )
        console.print(f"[bold cyan]Running min_score={min_score:.0f}...[/bold cyan]")
        t0 = time.time()
        result = run_backtest(
            inputs.price_data, inputs.fundamentals, inputs.config,
            inputs.strategy, bt_cfg,
            spy_df=inputs.spy_df, vix_df=inputs.vix_df,
            earnings_dates=inputs.earnings_dates,
        )
        elapsed = time.time() - t0
        row = summarize_result(min_score, result)
        console.print(
            f"  done in {elapsed:.1f}s — OOS Sharpe {row['oos_sharpe']:+.2f}, "
            f"trades {row['n_trades']}, win rate {row['win_rate_pct']:.1f}%\n"
        )
        rows.append(row)

    _print_table(rows, inputs.strategy_name, inputs.universe_label)

    saved = write_sweep_rows(rows, args.save)
    console.print(f"\n[dim]Saved comparison rows to {saved}[/dim]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
