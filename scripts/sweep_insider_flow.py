"""Insider-flow A/B sweep.

Three modes on the swing_trading + themes harness:

  off              : insider_flow weight = 0 AND analyzer skipped
                     entirely (no signals contribute to the
                     consensus adjustment either) — clean baseline.
  signal_only      : analyzer runs (signals feed the ±5 consensus
                     adjustment) but rel_strength-equivalent weight=0.
  weighted         : analyzer runs AND insider_flow weighted at 0.10
                     (replaces 10% of composite).

The "signal_only vs weighted" distinction matters because earlier
sweeps (RS) showed signals contribute most of the lift through
consensus — putting weight on the sub-score is often a wash or worse.

Requires: insider_transactions table populated for the themes
universe (run scripts/backfill_insider --universe themes --days 1095
first).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from src.config_loader import Config
from src.data.cache import DataCache
from src.data.fetcher import DataFetcher
from src.data.fundamentals import FundamentalsFetcher
from src.db.models import InsiderTransaction as InsiderTxRow
from src.db.session import dispose_engine, get_sessionmaker
from src.backtest.engine import (
    BacktestConfig,
    fetch_earnings_history,
    run_backtest,
)
import src.scoring.analyzers.insider_flow as if_module

console = Console()


# (label, weight_in_composite, run_analyzer)
MODES: list[tuple[str, float, bool]] = [
    ("off",          0.0,  False),
    ("signal_only",  0.0,  True),
    ("weighted",     0.10, True),
]


def _strategy_with_insider_weight(
    base_strategy: dict, weight: float
) -> dict:
    """Same proportional scale-down pattern as the RS sweep so the
    weight total stays at the base's original sum."""
    strat = deepcopy(base_strategy)
    weights = strat.get("weights", {}) or {}
    if weight <= 0:
        weights["insider_flow"] = 0.0
        strat["weights"] = weights
        return strat
    other_sum = sum(weights.values())
    if other_sum <= 0:
        weights["insider_flow"] = weight
        strat["weights"] = weights
        return strat
    scale = (1.0 - weight) / other_sum
    weights = {k: v * scale for k, v in weights.items()}
    weights["insider_flow"] = weight
    strat["weights"] = weights
    return strat


async def _load_insider_transactions(
    tickers: list[str],
) -> dict[str, list]:
    """Fetch all insider transactions for the universe once, then
    keep them in memory. The backtest engine slices per-Monday from
    this map — much cheaper than N tickers × M Mondays SQL calls."""
    SL = get_sessionmaker()
    out: dict[str, list] = {}
    async with SL() as session:
        stmt = (
            select(InsiderTxRow)
            .where(InsiderTxRow.ticker.in_([t.upper() for t in tickers]))
            .order_by(InsiderTxRow.transaction_date.asc())
        )
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            # Detach from session so the engine can use them after we close
            session.expunge(row)
            out.setdefault(row.ticker, []).append(row)
    await dispose_engine()
    return out


def _summarize(
    mode: str, weight: float, run_analyzer: bool, result: dict[str, Any]
) -> dict[str, Any]:
    full = result["full"]
    oos = result["out_of_sample"]
    return {
        "mode": mode,
        "insider_weight": weight,
        "analyzer_active": run_analyzer,
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
        title=f"Insider-flow A/B — {strategy_name} on {universe_label}",
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
            f"{r['insider_weight']:.2f}",
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
    parser = argparse.ArgumentParser(description="A/B sweep on insider_flow analyzer.")
    parser.add_argument("--strategy", default="swing_trading")
    parser.add_argument(
        "--universe",
        choices=["themes", "watchlist", "value_cohort", "russell_1000"],
        default="themes",
    )
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
    parser.add_argument("--save", default="data/sweep_insider_flow.json")
    args = parser.parse_args()

    config = Config()
    base_strategy = config.get_strategy(args.strategy)

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
    universe_label = f"{args.universe} ({len(tickers)})"

    if not tickers:
        console.print(f"[red]No tickers found for universe '{args.universe}'[/red]")
        return 1

    end = pd.Timestamp.now().normalize()
    start = end - pd.Timedelta(days=int(365.25 * args.years))
    fetch_period_years = max(args.years + 2, 5)
    fetch_period = f"{int(fetch_period_years)}y"

    console.print(f"\n[bold cyan]Insider-flow A/B sweep[/bold cyan]")
    console.print(f"  Strategy: [bold]{args.strategy}[/bold]")
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

    console.print("[bold]Loading insider transactions from Postgres...[/bold]")
    insider_txs = asyncio.run(_load_insider_transactions(tickers))
    n_txs = sum(len(v) for v in insider_txs.values())
    n_buys = sum(
        1 for txs in insider_txs.values() for tx in txs
        if tx.transaction_code == "P" and tx.acquired_disposed == "A"
    )
    console.print(
        f"  Loaded {n_txs} transactions ({n_buys} open-market buys) "
        f"across {len(insider_txs)} tickers\n"
    )
    if n_buys == 0:
        console.print("[red]No open-market buys in DB — backfill not run?[/red]")
        return 1

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
    for mode, weight, run_analyzer in MODES:
        strat = _strategy_with_insider_weight(base_strategy, weight)
        # Withhold the insider data entirely when running the off-baseline
        # so the analyzer can't fire signals into the consensus adjustment.
        ins_for_run = insider_txs if run_analyzer else None
        console.print(
            f"[bold cyan]Running mode={mode} (weight={weight}, "
            f"analyzer={'on' if run_analyzer else 'off'})...[/bold cyan]"
        )
        t0 = time.time()
        result = run_backtest(
            price_data, fundamentals, config, strat, bt_cfg,
            spy_df=spy_df, vix_df=vix_df, earnings_dates=earnings_dates,
            insider_transactions=ins_for_run,
        )
        elapsed = time.time() - t0
        summary = _summarize(mode, weight, run_analyzer, result)
        console.print(
            f"  done in {elapsed:.1f}s — OOS Sharpe {summary['oos_sharpe']:+.2f}, "
            f"trades {summary['n_trades']}, win rate {summary['win_rate_pct']:.1f}%\n"
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
