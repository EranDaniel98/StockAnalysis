"""Sector-relative scoring A/B sweep.

Same harness shape as ``sweep_regime.py``: fetch data once, run
``run_backtest`` twice — once with sector-relative valuation scoring
on, once with it off — and emit a comparison table.

The toggle lives on the ``Config`` object
(``risk_management.sector_relative_scoring``), not on
``BacktestConfig``, so we mutate it between runs rather than going
through the ``parameter_sweep`` harness which only varies
``BacktestConfig`` fields.

Anchor: matches the live-recommended config (swing_trading +
min_score=50 + atr_stop=2.0 + themes universe + 3y window) so the
result is directly comparable to ``project_sweep_results.md`` and
``data/sweep_regime.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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


MODES = [
    ("absolute", False),
    ("sector_relative", True),
]


def _set_sector_relative(config: Config, enabled: bool, min_cohort: int) -> None:
    rm = config.settings.setdefault("risk_management", {})
    block = rm.setdefault("sector_relative_scoring", {})
    block["enabled"] = enabled
    block.setdefault("min_cohort", min_cohort)


def _summarize(mode: str, result: dict[str, Any]) -> dict[str, Any]:
    full = result["full"]
    oos = result["out_of_sample"]
    srs = result.get("sector_relative_scoring", {})
    return {
        "mode": mode,
        "n_trades": full["summary"]["n_trades"],
        "n_oos_trades": oos["summary"]["n_trades"],
        "full_return_pct": full["summary"]["total_return_pct"],
        "oos_return_pct": oos["summary"]["total_return_pct"],
        "full_sharpe": full["equity_stats"]["ann_sharpe"],
        "oos_sharpe": oos["equity_stats"]["ann_sharpe"],
        "max_dd_pct": full["equity_stats"]["max_drawdown_pct"],
        "win_rate_pct": full["summary"]["win_rate_pct"],
        "sectors_with_stats": srs.get("sectors_with_stats", []),
    }


def _print_table(rows: list[dict[str, Any]], strategy_name: str, universe_label: str) -> None:
    table = Table(
        title=f"Sector-relative A/B — {strategy_name} on {universe_label}",
        show_lines=False,
    )
    table.add_column("Mode", style="bold")
    table.add_column("Trades", justify="right")
    table.add_column("OOS n", justify="right")
    table.add_column("Full ret %", justify="right")
    table.add_column("OOS ret %", justify="right")
    table.add_column("Full Sharpe", justify="right")
    table.add_column("OOS Sharpe", justify="right", style="bold")
    table.add_column("Max DD %", justify="right")
    table.add_column("Win %", justify="right")
    table.add_column("Sectors", justify="right", style="dim")
    for r in rows:
        table.add_row(
            r["mode"],
            str(r["n_trades"]),
            str(r["n_oos_trades"]),
            f"{r['full_return_pct']:+.2f}",
            f"{r['oos_return_pct']:+.2f}",
            f"{r['full_sharpe']:+.2f}",
            f"{r['oos_sharpe']:+.2f}",
            f"{r['max_dd_pct']:.2f}",
            f"{r['win_rate_pct']:.1f}",
            str(len(r["sectors_with_stats"])),
        )
    console.print(table)


def main() -> int:
    parser = argparse.ArgumentParser(description="A/B sweep on sector-relative valuation scoring.")
    parser.add_argument("--strategy", default="swing_trading")
    parser.add_argument("--universe", choices=["themes", "watchlist"], default="themes")
    parser.add_argument("--years", type=float, default=3.0)
    parser.add_argument("--min-score", type=float, default=50.0)
    parser.add_argument("--atr-stop", type=float, default=2.0)
    parser.add_argument("--min-cohort", type=int, default=5)
    parser.add_argument("--cash", type=float, default=10_000.0)
    parser.add_argument("--max-positions", type=int, default=20)
    parser.add_argument("--commission", type=float, default=0.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--regulatory-bps", type=float, default=3.0)
    parser.add_argument("--earnings-blackout", type=int, default=3)
    parser.add_argument("--bootstrap-resamples", type=int, default=0)
    parser.add_argument(
        "--save",
        default="data/sweep_sector_relative.json",
        help="Where to write the raw comparison rows.",
    )
    args = parser.parse_args()

    config = Config()
    strategy = config.get_strategy(args.strategy)

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

    console.print(f"\n[bold cyan]Sector-relative A/B sweep[/bold cyan]")
    console.print(f"  Strategy: [bold]{args.strategy}[/bold]")
    console.print(f"  Universe: [bold]{universe_label}[/bold]")
    console.print(f"  Window:   {start.strftime('%Y-%m-%d')} -> {end.strftime('%Y-%m-%d')}")
    console.print(f"  Params:   min_score={args.min_score}, atr_stop={args.atr_stop}, min_cohort={args.min_cohort}\n")

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
    console.print(f"  Got fundamentals for {len(fundamentals)}/{len(tickers)} tickers")
    # Useful diagnostic — how many sectors clear the cohort threshold?
    sectors_seen = {f.get("sector") for f in fundamentals.values() if f and f.get("sector")}
    console.print(f"  Sectors represented: {len(sectors_seen)}\n")

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
    for mode, enabled in MODES:
        _set_sector_relative(config, enabled, args.min_cohort)
        console.print(f"[bold cyan]Running mode={mode}...[/bold cyan]")
        t0 = time.time()
        result = run_backtest(
            price_data, fundamentals, config, strategy, bt_cfg,
            spy_df=spy_df, vix_df=vix_df, earnings_dates=earnings_dates,
        )
        elapsed = time.time() - t0
        summary = _summarize(mode, result)
        console.print(
            f"  done in {elapsed:.1f}s — OOS Sharpe {summary['oos_sharpe']:+.2f}, "
            f"trades {summary['n_trades']}, sectors with stats: "
            f"{len(summary['sectors_with_stats'])}\n"
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
