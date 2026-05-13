"""Catalyst A/B sweep.

Three modes on the swing_trading + themes harness:

  off              : catalyst snapshots withheld entirely from the
                     backtest engine. Composite has no catalyst slot.
  signal_only      : snapshots passed in (analyzer fires per Monday),
                     but the catalyst sub-score weight is 0 — only
                     the bullish/bearish signal-consensus adjustment
                     can move the composite.
  weighted         : analyzer fires AND catalyst is weighted at 0.10
                     in the composite, with other weights scaled
                     down proportionally to keep the total normalized.

The "signal_only vs weighted" distinction has been informative on
prior sweeps (RS, insider_flow) — signals often contribute most of
their lift through the consensus adjustment; explicitly weighting a
sparse sub-score is usually a wash or worse.

Requires: ``insider_narrative_snapshots`` populated. Run
``scripts/backfill_insider_narrative.py --universe themes`` first.
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
from src.db.models import InsiderNarrativeSnapshot
from src.db.session import dispose_engine, get_sessionmaker
from src.backtest.engine import (
    BacktestConfig,
    fetch_earnings_history,
    run_backtest,
)

console = Console()


# (label, weight_in_composite, run_analyzer)
MODES: list[tuple[str, float, bool]] = [
    ("off",          0.0,  False),
    ("signal_only",  0.0,  True),
    ("weighted",     0.10, True),
]


def _strategy_with_catalyst_weight(
    base_strategy: dict, weight: float
) -> dict:
    """Same proportional scale-down pattern as the insider_flow sweep:
    keep the total weight constant at the base's original sum so the
    weighted composite is comparable across modes."""
    strat = deepcopy(base_strategy)
    weights = strat.get("weights", {}) or {}
    if weight <= 0:
        weights["catalyst"] = 0.0
        strat["weights"] = weights
        return strat
    other_sum = sum(weights.values())
    if other_sum <= 0:
        weights["catalyst"] = weight
        strat["weights"] = weights
        return strat
    scale = (1.0 - weight) / other_sum
    weights = {k: v * scale for k, v in weights.items()}
    weights["catalyst"] = weight
    strat["weights"] = weights
    return strat


async def _load_narrative_snapshots(
    tickers: list[str],
) -> dict[str, list]:
    """Pull all narrative snapshots for the universe into memory once.
    The backtest engine picks the most-recent-on-or-before-as_of per
    Monday from this map (cheaper than per-Monday SQL)."""
    SL = get_sessionmaker()
    out: dict[str, list] = {}
    async with SL() as session:
        stmt = (
            select(InsiderNarrativeSnapshot)
            .where(
                InsiderNarrativeSnapshot.ticker.in_([t.upper() for t in tickers])
            )
            .order_by(InsiderNarrativeSnapshot.cluster_end_date.asc())
        )
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            # Detach so the engine can keep using these objects after
            # we close the session.
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
        "catalyst_weight": weight,
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
        title=f"Catalyst A/B — {strategy_name} on {universe_label}",
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
            f"{r['catalyst_weight']:.2f}",
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
    parser = argparse.ArgumentParser(description="A/B sweep on catalyst analyzer.")
    parser.add_argument("--strategy", default="swing_trading")
    parser.add_argument(
        "--universe",
        choices=["themes", "watchlist", "value_cohort"],
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
    parser.add_argument("--save", default="data/sweep_catalyst.json")
    args = parser.parse_args()

    config = Config()
    base_strategy = config.get_strategy(args.strategy)

    if args.universe == "themes":
        tickers = config.get_theme_tickers()
        universe_label = f"themes ({len(tickers)})"
    elif args.universe == "value_cohort":
        tickers = config.get_value_cohort_tickers()
        universe_label = f"value_cohort ({len(tickers)})"
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

    console.print(f"\n[bold cyan]Catalyst A/B sweep[/bold cyan]")
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

    console.print("[bold]Loading narrative snapshots from Postgres...[/bold]")
    snaps = asyncio.run(_load_narrative_snapshots(tickers))
    n_snaps = sum(len(v) for v in snaps.values())
    n_with_8k = sum(
        1 for ts in snaps.values() for s in ts if s.has_recent_8k
    )
    console.print(
        f"  Loaded {n_snaps} snapshots ({n_with_8k} with recent 8-K) "
        f"across {len(snaps)} tickers\n"
    )
    if n_snaps == 0:
        console.print(
            "[red]No narrative snapshots in DB — run "
            "`python -m scripts.backfill_insider_narrative` first.[/red]"
        )
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
        strat = _strategy_with_catalyst_weight(base_strategy, weight)
        # Withhold the narrative snapshots in 'off' mode so the
        # analyzer can't even fire into the consensus adjustment.
        snaps_for_run = snaps if run_analyzer else None
        console.print(
            f"[bold cyan]Running mode={mode} (weight={weight}, "
            f"analyzer={'on' if run_analyzer else 'off'})...[/bold cyan]"
        )
        t0 = time.time()
        result = run_backtest(
            price_data, fundamentals, config, strat, bt_cfg,
            spy_df=spy_df, vix_df=vix_df, earnings_dates=earnings_dates,
            narrative_snapshots=snaps_for_run,
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
