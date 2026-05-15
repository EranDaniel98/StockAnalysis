"""PIT-fundamentals A/B sweep.

For each fundamental-heavy strategy, run two backtests:

  baseline (lookahead)  : --accept-lookahead flag passes; engine scores
                          against the CURRENT yfinance fundamentals dict
                          at every historical Monday. This is the
                          look-ahead-leaked path the original guard
                          blocked - included so we can quantify how much
                          of the headline alpha was synthetic.
  pit_edgar             : FundamentalsPITLoader pre-loaded from the
                          Postgres fundamentals table; engine looks up
                          the EDGAR row valid at each as_of, layers a
                          PIT-safe overlay (sector / analyst metadata),
                          and scores cleanly. No guard, no leak.

The strategies that need this most are the ones the guard normally blocks
(weights fundamentals ≥35%): long_term_growth, value_investing,
dividend_income. Sweep also accepts swing_trading as a sanity-check -
swing_trading weights fundamentals at 5% (sub-guard threshold) so both
modes should produce nearly identical numbers.

Usage:
    uv run python -m scripts.sweep_pit_fundamentals \
        --strategy long_term_growth,value_investing,dividend_income \
        --universe all --years 3
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
    fetch_earnings_history,
    run_backtest,
)
from src.scoring.fundamentals_pit_loader import FundamentalsPITLoader

console = Console()


# (label, accept_lookahead, use_pit_loader)
MODES: list[tuple[str, bool, bool]] = [
    ("baseline_lookahead", True,  False),
    ("pit_edgar",          False, True),
]


def _resolve_universe(cfg: Config, name: str) -> list[str]:
    if name == "themes":
        return cfg.get_theme_tickers()
    if name == "value_cohort":
        return cfg.get_value_cohort_tickers()
    if name == "watchlist":
        return cfg.get_watchlist()
    if name == "all":
        return sorted(set(cfg.get_theme_tickers()) | set(cfg.get_value_cohort_tickers()))
    raise ValueError(f"Unknown universe {name!r}")


async def _build_loader(tickers: list[str]) -> FundamentalsPITLoader:
    SessionLocal = get_sessionmaker()
    async with SessionLocal() as session:
        repo = PostgresFundamentalsRepository(session)
        loader = await FundamentalsPITLoader.from_repository(repo, tickers)
    # Dispose inside this run so the trailing asyncio.run(dispose_engine())
    # at script end doesn't try to dispose a pool bound to a different
    # (now-closed) loop. Same fix the other sweep scripts use; matches
    # commit 4199d8a where this pattern was first established.
    await dispose_engine()
    return loader


def _summarize(mode: str, strategy: str, result: dict[str, Any]) -> dict[str, Any]:
    full = result["full"]
    oos = result["out_of_sample"]
    return {
        "strategy": strategy,
        "mode": mode,
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
        title=f"PIT-fundamentals A/B on {universe_label}",
        show_lines=False,
    )
    table.add_column("Strategy", style="bold")
    table.add_column("Mode")
    table.add_column("Trades", justify="right")
    table.add_column("OOS n", justify="right")
    table.add_column("Full ret %", justify="right")
    table.add_column("OOS ret %", justify="right")
    table.add_column("Full Sharpe", justify="right")
    table.add_column("OOS Sharpe", justify="right", style="bold")
    table.add_column("Max DD %", justify="right")
    table.add_column("Win %", justify="right")
    # Per-strategy delta (PIT vs baseline) - the key comparison.
    baseline_oos = {
        r["strategy"]: r["oos_sharpe"]
        for r in rows
        if r["mode"] == "baseline_lookahead"
    }
    for r in rows:
        base = baseline_oos.get(r["strategy"])
        delta = ""
        if r["mode"] == "pit_edgar" and base is not None:
            delta = f"  (D {r['oos_sharpe'] - base:+.2f})"
        table.add_row(
            r["strategy"],
            r["mode"],
            str(r["n_trades"]),
            str(r["n_oos_trades"]),
            f"{r['full_return_pct']:+.2f}",
            f"{r['oos_return_pct']:+.2f}",
            f"{r['full_sharpe']:+.2f}",
            f"{r['oos_sharpe']:+.2f}{delta}",
            f"{r['max_dd_pct']:.2f}",
            f"{r['win_rate_pct']:.1f}",
        )
    console.print(table)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strategy",
        default="long_term_growth,value_investing,dividend_income",
        help="Comma-separated strategy names.",
    )
    parser.add_argument(
        "--universe",
        choices=("themes", "value_cohort", "watchlist", "all"),
        default="all",
    )
    parser.add_argument("--years", type=float, default=3.0)
    parser.add_argument(
        "--period",
        default=None,
        help="yfinance period override (e.g. 'max', '10y'). "
        "Default: max(years+2, 5)y. Use 'max' to fetch full per-ticker history.",
    )
    parser.add_argument("--min-score", type=float, default=50.0)
    parser.add_argument("--atr-stop", type=float, default=2.0)
    parser.add_argument("--cash", type=float, default=10_000.0)
    parser.add_argument("--max-positions", type=int, default=20)
    parser.add_argument("--save", default="data/sweep_pit_fundamentals.json")
    args = parser.parse_args()

    config = Config()
    strategy_names = [s.strip() for s in args.strategy.split(",") if s.strip()]
    base_strategies = {s: config.get_strategy(s) for s in strategy_names}

    tickers = _resolve_universe(config, args.universe)
    universe_label = f"{args.universe} ({len(tickers)})"
    if not tickers:
        console.print(f"[red]Empty universe '{args.universe}'[/red]")
        return 1

    end = pd.Timestamp.now().normalize()
    start = end - pd.Timedelta(days=int(365.25 * args.years))
    fetch_period = args.period or f"{int(max(args.years + 2, 5))}y"

    console.print("\n[bold cyan]PIT-fundamentals A/B sweep[/bold cyan]")
    console.print(f"  Strategies: [bold]{', '.join(strategy_names)}[/bold] ({len(strategy_names)} total)")
    console.print(f"  Universe:   [bold]{universe_label}[/bold]")
    console.print(f"  Window:     {start.strftime('%Y-%m-%d')} -> {end.strftime('%Y-%m-%d')}\n")

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

    console.print("[bold]Fetching fundamentals (yfinance current snapshot - used as PIT-safe overlay)...[/bold]")
    fundamentals = fund_fetcher.fetch_batch(tickers)
    console.print(f"  Got fundamentals for {len(fundamentals)}/{len(tickers)} tickers")

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

    console.print("[bold]Loading EDGAR PIT loader from Postgres...[/bold]")
    loader = asyncio.run(_build_loader(list(price_data.keys())))
    coverage = loader.coverage()
    n_covered = sum(1 for t in price_data if t.upper() in loader.tickers)
    pct = (n_covered / max(1, len(price_data))) * 100
    console.print(f"  PIT coverage: {n_covered}/{len(price_data)} tickers ({pct:.0f}%) "
                  f"- total rows {sum(coverage.values())}")
    if pct < 50:
        console.print(
            f"[red]Coverage <50% - engine guard will not be bypassed.[/red] "
            f"Backfill missing tickers via `python -m scripts.run_edgar_backfill --universe {args.universe}`."
        )
    console.print()

    all_rows: list[dict[str, Any]] = []
    for strategy_name in strategy_names:
        base_strategy = base_strategies[strategy_name]
        console.print(f"\n[bold magenta]== Strategy: {strategy_name} ==[/bold magenta]")
        for mode, accept_lookahead, use_loader in MODES:
            bt_cfg = BacktestConfig(
                start_date=start,
                end_date=end,
                min_score=args.min_score,
                atr_stop_mult=args.atr_stop,
                max_open_positions=args.max_positions,
                starting_cash=args.cash,
                accept_lookahead=accept_lookahead,
            )
            console.print(f"[bold cyan]Running mode={mode}...[/bold cyan]")
            t0 = time.time()
            result = run_backtest(
                price_data, fundamentals, config, base_strategy, bt_cfg,
                spy_df=spy_df, vix_df=vix_df, earnings_dates=earnings_dates,
                fundamentals_pit_loader=loader if use_loader else None,
            )
            elapsed = time.time() - t0
            summary = _summarize(mode, strategy_name, result)
            console.print(
                f"  done in {elapsed:.1f}s - OOS Sharpe {summary['oos_sharpe']:+.2f}, "
                f"trades {summary['n_trades']}, win rate {summary['win_rate_pct']:.1f}%\n"
            )
            all_rows.append(summary)

    _print_table(all_rows, universe_label)

    save_path = Path(args.save)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(json.dumps(all_rows, indent=2, default=str), encoding="utf-8")
    console.print(f"\n[dim]Saved {len(all_rows)} comparison rows to {save_path}[/dim]")

    # Engine was disposed inside _build_loader so its asyncpg pool didn't
    # outlive that loop. Nothing else opened a new pool, so no further
    # cleanup needed here.
    return 0


if __name__ == "__main__":
    sys.exit(main())
