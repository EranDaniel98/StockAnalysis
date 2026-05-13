"""Form 4 insider-transaction backfill driver.

Usage:
    # Test with a small ticker set first
    uv run python -m scripts.backfill_insider --tickers AAPL,MSFT,TSLA

    # Full backfill across the themes universe (slow — ~37 tickers,
    # each fetches 100-500 filings; 8 req/sec rate limit, ~20-40 min)
    uv run python -m scripts.backfill_insider --universe themes

Reads STOCKNEW_EDGAR_USER_AGENT for the SEC-mandated User-Agent
header. Default is "StockNew local-dev contact@stocknew.local" — set
your real contact info before running on more than a handful of
tickers.

Incremental by default: re-running the script only fetches filings
newer than the most-recent ingested filing_date per ticker. To force
a full re-pull, pass ``--days 1095`` (or whatever lookback you want).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, timedelta

from src.market_data.insider.ingest import run_backfill

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("backfill_insider")


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--tickers", type=str, help="Comma-separated ticker list")
    src.add_argument(
        "--universe",
        type=str,
        choices=("themes", "watchlist", "value_cohort", "russell_1000", "all"),
        help=(
            "Universe to backfill (resolved from config/sectors.yaml). "
            "'all' = themes ∪ value_cohort ∪ russell_1000 (deduped)."
        ),
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Lookback window in days. None (default) means use per-ticker "
        "watermark — incremental on re-runs.",
    )
    args = parser.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = _resolve_universe(args.universe)

    since: date | None = None
    if args.days is not None:
        since = date.today() - timedelta(days=args.days)
        logger.info("Backfilling since %s (%d days)", since, args.days)

    logger.info("Backfilling Form 4 for %d tickers: %s", len(tickers), tickers[:10])
    results = asyncio.run(run_backfill(tickers, since=since))

    ok = sum(1 for v in results.values() if isinstance(v, int))
    total_tx = sum(v for v in results.values() if isinstance(v, int))
    failed = {t: v for t, v in results.items() if not isinstance(v, int)}

    logger.info(
        "Backfill complete: %d/%d tickers OK, %d total transactions upserted",
        ok, len(tickers), total_tx,
    )
    if failed:
        logger.warning("Failures (%d):", len(failed))
        for t, err in failed.items():
            logger.warning("  %s: %s", t, err)

    return 0 if ok == len(tickers) else 1


if __name__ == "__main__":
    sys.exit(main())
