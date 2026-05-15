"""Run the minimal_baseline strategy (review item #6) against the
clean-pipeline universe and dump the full backtest result + walk-forward
report to ``data/baseline/minimal_baseline.json``.

This is the CONTROL ARM for evaluating whether the experimental sources
(PEAD, Alpha158, patterns, ML ensemble, insider, catalysts, sector
flows, short interest, research agent) add real edge. Any richer
strategy that fails to beat this on OOS Sharpe + alpha-vs-SPY does NOT
deserve to keep its extra sources.

Usage:
    uv run python -m scripts.run_minimal_baseline \\
        [--universe russell_1000] \\
        [--years 2] \\
        [--starting-cash 10000]

Output written to data/baseline/minimal_baseline.json. Consumed by
``scripts/produce_mvtp_report.py`` (review item #7).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.config_loader import Config

logger = logging.getLogger("minimal_baseline")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the minimal_baseline control strategy.",
    )
    p.add_argument("--universe", default="russell_1000",
                   choices=("russell_1000",))
    p.add_argument("--years", type=float, default=2.0,
                   help="Backtest window length, years (default 2)")
    p.add_argument("--starting-cash", type=float, default=10_000.0)
    p.add_argument("--output",
                   default="data/baseline/minimal_baseline.json")
    p.add_argument("--pit-fundamentals", action="store_true",
                   help="Use EDGAR PIT loader for fundamentals "
                        "(strongly recommended).")
    p.add_argument("--walk-forward-folds", type=int, default=5,
                   help="N-fold walk-forward CV (review #5)")
    p.add_argument("--min-mean-sharpe", type=float, default=0.5,
                   help="Walk-forward gate threshold")
    p.add_argument("--end-date",
                   help="ISO date; defaults to min(today, universe-captured). "
                        "Pass explicitly to test a custom window.")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Lazy imports — the engine module pulls in the full analyzer chain,
    # which we want only after argparse has done its thing.
    from src.backtest.engine import (
        BacktestConfig,
        SurvivorshipGuardError,
        fetch_earnings_history,
        run_backtest,
    )
    from src.data.cache import DataCache
    from src.data.fetcher import DataFetcher
    from src.data.fundamentals import FundamentalsFetcher

    config = Config()
    strategy = config.get_strategy("minimal_baseline")
    if strategy is None:
        logger.error(
            "Strategy 'minimal_baseline' not found in config/strategies.yaml. "
            "Did you skip the review-#6 edit?"
        )
        return 2

    # Universe selection
    if args.universe == "russell_1000":
        tickers = config.get_russell_1000_tickers()
    else:
        logger.error("Unknown universe %s", args.universe)
        return 2

    if not tickers:
        logger.error(
            "Universe %s has no tickers. Run scripts/fetch_russell_1000.py "
            "first.", args.universe,
        )
        return 2

    logger.info("Universe %s: %d tickers", args.universe, len(tickers))

    # Cache + fetchers
    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5,
        ),
    )
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    # Default end_date: min(today, universe-captured). The survivorship
    # guard refuses end > captured, so picking the smaller automatically
    # keeps the run within the safe window. Explicit --end-date wins.
    today = pd.Timestamp.utcnow().normalize().tz_localize(None)
    try:
        captured = config.get_universe_captured_date(args.universe)
    except ValueError as exc:
        logger.error("Universe captured-date header malformed: %s", exc)
        return 2
    if args.end_date:
        end = pd.Timestamp(args.end_date)
    elif captured is not None:
        end = min(today, pd.Timestamp(captured))
        if end < today:
            logger.info(
                "End_date trimmed to universe-capture date %s (today=%s) "
                "to satisfy the survivorship guard.",
                end.date(), today.date(),
            )
    else:
        end = today
    start = end - pd.DateOffset(years=int(args.years))

    logger.info("Fetching %d ticker price histories (this can take a while)...",
                len(tickers))
    price_data = fetcher.fetch_batch(tickers)
    fundamentals = fund_fetcher.fetch_batch(tickers)

    # Earnings (used by the engine's blackout filter)
    logger.info("Fetching earnings history...")
    earnings_history = fetch_earnings_history(list(price_data.keys()), workers=8)

    # SPY benchmark
    logger.info("Fetching SPY benchmark...")
    spy_df = fetcher.fetch_price_data("SPY", period=f"{int(args.years)+1}y")

    # PIT loader (recommended for fundamental-weighted strategies).
    # Async API: pull all EDGAR rows for the universe in one query, then
    # the engine resolves (ticker, as_of) lookups in-memory. Same shape
    # as scripts/sweep_insider_flow.py and sweep_pit_fundamentals.py.
    pit_loader = None
    if args.pit_fundamentals:
        import asyncio
        from src.scoring.fundamentals_pit_loader import FundamentalsPITLoader
        from src.db.repositories import PostgresFundamentalsRepository
        from src.db.session import get_sessionmaker, dispose_engine

        async def _build_loader() -> FundamentalsPITLoader:
            SL = get_sessionmaker()
            async with SL() as session:
                repo = PostgresFundamentalsRepository(session)
                loader = await FundamentalsPITLoader.from_repository(
                    repo, list(price_data.keys()),
                )
            # Dispose so subsequent asyncio.run() calls don't inherit a
            # connection pool bound to this closed loop (Windows asyncpg
            # proactor crash, audit fix 4199d8a).
            await dispose_engine()
            return loader

        try:
            pit_loader = asyncio.run(_build_loader())
            logger.info(
                "PIT loader active — %d tickers indexed from EDGAR.",
                len(pit_loader._by_ticker),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "PIT loader build failed (%s); proceeding without. "
                "Fundamental weight in minimal_baseline is 0.30 so this WILL "
                "raise LookaheadGuardError unless EDGAR coverage is healthy. "
                "Re-run with EDGAR DB populated to fix.", exc,
            )

    bt_cfg = BacktestConfig(
        start_date=start,
        end_date=end,
        starting_cash=args.starting_cash,
        universe_label=args.universe,
        apply_survivorship_haircut=True,
        refuse_survivor_only_window=True,
        walk_forward_folds=args.walk_forward_folds,
        walk_forward_min_mean_sharpe=args.min_mean_sharpe,
        bootstrap_resamples=500,
        compound=False,
        min_score=strategy.get("min_score", 55),
    )

    logger.info("Backtest start: %s end: %s walk_forward_folds=%d",
                start.date(), end.date(), args.walk_forward_folds)

    try:
        result = run_backtest(
            price_data=price_data,
            fundamentals=fundamentals,
            config=config,
            strategy=strategy,
            bt_cfg=bt_cfg,
            spy_df=spy_df,
            earnings_history=earnings_history,
            fundamentals_pit_loader=pit_loader,
        )
    except SurvivorshipGuardError as exc:
        logger.error("Survivorship guard: %s", exc)
        return 3

    if "error" in result:
        logger.error("Backtest returned error: %s", result["error"])
        return 4

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Strip the full equity curve to keep the file readable; keep just
    # the summary blocks + the walk-forward report (the things the MVTP
    # report consumer reads).
    slim = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "universe": args.universe,
        "strategy": "minimal_baseline",
        "window": {
            "start": start.date().isoformat(),
            "end": end.date().isoformat(),
            "years": args.years,
        },
        "starting_cash": args.starting_cash,
        "pit_fundamentals": args.pit_fundamentals,
        "full": result.get("full"),
        "in_sample": result.get("in_sample"),
        "out_of_sample": result.get("out_of_sample"),
        "split_date": result.get("split_date"),
        "walk_forward": result.get("walk_forward"),
        "regimes": result.get("regimes"),
        "data_quality": result.get("data_quality"),
        "n_trades": len(result.get("trades") or []),
        "warnings": result.get("warnings") or [],
        # PIPELINE_VERSION lives under data_quality.pipeline_version in the
        # engine result (see engine.py:106). Earlier slim build pulled it
        # from top-level and got None; the MVTP report's freshness gate then
        # failed against an unknown pipeline.
        "pipeline_version": (
            (result.get("data_quality") or {}).get("pipeline_version")
        ),
        # Block bootstrap CIs (return + win rate + expectancy + Sharpe).
        # bootstrap_label says whether the CI is on the OOS slice or the
        # full window — engine picks OOS if oos_trades >= 20.
        "bootstrap": result.get("bootstrap"),
        "bootstrap_label": result.get("bootstrap_label"),
        # Top-N-removed concentration sensitivity (review #7 auto-check).
        # MVTP gate fires FAIL if Sharpe drop > 0.4.
        "concentration_sensitivity": result.get("concentration_sensitivity"),
    }
    out.write_text(json.dumps(slim, indent=2, default=str), encoding="utf-8")
    logger.info("Wrote %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
