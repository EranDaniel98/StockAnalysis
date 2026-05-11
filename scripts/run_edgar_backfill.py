"""One-shot EDGAR backfill driver.

Usage:
    # Test with a small ticker set first to confirm rate-limit + parser work
    uv run python -m scripts.run_edgar_backfill --tickers AAPL,MSFT,TSLA

    # Full backfill across the current universe (slow — let it run unattended)
    uv run python -m scripts.run_edgar_backfill --universe themes
    uv run python -m scripts.run_edgar_backfill --universe watchlist

Reads STOCKNEW_EDGAR_USER_AGENT for the SEC-mandated User-Agent header.
Default is "StockNew local-dev contact@stocknew.local" — set your real
contact info before running anything beyond a tiny test set.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from src.market_data.edgar.ingest import run_backfill

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_edgar_backfill")


def _resolve_universe(name: str) -> list[str]:
    from src.config_loader import Config

    config = Config()
    if name == "themes":
        return config.get_theme_tickers()
    if name == "watchlist":
        return config.get_watchlist()
    raise ValueError(f"Unknown universe {name!r}; choose themes|watchlist")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--tickers", type=str, help="Comma-separated ticker list")
    src.add_argument(
        "--universe",
        type=str,
        choices=("themes", "watchlist"),
        help="Universe to backfill (resolved from config/sectors.yaml)",
    )
    args = parser.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = _resolve_universe(args.universe)

    logger.info("Backfilling %d tickers: %s", len(tickers), tickers[:10])
    results = asyncio.run(run_backfill(tickers))

    ok = sum(1 for v in results.values() if isinstance(v, int))
    total_rows = sum(v for v in results.values() if isinstance(v, int))
    failed = {t: v for t, v in results.items() if isinstance(v, str)}

    logger.info("Summary: %d/%d tickers OK, %d rows total", ok, len(tickers), total_rows)
    if failed:
        logger.warning("%d tickers failed:", len(failed))
        for t, err in failed.items():
            logger.warning("  %-6s %s", t, err)
        sys.exit(1)


if __name__ == "__main__":
    main()
