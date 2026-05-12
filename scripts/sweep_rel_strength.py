"""Relative-strength A/B sweep.

Three modes on the same swing_trading + themes harness used by the
regime and sector-relative sweeps. Each mode shifts a slice of the
composite weight onto the new ``rel_strength`` sub-score; the other
weights are scaled down proportionally so the total still sums to 1.

  off     : rel_strength weight = 0.00 (baseline — analyzer runs but
            its score doesn't feed the composite)
  light   : rel_strength weight = 0.10
  medium  : rel_strength weight = 0.20

This is an A/B/C test, not a continuous sweep, because the weight space
is too small to need a grid: if 0.10 doesn't move the needle and 0.20
hurts, the answer is "RS doesn't help for this strategy."
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd
from rich.console import Console
from rich.table import Table

from src.config_loader import Config
from src.data.cache import DataCache
from src.data.fetcher import DataFetcher
from src.data.fundamentals import FundamentalsFetcher
from src.backtest.engine import (
    BacktestConfig,
    fetch_earnings_history,
    run_backtest,
)

console = Console()


MODES: list[tuple[str, float]] = [
    ("off", 0.0),
    ("light", 0.10),
    ("medium", 0.20),
]


def _strategy_with_rs_weight(base_strategy: dict, rs_weight: float) -> dict:
    """Return a deep-copy of the strategy with ``rel_strength`` added
    to its weights at ``rs_weight``; remaining categories are scaled
    down proportionally so the total stays at the original sum.

    Why preserve the sum: the composite engine renormalizes when
    weights don't sum to 1, so the math works either way — but
    preserving the sum keeps the breakdown table interpretable.
    """
    strat = deepcopy(base_strategy)
    weights = strat.get("weights", {}) or {}
    if rs_weight <= 0:
        weights["rel_strength"] = 0.0
        strat["weights"] = weights
        return strat
    other_sum = sum(weights.values())
    if other_sum <= 0:
        weights["rel_strength"] = rs_weight
        strat["weights"] = weights
        return strat
    scale = (1.0 - rs_weight) / other_sum if other_sum > 0 else 1.0
    weights = {k: v * scale for k, v in weights.items()}
    weights["rel_strength"] = rs_weight
    strat["weights"] = weights
    return strat


def _summarize(mode: str, rs_weight: float, result: dict[str, Any]) -> dict[str, Any]:
    full = result["full"]
    oos = result["out_of_sample"]
    return {
        "mode": mode,
        "rs_weight": rs_weight,
        "n_trades": full["summary"]["n_trades"],
        "n_oos_trades": oos["summary"]["n_trades"],
        "full_return_pct": full["summary"]["total_return_pct"],
        "oos_return_pct": oos["summary"]["total_return_pct"],
        "full_sharpe": full["equity_stats"]["ann_sharpe"],
        "oos_sharpe": oos["equity_stats"]["ann_sharpe"],
        "max_dd_pct": full["equity_stats"]["max_drawdown_pct"],
        "win_rate_pct": full["summary"]["win_rate_pct"],
    }


def _print_table(rows: list[dict[str, Any]], strategy_name: str, universe_label: str) -> None:
    table = Table(
        title=f"Relative Strength A/B — {strategy_name} on {universe_label}",
        show_lines=False,
    )
    table.add_column("Mode", style="bold")
    table.add_column("RS weight", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("OOS n", justify="right")
    table.add_column("Full ret %", justify="right")
    table.add_column("OOS ret %", justify="right")
    table.add_column("Full Sharpe", justify="right")
    table.add_column("OOS Sharpe", justify="right", style="bold")
    table.add_column("Max DD %", justify="right")
    table.add_column("Win %", justify="right")
    for r in rows:
        table.add_row(
            r["mode"],
            f"{r['rs_weight']:.2f}",
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
    parser = argparse.ArgumentParser(description="A/B sweep on relative-strength weighting.")
    parser.add_argument("--strategy", default="swing_trading")
    parser.add_argument("--universe", choices=["themes", "watchlist"], default="themes")
    parser.add_argument("--years", type=float, default=3.0)
    parser.add_argument("--min-score", type=float, default=50.0)
    parser.add_argument("--atr-stop", type=float, default=2.0)
    parser.add_argument("--cash", type=float, default=10_000.0)
    parser.add_argument("--max-positions", type=int, default=20)
    parser.add_argument("--commission", type=float, default=0.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--regulatory-bps", type=float, default=3.0)
    parser.add_argument("--earnings-blackout", type=int, default=3)
    parser.add_argument("--bootstrap-resamples", type=int, default=0)
    parser.add_argument(
        "--save",
        default="data/sweep_rel_strength.json",
        help="Where to write the raw comparison rows.",
    )
    args = parser.parse_args()

    config = Config()
    base_strategy = config.get_strategy(args.strategy)

    if args.universe == "themes":
        tickers = config.get_theme_tickers()
        universe_label = f"themes ({len(tickers)})"
    else:
        tickers = config.get_watchlist()
        universe_label = f"watchlist ({len(tickers)})"

    if not tickers:
        console.print(f"[red]No tickers found for universe '{args.universe}'[/red]")
        return 1

    end = pd.Timestamp.now().normalize()
    start = end - pd.Timedelta(days=int(365.25 * args.years))
    fetch_period_years = max(args.years + 2, 5)
    fetch_period = f"{int(fetch_period_years)}y"

    console.print(f"\n[bold cyan]Relative-strength A/B sweep[/bold cyan]")
    console.print(f"  Strategy: [bold]{args.strategy}[/bold]")
    console.print(f"  Universe: [bold]{universe_label}[/bold]")
    console.print(f"  Window:   {start.strftime('%Y-%m-%d')} -> {end.strftime('%Y-%m-%d')}")
    console.print(f"  Params:   min_score={args.min_score}, atr_stop={args.atr_stop}\n")

    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get("data", "market_hours_cache_minutes", default=5),
        force_fresh=False,
    )
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    console.print("[bold]Fetching price history...[/bold]")
    price_data = fetcher.fetch_batch(tickers, period=fetch_period)
    console.print(f"  Got price data for {len(price_data)}/{len(tickers)} tickers")

    console.print("[bold]Fetching fundamentals...[/bold]")
    fundamentals = fund_fetcher.fetch_batch(tickers)
    console.print(f"  Got fundamentals for {len(fundamentals)}/{len(tickers)} tickers\n")

    console.print("[bold]Fetching SPY + VIX...[/bold]")
    bench_map = fetcher.fetch_batch(["SPY", "^VIX"], period=fetch_period)
    spy_df = bench_map.get("SPY")
    vix_df = bench_map.get("^VIX")
    if spy_df is None or spy_df.empty:
        console.print("[red]SPY fetch failed — relative strength cannot fire.[/red]")
        return 1

    console.print("[bold]Fetching earnings history...[/bold]")
    earnings_history = fetch_earnings_history(list(price_data.keys()))
    earnings_dates = {
        t: (sorted(df_h.index.tolist()) if df_h is not None and not df_h.empty else [])
        for t, df_h in earnings_history.items()
    }
    print()

    bt_cfg = BacktestConfig(
        start_date=start,
        end_date=end,
        min_score=args.min_score,
        atr_stop_mult=args.atr_stop,
        max_open_positions=args.max_positions,
        starting_cash=args.cash,
        commission_per_trade=args.commission,
        slippage_bps=args.slippage_bps,
        regulatory_bps_on_sale=args.regulatory_bps,
        earnings_blackout_days=args.earnings_blackout,
        bootstrap_resamples=args.bootstrap_resamples,
    )

    rows: list[dict[str, Any]] = []
    for mode, rs_weight in MODES:
        strat = _strategy_with_rs_weight(base_strategy, rs_weight)
        console.print(f"[bold cyan]Running mode={mode} (rs_weight={rs_weight})...[/bold cyan]")
        t0 = time.time()
        result = run_backtest(
            price_data, fundamentals, config, strat, bt_cfg,
            spy_df=spy_df, vix_df=vix_df, earnings_dates=earnings_dates,
        )
        elapsed = time.time() - t0
        summary = _summarize(mode, rs_weight, result)
        console.print(
            f"  done in {elapsed:.1f}s — OOS Sharpe {summary['oos_sharpe']:+.2f}, "
            f"trades {summary['n_trades']}\n"
        )
        rows.append(summary)

    _print_table(rows, args.strategy, universe_label)

    save_path = Path(args.save)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    console.print(f"\n[dim]Saved comparison rows to {save_path}[/dim]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
