"""Freeze yfinance inputs into an immutable backtest snapshot.

One-shot script. Pull prices + fundamentals + earnings + SPY + VIX
for the configured universe and window, write them under
``data/snapshots/<snapshot_id>/``, print the snapshot id so
follow-up runners can pin to it.

Usage
-----
    uv run python -m scripts.freeze_snapshot \\
        --universe russell_1000 \\
        --window-end 2024-05-13 \\
        --years 2 \\
        --pre-buffer-days 7 \\
        --post-buffer-days 120

The post-buffer is for forward-return windows in IC reports (alphalens
needs prices past the panel end for 21D / 42D forward returns).

The pre-buffer is for analyzers that need pre-window history to warm
up indicators (technical SMA200 etc.).

Snapshot id is content-addressed — re-running with the same data
returns the same id. Different yfinance pulls produce different ids
even if the requested window is the same.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

import pandas as pd

from src.config_loader import Config


logger = logging.getLogger("freeze_snapshot")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Freeze a backtest's yfinance inputs into a Parquet "
                    "snapshot. Produces a content-addressed id callers "
                    "can pin to.",
    )
    p.add_argument("--universe", default="russell_1000",
                   choices=("russell_1000",))
    p.add_argument("--window-end", required=True,
                   help="ISO end date for the backtest window (e.g. "
                        "2024-05-13)")
    p.add_argument("--years", type=float, default=2.0,
                   help="Years before window-end the window starts.")
    p.add_argument("--pre-buffer-days", type=int, default=400,
                   help="Calendar days of pre-window history to include "
                        "(default 400 ≈ SMA200 + buffer).")
    p.add_argument("--post-buffer-days", type=int, default=120,
                   help="Calendar days of post-window history to include "
                        "(for forward-return IC at 42D + alphalens runway).")
    p.add_argument("--workers", type=int, default=10)
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Lazy imports — pulling the engine pulls in many analyzer deps.
    from src.data.cache import DataCache
    from src.data.fetcher import DataFetcher
    from src.data.fundamentals import FundamentalsFetcher
    from src.backtest.engine import PIPELINE_VERSION, fetch_earnings_history
    from src.storage.snapshot import write_snapshot

    config = Config()

    if args.universe == "russell_1000":
        tickers = config.get_russell_1000_tickers()
    else:
        logger.error("Unknown universe %s", args.universe)
        return 2
    if not tickers:
        logger.error("Universe %s has no tickers — run "
                     "scripts/fetch_russell_1000.py first.", args.universe)
        return 2

    end = pd.Timestamp(args.window_end)
    start = end - pd.DateOffset(years=int(args.years))

    # Survivorship guard parity: refuse if end is past the universe
    # captured date.
    try:
        captured = config.get_universe_captured_date(args.universe)
    except ValueError as exc:
        logger.error("Universe captured-date header malformed: %s", exc)
        return 2
    if captured is not None and end > pd.Timestamp(captured):
        logger.error(
            "Backtest end %s > universe captured-date %s — refuse to "
            "freeze a snapshot that would trip the survivorship guard.",
            end.date(), pd.Timestamp(captured).date(),
        )
        return 3

    pre_buffer = pd.Timedelta(days=args.pre_buffer_days)
    post_buffer = pd.Timedelta(days=args.post_buffer_days)
    fetch_start = start - pre_buffer
    fetch_end = end + post_buffer

    logger.info(
        "Snapshot: window %s -> %s | fetch %s -> %s | universe %s (%d tickers)",
        start.date(), end.date(), fetch_start.date(), fetch_end.date(),
        args.universe, len(tickers),
    )

    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5,
        ),
    )
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    # yfinance period strings — request enough to span pre_buffer +
    # window + post_buffer comfortably.
    total_years = max(1, int((fetch_end - fetch_start).days / 365) + 1)
    period = f"{total_years + 1}y"

    logger.info("Fetching prices (period=%s)...", period)
    raw_prices = fetcher.fetch_batch(tickers)
    # Trim each frame to the fetch window so we don't snapshot
    # arbitrarily-deep history (some yfinance pulls return 10y of data).
    price_data: dict[str, pd.DataFrame] = {}
    for ticker, df in raw_prices.items():
        if df is None or df.empty:
            continue
        d = df.copy()
        if d.index.tz is not None:
            d.index = d.index.tz_localize(None)
        d = d.loc[(d.index >= fetch_start) & (d.index <= fetch_end)]
        if not d.empty:
            price_data[ticker] = d

    logger.info("Fetching fundamentals...")
    raw_fund = fund_fetcher.fetch_batch(tickers)
    fundamentals = {t: fd for t, fd in raw_fund.items()
                    if isinstance(fd, dict) and fd}

    logger.info("Fetching earnings history...")
    earnings_history = fetch_earnings_history(
        list(price_data.keys()), workers=args.workers,
    )

    logger.info("Fetching SPY benchmark...")
    spy = fetcher.fetch_price_data("SPY", period=period)
    if spy is not None and not spy.empty:
        if spy.index.tz is not None:
            spy.index = spy.index.tz_localize(None)
        spy = spy.loc[(spy.index >= fetch_start) & (spy.index <= fetch_end)]

    logger.info("Fetching ^VIX...")
    vix = fetcher.fetch_price_data("^VIX", period=period)
    if vix is not None and not vix.empty:
        if vix.index.tz is not None:
            vix.index = vix.index.tz_localize(None)
        vix = vix.loc[(vix.index >= fetch_start) & (vix.index <= fetch_end)]

    logger.info("Writing snapshot...")
    manifest = write_snapshot(
        price_data=price_data,
        fundamentals=fundamentals,
        earnings_history=earnings_history,
        spy_df=spy,
        vix_df=vix,
        universe_label=args.universe,
        window_start=start,
        window_end=end,
        pipeline_version=PIPELINE_VERSION,
    )

    logger.info(
        "Snapshot %s — %d prices, %d fundamentals, %d earnings, "
        "spy=%s vix=%s",
        manifest.snapshot_id,
        manifest.n_tickers_with_prices,
        manifest.n_tickers_with_fundamentals,
        manifest.n_tickers_with_earnings,
        manifest.has_spy, manifest.has_vix,
    )
    # Print id to stdout last so callers can capture it.
    print(manifest.snapshot_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
