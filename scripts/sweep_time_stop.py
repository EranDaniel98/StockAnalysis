"""Time-stop A/B sweep — Stage 1 of triple-barrier exit rollout.

For one (strategy, universe) pair, runs the backtest under four
`max_hold_days` modes:

  half        : 0.5 × strategy.time_stop_days
  default     : 1.0 × strategy.time_stop_days  (literature default)
  one_half    : 1.5 × strategy.time_stop_days
  no_time_stop: 730 days (effectively no time stop in a 2-3y window)

The "no_time_stop" mode is the empirical baseline — the system's
behavior BEFORE the triple-barrier work, when positions held until
stop / target / backtest-end. If `default` doesn't beat
`no_time_stop` OOS, the time stop should not ship for that strategy.

Why a fresh script rather than reusing run_backtest_multi_mode: that
helper caches scores across modes but assumes all modes share the
same engine config (max_hold_days is in BacktestConfig, not in a
SweepMode). So this script re-runs the full simulation per mode,
trading runtime for correctness. The score cache is still warm
across modes within the same process, but the portfolio simulation
re-runs.

Usage:
    uv run python -m scripts.sweep_time_stop \\
        --strategy swing_trading --universe russell_1000 --years 2 \\
        --save data/sweep_time_stop/sweep_russell_1000_swing_trading_2y.json
"""

from __future__ import annotations

import argparse
import asyncio
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
from src.db.repositories import PostgresFundamentalsRepository
from src.db.session import dispose_engine, get_sessionmaker
from src.backtest.engine import (
    BacktestConfig,
    fetch_earnings_dates,
    fetch_earnings_history,
    run_backtest,
)
from src.scoring.fundamentals_pit_loader import FundamentalsPITLoader

console = Console()

# Mode = (label, multiplier_of_strategy_default). The "no_time_stop"
# mode is captured by a sentinel multiplier that resolves to 730 days
# regardless of the strategy default.
MODES: list[tuple[str, float | None]] = [
    ("half",         0.5),
    ("default",      1.0),
    ("one_half",     1.5),
    ("no_time_stop", None),   # sentinel — resolves to 730d
]

# Strategies needing PIT fundamentals (fundamental weight > 0.05).
PIT_REQUIRED_STRATEGIES = {
    "long_term_growth",
    "value_investing",
    "dividend_income",
}


async def _build_pit_loader(tickers: list[str]) -> FundamentalsPITLoader:
    SL = get_sessionmaker()
    async with SL() as session:
        repo = PostgresFundamentalsRepository(session)
        loader = await FundamentalsPITLoader.from_repository(repo, tickers)
    # Dispose so the next asyncio loop doesn't inherit a stale pool —
    # the asyncpg ping crashes on Windows when the old proactor is gone.
    await dispose_engine()
    return loader


def _summarize(label: str, hold_days: int, result: dict[str, Any]) -> dict[str, Any]:
    full = result["full"]
    oos = result["out_of_sample"]
    return {
        "mode": label,
        "max_hold_days": hold_days,
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
        title=f"Time-stop sweep — {strategy_name} on {universe_label}",
        show_lines=False,
    )
    table.add_column("Mode", style="bold")
    table.add_column("Hold days", justify="right")
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
            str(r["max_hold_days"]),
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
    parser = argparse.ArgumentParser(description="A/B sweep on triple-barrier time stop.")
    parser.add_argument("--strategy", required=True)
    parser.add_argument(
        "--universe",
        choices=["themes", "watchlist", "value_cohort", "russell_1000"],
        default="russell_1000",
    )
    parser.add_argument("--years", type=float, default=2.0)
    parser.add_argument("--min-score", type=float, default=None,
                        help="Override strategy's min_score (else uses the config value).")
    parser.add_argument("--atr-stop", type=float, default=2.0)
    parser.add_argument("--cash", type=float, default=10_000.0)
    parser.add_argument("--max-positions", type=int, default=20)
    parser.add_argument("--commission", type=float, default=0.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--regulatory-bps", type=float, default=3.0)
    parser.add_argument("--earnings-blackout", type=int, default=3)
    parser.add_argument("--bootstrap-resamples", type=int, default=0)
    parser.add_argument("--save", required=True,
                        help="Path for the per-mode summary JSON.")
    parser.add_argument("--save-full", default=None,
                        help="Optional path to dump per-mode BacktestResult dicts.")
    parser.add_argument("--no-pit", action="store_true",
                        help="Skip PIT loader even for fundamental strategies "
                             "(overrides auto-enable).")
    args = parser.parse_args()

    config = Config()
    strategy = config.get_strategy(args.strategy)
    base_time_stop = int(strategy.get("time_stop_days", 90))

    # Resolve universe.
    if args.universe == "themes":
        tickers = config.get_theme_tickers()
    elif args.universe == "watchlist":
        tickers = config.get_watchlist()
    elif args.universe == "value_cohort":
        tickers = config.get_value_cohort_tickers()
    elif args.universe == "russell_1000":
        tickers = config.get_russell_1000_tickers()
    else:
        tickers = []
    if not tickers:
        console.print(f"[red]No tickers for universe '{args.universe}'[/red]")
        return 1
    universe_label = f"{args.universe} ({len(tickers)})"
    console.print(
        f"Time-stop sweep — [bold]{args.strategy}[/bold] on {universe_label}, "
        f"base time_stop_days={base_time_stop}, years={args.years}"
    )

    end = pd.Timestamp.now().normalize()
    start = end - pd.Timedelta(days=int(365.25 * args.years))
    fetch_period_years = max(args.years + 2, 5)

    # Heavy I/O once — price data, fundamentals, earnings, SPY/VIX.
    cache = DataCache()
    fetcher = DataFetcher(cache=cache)
    f_fetcher = FundamentalsFetcher(cache=cache)

    console.print(f"Fetching prices for {len(tickers)} tickers …")
    t0 = time.time()
    price_data = fetcher.get_historical_data_batch(
        tickers, period=f"{int(fetch_period_years)}y", workers=8
    )
    console.print(f"  prices done in {time.time()-t0:.1f}s "
                  f"({len(price_data)}/{len(tickers)} tickers loaded)")

    console.print("Fetching fundamentals snapshot …")
    t0 = time.time()
    fundamentals = f_fetcher.get_fundamentals_batch(tickers, workers=8)
    console.print(f"  fundamentals done in {time.time()-t0:.1f}s")

    console.print("Fetching SPY + VIX history …")
    spy_df = fetcher.get_historical_data("SPY", period=f"{int(fetch_period_years)}y")
    vix_df = fetcher.get_historical_data("^VIX", period=f"{int(fetch_period_years)}y")

    console.print("Fetching earnings dates / history …")
    t0 = time.time()
    earnings_dates = fetch_earnings_dates(list(price_data.keys()), workers=8)
    earnings_history = fetch_earnings_history(list(price_data.keys()), workers=8)
    console.print(f"  earnings done in {time.time()-t0:.1f}s")

    pit_loader = None
    use_pit = (
        not args.no_pit and args.strategy in PIT_REQUIRED_STRATEGIES
    )
    if use_pit:
        console.print("Loading EDGAR PIT fundamentals from Postgres …")
        t0 = time.time()
        pit_loader = asyncio.run(_build_pit_loader(list(price_data.keys())))
        console.print(f"  PIT loaded in {time.time()-t0:.1f}s")

    # Run per-mode backtests.
    summary_rows: list[dict[str, Any]] = []
    full_results: dict[str, dict] = {}
    t_sweep = time.time()
    for label, mult in MODES:
        hold_days = 730 if mult is None else max(1, int(round(base_time_stop * mult)))
        console.print(f"\n[bold]Mode={label}[/bold] max_hold_days={hold_days}")
        bt_cfg = BacktestConfig(
            start_date=start,
            end_date=end,
            min_score=args.min_score if args.min_score is not None else strategy.get("min_score", 65),
            max_open_positions=args.max_positions,
            max_position_pct=0.10,
            starting_cash=args.cash,
            max_hold_days=hold_days,
            atr_stop_mult=args.atr_stop,
            commission_per_trade=args.commission,
            slippage_bps=args.slippage_bps,
            regulatory_bps_on_sale=args.regulatory_bps,
            earnings_blackout_days=args.earnings_blackout,
            bootstrap_resamples=args.bootstrap_resamples,
        )
        t0 = time.time()
        result = run_backtest(
            price_data,
            fundamentals,
            config,
            strategy,
            bt_cfg,
            spy_df=spy_df,
            vix_df=vix_df,
            earnings_dates=earnings_dates,
            earnings_history=earnings_history,
            fundamentals_pit_loader=pit_loader,
        )
        elapsed = time.time() - t0
        row = _summarize(label, hold_days, result)
        row["elapsed_sec"] = round(elapsed, 1)
        summary_rows.append(row)
        full_results[label] = result
        console.print(
            f"  done in {elapsed:.1f}s — OOS Sharpe {row['oos_sharpe']:+.2f}, "
            f"{row['n_oos_trades']} OOS trades"
        )

    total = time.time() - t_sweep
    console.print(f"\n[bold]Sweep total: {total:.1f}s[/bold]")
    _print_table(summary_rows, args.strategy, universe_label)

    # Persist.
    save_path = Path(args.save)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(
        json.dumps(summary_rows, indent=2),
        encoding="utf-8",
    )
    console.print(f"Summary written → {save_path}")

    if args.save_full:
        full_path = Path(args.save_full)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(
            json.dumps(full_results, indent=2, default=str),
            encoding="utf-8",
        )
        console.print(f"Full per-mode results → {full_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
