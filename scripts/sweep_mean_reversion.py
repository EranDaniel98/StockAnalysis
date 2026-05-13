"""Mean-reversion strategy A/B sweep.

Compares the new ``mean_reversion`` strategy (config/strategies.yaml)
against the established ``swing_trading`` baseline on the themes
universe. Different strategies need different trade mechanics:

  swing_trading       — atr_stop=2.0, atr_target=6.0 (3:1 R:R), hold 90d
  mean_reversion      — atr_stop=1.5, atr_target=2.5 (1.67:1 R:R), hold 10d

Mean-rev expects fast reversion to the mean; if the move doesn't happen
quickly the thesis was wrong, so tight stops and short holds. R:R is
intentionally lower than swing — mean-rev gets its edge from a higher
win rate, not from per-trade asymmetry.

Hypothesis: mean_reversion produces a higher win rate (target ~55-65%)
at a similar or slightly lower OOS Sharpe. Whether that's the user's
preferred profile is a separate question.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
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


# (strategy_name, atr_stop_mult, atr_target_mult, max_hold_days, min_score)
# Three runs: baseline swing, mean_reversion at default tight mechanics,
# and mean_reversion at moderate mechanics (less aggressive stop).
SCENARIOS: list[tuple[str, str, float, float, int, float]] = [
    ("swing_baseline",   "swing_trading",   2.0, 6.0, 90, 50.0),
    ("mean_rev_tight",   "mean_reversion",  1.5, 2.5, 10, 50.0),
    ("mean_rev_moderate","mean_reversion",  2.0, 3.0, 15, 50.0),
]


def _summarize(label: str, strat_name: str, result: dict[str, Any]) -> dict[str, Any]:
    full = result["full"]
    oos = result["out_of_sample"]
    return {
        "label": label,
        "strategy": strat_name,
        "n_trades": full["summary"]["n_trades"],
        "n_oos_trades": oos["summary"]["n_trades"],
        "full_return_pct": full["summary"]["total_return_pct"],
        "oos_return_pct": oos["summary"]["total_return_pct"],
        "full_sharpe": full["equity_stats"]["ann_sharpe"],
        "oos_sharpe": oos["equity_stats"]["ann_sharpe"],
        "max_dd_pct": full["equity_stats"]["max_drawdown_pct"],
        "win_rate_pct": full["summary"]["win_rate_pct"],
    }


def _print_table(rows: list[dict[str, Any]], universe_label: str) -> None:
    table = Table(
        title=f"Mean-reversion vs swing — {universe_label}",
        show_lines=False,
    )
    table.add_column("Scenario", style="bold")
    table.add_column("Strategy")
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
            r["label"],
            r["strategy"],
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
    parser = argparse.ArgumentParser(description="Mean-reversion A/B sweep.")
    parser.add_argument("--universe", choices=["themes", "watchlist"], default="themes")
    parser.add_argument("--years", type=float, default=3.0)
    parser.add_argument("--cash", type=float, default=10_000.0)
    parser.add_argument("--max-positions", type=int, default=20)
    parser.add_argument("--commission", type=float, default=0.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--regulatory-bps", type=float, default=3.0)
    parser.add_argument("--earnings-blackout", type=int, default=3)
    parser.add_argument("--bootstrap-resamples", type=int, default=0)
    parser.add_argument("--save", default="data/sweep_mean_reversion.json")
    args = parser.parse_args()

    config = Config()

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

    console.print(f"\n[bold cyan]Mean-reversion A/B sweep[/bold cyan]")
    console.print(f"  Universe: [bold]{universe_label}[/bold]")
    console.print(f"  Window:   {start.strftime('%Y-%m-%d')} -> {end.strftime('%Y-%m-%d')}\n")

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

    console.print("[bold]Fetching earnings history...[/bold]")
    earnings_history = fetch_earnings_history(list(price_data.keys()))
    earnings_dates = {
        t: (sorted(df_h.index.tolist()) if df_h is not None and not df_h.empty else [])
        for t, df_h in earnings_history.items()
    }
    print()

    rows: list[dict[str, Any]] = []
    for label, strat_name, atr_stop, atr_target, hold_days, min_score in SCENARIOS:
        try:
            strategy = config.get_strategy(strat_name)
        except ValueError as e:
            console.print(f"[red]Skipping {label}: {e}[/red]")
            continue
        bt_cfg = BacktestConfig(
            start_date=start,
            end_date=end,
            min_score=min_score,
            atr_stop_mult=atr_stop,
            atr_target_mult=atr_target,
            max_hold_days=hold_days,
            max_open_positions=args.max_positions,
            starting_cash=args.cash,
            commission_per_trade=args.commission,
            slippage_bps=args.slippage_bps,
            regulatory_bps_on_sale=args.regulatory_bps,
            earnings_blackout_days=args.earnings_blackout,
            bootstrap_resamples=args.bootstrap_resamples,
        )
        console.print(
            f"[bold cyan]Running {label} (strategy={strat_name}, "
            f"atr_stop={atr_stop}, atr_target={atr_target}, hold={hold_days}d)...[/bold cyan]"
        )
        t0 = time.time()
        result = run_backtest(
            price_data, fundamentals, config, strategy, bt_cfg,
            spy_df=spy_df, vix_df=vix_df, earnings_dates=earnings_dates,
        )
        elapsed = time.time() - t0
        summary = _summarize(label, strat_name, result)
        console.print(
            f"  done in {elapsed:.1f}s — OOS Sharpe {summary['oos_sharpe']:+.2f}, "
            f"trades {summary['n_trades']}, win rate {summary['win_rate_pct']:.1f}%\n"
        )
        rows.append(summary)

    _print_table(rows, universe_label)

    save_path = Path(args.save)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    console.print(f"\n[dim]Saved comparison rows to {save_path}[/dim]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
