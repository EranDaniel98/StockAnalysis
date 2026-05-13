"""DERA bulk-archive backfill driver.

Pulls SEC DERA financial-statement-dataset quarter zips and upserts every
in-universe 10-K/10-Q filing's fundamentals into Postgres. One ~50-200MB
download per quarter replaces ~1000 individual companyfacts requests when
the universe is the Russell 1000.

Usage:
    # Small smoke test (1 quarter, custom tickers)
    uv run python -m scripts.run_edgar_bulk_backfill \\
        --tickers AAPL,MSFT --start-year 2023 --start-q 4 --end-year 2023 --end-q 4

    # Full Russell 1000 backfill, last 5 years
    uv run python -m scripts.run_edgar_bulk_backfill \\
        --universe russell_1000 --start-year 2020 --start-q 1 --end-year 2024 --end-q 4

The ticker→CIK map is fetched lazily via the existing EDGAR HTTP client
(one request for the SEC company_tickers.json index). Quarter zips are
downloaded on demand and cached under ``.cache/edgar_bulk/``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from src.db.session import dispose_engine, get_sessionmaker
from src.market_data.edgar.client import EDGARClient, get_ticker_to_cik
from src.market_data.edgar_bulk.client import BulkArchiveClient, iter_year_quarter_pairs
from src.market_data.edgar_bulk.ingest import ingest_range

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_edgar_bulk_backfill")


def _resolve_universe(name: str) -> list[str]:
    from src.config_loader import Config

    config = Config()
    if name == "themes":
        return config.get_theme_tickers()
    if name == "watchlist":
        return config.get_watchlist()
    if name == "value_cohort":
        return config.get_value_cohort_tickers()
    if name == "russell_1000":
        return config.get_russell_1000_tickers()
    if name == "all":
        return sorted(
            set(config.get_theme_tickers())
            | set(config.get_value_cohort_tickers())
            | set(config.get_russell_1000_tickers())
        )
    raise ValueError(
        f"Unknown universe {name!r}; choose themes|watchlist|value_cohort|russell_1000|all"
    )


async def _fetch_cik_map(tickers: list[str]) -> dict[str, int]:
    """Pull the SEC ticker→CIK index once and filter to the universe."""
    client = EDGARClient()
    try:
        full = await get_ticker_to_cik(client)
    finally:
        await client.aclose()
    upper = {t.upper() for t in tickers}
    filtered = {t: c for t, c in full.items() if t in upper}
    missing = upper - set(filtered.keys())
    if missing:
        logger.warning(
            "Could not resolve CIK for %d tickers: %s",
            len(missing), sorted(missing)[:20],
        )
    return filtered


async def run(
    tickers: list[str],
    start_year: int,
    start_q: int,
    end_year: int,
    end_q: int,
    no_download: bool,
) -> int:
    pairs = list(iter_year_quarter_pairs(start_year, start_q, end_year, end_q))
    logger.info(
        "Backfilling %d tickers across %d quarters (%dq%d → %dq%d)",
        len(tickers), len(pairs), start_year, start_q, end_year, end_q,
    )

    ticker_to_cik = await _fetch_cik_map(tickers)
    if not ticker_to_cik:
        logger.error("No CIK mappings resolved — aborting.")
        return 1

    bulk_client = BulkArchiveClient()
    sessionmaker = get_sessionmaker()
    try:
        results = await ingest_range(
            pairs,
            ticker_to_cik,
            sessionmaker,
            client=bulk_client,
            download=not no_download,
        )
    finally:
        await dispose_engine()

    total = sum(results.values())
    logger.info("Wrote %d fundamental snapshots across %d quarters", total, len(results))
    for (y, q), n in sorted(results.items()):
        logger.info("  %dq%d: %d rows", y, q, n)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--tickers", type=str, help="Comma-separated ticker list")
    src.add_argument(
        "--universe",
        type=str,
        choices=("themes", "watchlist", "value_cohort", "russell_1000", "all"),
    )
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--start-q", type=int, default=1, choices=(1, 2, 3, 4))
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument("--end-q", type=int, default=4, choices=(1, 2, 3, 4))
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Use cache only; fail on missing zips instead of fetching from SEC.",
    )
    args = parser.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = _resolve_universe(args.universe)

    exit_code = asyncio.run(
        run(
            tickers=tickers,
            start_year=args.start_year,
            start_q=args.start_q,
            end_year=args.end_year,
            end_q=args.end_q,
            no_download=args.no_download,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
