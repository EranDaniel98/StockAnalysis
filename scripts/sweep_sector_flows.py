"""sector_etf_flows A/B sweep.

Three modes on a chosen strategy:

  off              : sector ETFs withheld; analyzer can't fire.
  signal_only      : analyzer fires per Monday (signals propagate to
                     consensus adjustment) but sector_flows sub-score
                     weight is 0.
  weighted         : analyzer fires AND sector_flows is weighted at 0.10
                     in the composite, with other weights scaled down
                     proportionally so the total stays normalized.

This is the sector_flows equivalent of sweep_catalyst.py / sweep_insider_flow.py.

Usage:
    uv run python -m scripts.sweep_sector_flows --universe russell_1000 --years 5
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
from src.scoring.analyzers.sector_flows import SECTOR_TO_ETF

console = Console()


# (label, weight_in_composite, run_analyzer)
MODES: list[tuple[str, float, bool]] = [
    ("off",          0.0,  False),
    ("signal_only",  0.0,  True),
    ("weighted",     0.10, True),
]


def _strategy_with_sector_flows_weight(base_strategy: dict, weight: float) -> dict:
    """Same proportional scale-down pattern as the other sweeps.

    When weight > 0, push 'sector_flows' into the strategy's weights dict
    and shrink the other categories proportionally so the total weight
    is preserved. Engine renormalizes via total_weight anyway, but
    keeping the sum invariant makes cross-mode tables comparable.
    """
    strat = deepcopy(base_strategy)
    weights = strat.get("weights", {}) or {}
    if weight <= 0:
        weights["sector_flows"] = 0.0
        strat["weights"] = weights
        return strat
    other_sum = sum(weights.values())
    if other_sum <= 0:
        weights["sector_flows"] = weight
        strat["weights"] = weights
        return strat
    scale = (1.0 - weight) / other_sum
    weights = {k: round(v * scale, 4) for k, v in weights.items()}
    weights["sector_flows"] = weight
    strat["weights"] = weights
    return strat


def _resolve_universe(cfg: Config, name: str) -> list[str]:
    if name == "themes":
        return cfg.get_theme_tickers()
    if name == "value_cohort":
        return cfg.get_value_cohort_tickers()
    if name == "watchlist":
        return cfg.get_watchlist()
    if name == "russell_1000":
        return cfg.get_russell_1000_tickers()
    if name == "all":
        return sorted(
            set(cfg.get_theme_tickers())
            | set(cfg.get_value_cohort_tickers())
            | set(cfg.get_russell_1000_tickers())
        )
    raise ValueError(f"Unknown universe {name!r}")


def _summarize(mode: str, weight: float, strategy: str, result: dict[str, Any]) -> dict[str, Any]:
    full = result["full"]
    oos = result["out_of_sample"]
    return {
        "strategy": strategy,
        "mode": mode,
        "sector_flows_weight": weight,
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
        title=f"sector_etf_flows A/B - {strategy_name} on {universe_label}",
        show_lines=False,
    )
    table.add_column("Mode", style="bold")
    table.add_column("Weight", justify="right")
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
            f"{r['sector_flows_weight']:.2f}",
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", default="swing_trading")
    parser.add_argument(
        "--universe",
        choices=("themes", "value_cohort", "watchlist", "russell_1000", "all"),
        default="russell_1000",
    )
    parser.add_argument("--years", type=float, default=3.0)
    parser.add_argument(
        "--period",
        default=None,
        help="yfinance period override (e.g. 'max', '10y'). Default: years+2.",
    )
    parser.add_argument("--min-score", type=float, default=50.0)
    parser.add_argument("--atr-stop", type=float, default=2.0)
    parser.add_argument("--cash", type=float, default=10_000.0)
    parser.add_argument("--max-positions", type=int, default=20)
    parser.add_argument("--save", default="data/sweep_sector_flows.json")
    args = parser.parse_args()

    config = Config()
    base_strategy = config.get_strategy(args.strategy)

    tickers = _resolve_universe(config, args.universe)
    universe_label = f"{args.universe} ({len(tickers)})"
    if not tickers:
        console.print(f"[red]Empty universe '{args.universe}'[/red]")
        return 1

    end = pd.Timestamp.now().normalize()
    start = end - pd.Timedelta(days=int(365.25 * args.years))
    fetch_period = args.period or f"{int(max(args.years + 2, 5))}y"

    console.print("\n[bold cyan]sector_etf_flows A/B sweep[/bold cyan]")
    console.print(f"  Strategy: [bold]{args.strategy}[/bold]")
    console.print(f"  Universe: [bold]{universe_label}[/bold]")
    console.print(f"  Window:   {start.strftime('%Y-%m-%d')} -> {end.strftime('%Y-%m-%d')}")
    console.print(f"  Fetch:    period={fetch_period}\n")

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

    console.print("[bold]Fetching fundamentals (yfinance current snapshot for sector overlay)...[/bold]")
    fundamentals = fund_fetcher.fetch_batch(tickers)
    console.print(f"  Got fundamentals for {len(fundamentals)}/{len(tickers)} tickers")

    console.print("[bold]Fetching SPY + VIX...[/bold]")
    bench_map = fetcher.fetch_batch(["SPY", "^VIX"], period=fetch_period)
    spy_df = bench_map.get("SPY")
    vix_df = bench_map.get("^VIX")

    console.print("[bold]Fetching sector ETFs (XLK/XLF/XLE/...)...[/bold]")
    sector_etf_symbols = sorted(set(SECTOR_TO_ETF.values()))
    sector_etfs = fetcher.fetch_batch(sector_etf_symbols, period=fetch_period)
    console.print(f"  Got ETF history for {len(sector_etfs)}/{len(sector_etf_symbols)} sector ETFs")

    console.print("[bold]Fetching earnings history...[/bold]")
    earnings_history = fetch_earnings_history(list(price_data.keys()))
    earnings_dates = {
        t: (sorted(df_h.index.tolist()) if df_h is not None and not df_h.empty else [])
        for t, df_h in earnings_history.items()
    }

    bt_cfg_base = dict(
        start_date=start,
        end_date=end,
        min_score=args.min_score,
        atr_stop_mult=args.atr_stop,
        max_open_positions=args.max_positions,
        starting_cash=args.cash,
    )

    rows: list[dict[str, Any]] = []
    for mode, weight, run_analyzer in MODES:
        strat = _strategy_with_sector_flows_weight(base_strategy, weight)
        etfs_for_run = sector_etfs if run_analyzer else None
        console.print(
            f"\n[bold cyan]Running mode={mode} "
            f"(weight={weight}, analyzer={'on' if run_analyzer else 'off'})...[/bold cyan]"
        )
        bt_cfg = BacktestConfig(**bt_cfg_base)
        t0 = time.time()
        result = run_backtest(
            price_data, fundamentals, config, strat, bt_cfg,
            spy_df=spy_df, vix_df=vix_df, earnings_dates=earnings_dates,
            sector_etfs=etfs_for_run,
        )
        elapsed = time.time() - t0
        summary = _summarize(mode, weight, args.strategy, result)
        console.print(
            f"  done in {elapsed:.1f}s - OOS Sharpe {summary['oos_sharpe']:+.2f}, "
            f"trades {summary['n_trades']}, win rate {summary['win_rate_pct']:.1f}%\n"
        )
        rows.append(summary)

    _print_table(rows, args.strategy, universe_label)

    save_path = Path(args.save)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    console.print(f"\n[dim]Saved {len(rows)} rows to {save_path}[/dim]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
