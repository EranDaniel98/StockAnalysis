"""Backfill (or daily-tick) factor snapshots into the feature store.

Usage:
    # Backfill 2 years of weekly snapshots for the themes universe.
    uv run python -m scripts.snapshot_features --years 2 --freq W-MON \\
        --universe themes

    # Append today only (cron-friendly).
    uv run python -m scripts.snapshot_features --today --universe themes

This is the data layer behind Phase 4 model training. The same job is also
useful for the calibration drift detector — every snapshot remembers what
the analyzer "would have said" on that day, so we can join later against
realized forward returns to compute true point-in-time IC.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone

import pandas as pd

from src.config_loader import Config
from src.data.cache import DataCache
from src.data.fetcher import DataFetcher
from src.data.fundamentals import FundamentalsFetcher
from src.db.session import dispose_engine, get_sessionmaker
from src.ml.feature_store import (
    DEFAULT_FACTOR_SET,
    compute_and_persist_snapshot,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("snapshot_features")


def _resolve_universe(config: Config, universe: str, tickers_arg: str | None) -> list[str]:
    if tickers_arg:
        return [t.strip().upper() for t in tickers_arg.split(",") if t.strip()]
    if universe == "watchlist":
        return config.get_watchlist()
    if universe == "themes":
        return config.get_theme_tickers()
    if universe == "portfolio":
        from src.portfolio import Portfolio

        return Portfolio(config).get_tickers()
    raise ValueError(f"unknown universe: {universe}")


async def _run(args: argparse.Namespace) -> int:
    config = Config()
    universe = _resolve_universe(config, args.universe, args.tickers)
    if not universe:
        logger.error("empty universe; nothing to snapshot")
        return 2
    logger.info("universe: %d tickers", len(universe))

    # Window
    end = pd.Timestamp(args.end) if args.end else pd.Timestamp.now().normalize()
    if args.today:
        start = end
    elif args.start:
        start = pd.Timestamp(args.start)
    else:
        start = end - pd.Timedelta(days=int(365.25 * args.years))

    # Need extra history before start_date so analyzers like alpha158 can
    # see 260 bars worth of context at the earliest snapshot date.
    fetch_period_years = max(args.years + 2, 5)
    fetch_period = f"{int(fetch_period_years)}y"

    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5
        ),
    )
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    logger.info("fetching price history (%s)", fetch_period)
    price_data = fetcher.fetch_batch(universe, period=fetch_period)
    logger.info("got prices for %d/%d tickers", len(price_data), len(universe))

    logger.info("fetching fundamentals snapshot")
    fundamentals = fund_fetcher.fetch_batch(universe)

    # Schedule of snapshot dates
    if start == end:
        schedule = [end]
    else:
        schedule = pd.date_range(start=start, end=end, freq=args.freq).tolist()
    logger.info(
        "computing %d snapshots from %s to %s",
        len(schedule),
        start.date(),
        end.date(),
    )

    SessionLocal = get_sessionmaker()
    persisted_total = 0
    skipped_total = 0
    async with SessionLocal() as session:
        for as_of in schedule:
            result = await compute_and_persist_snapshot(
                session,
                as_of=as_of.tz_localize(timezone.utc).to_pydatetime()
                if as_of.tz is None
                else as_of.to_pydatetime(),
                price_data=price_data,
                fundamentals=fundamentals,
                config=config,
                factor_set=args.factor_set,
            )
            persisted_total += result.n_persisted
            skipped_total += result.n_skipped
            logger.info(
                "  %s: persisted=%d skipped=%d",
                as_of.date(),
                result.n_persisted,
                result.n_skipped,
            )

    logger.info(
        "done — %d snapshot-rows persisted, %d ticker-day misses (insufficient history)",
        persisted_total,
        skipped_total,
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", default="themes",
                        choices=["watchlist", "portfolio", "themes"])
    parser.add_argument("--tickers", default=None,
                        help="Comma-separated tickers (overrides --universe)")
    parser.add_argument("--years", type=float, default=2.0,
                        help="Backfill window in years. Default 2.")
    parser.add_argument("--start", default=None,
                        help="Override start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None,
                        help="Override end date (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--today", action="store_true",
                        help="Snapshot only today (cron-friendly; ignores --start/--years)")
    parser.add_argument("--freq", default="W-MON",
                        help="Pandas date_range freq. Default W-MON (weekly Mondays).")
    parser.add_argument("--factor-set", default=DEFAULT_FACTOR_SET,
                        help=f"factor_set tag. Default '{DEFAULT_FACTOR_SET}'.")
    args = parser.parse_args()

    async def _go() -> int:
        try:
            return await _run(args)
        finally:
            await dispose_engine()

    sys.exit(asyncio.run(_go()))


if __name__ == "__main__":
    main()
