"""FINRA Reg SHO daily short-volume backfill driver.

Usage:
    # Smoke test against a small ticker set, last 90 days
    uv run python -m scripts.backfill_short_interest \\
        --tickers AAPL,MSFT,TSLA --days 90

    # Full 1-year backfill against the Russell 1000 universe
    uv run python -m scripts.backfill_short_interest \\
        --universe russell_1000 --years 1

    # 5-year backfill, all FINRA-published tickers (no allowlist)
    uv run python -m scripts.backfill_short_interest --years 5

FINRA publishes one daily file containing every NMS-listed ticker, so
the ticker filter only narrows what we *write*, not what we *fetch*.
Run-time scales linearly with the date window (one HTTP call per
weekday at ~1 req/sec polite default → ~250 calls/year ~ 5 min) +
write time (Russell 1000 × 250 days = 250k rows, ~30s upsert).

Re-running is safe: upsert on (ticker, settlement_date) overwrites
with the latest values.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, timedelta

from src.market_data.short_interest_finra.ingest import run_backfill

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("backfill_short_interest")


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
        f"Unknown universe {name!r}; "
        "choose themes|watchlist|value_cohort|russell_1000|all"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group()
    src.add_argument(
        "--tickers",
        type=str,
        help="Comma-separated ticker list (overrides --universe)",
    )
    src.add_argument(
        "--universe",
        type=str,
        choices=("themes", "watchlist", "value_cohort", "russell_1000", "all"),
        help=(
            "Universe to filter to (resolved from config). "
            "Omit both --tickers and --universe to ingest every "
            "FINRA-published symbol."
        ),
    )

    win = parser.add_mutually_exclusive_group()
    win.add_argument(
        "--years",
        type=float,
        default=None,
        help="Backfill window in years (default: 1.0 if neither --years "
        "nor --days nor --start is given)",
    )
    win.add_argument(
        "--days",
        type=int,
        default=None,
        help="Backfill window in days",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Explicit start date YYYY-MM-DD (overrides --years/--days). "
        "Pairs with --end; both optional.",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="Explicit end date YYYY-MM-DD (default: yesterday)",
    )
    args = parser.parse_args()

    tickers: list[str] | None = None
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    elif args.universe:
        tickers = _resolve_universe(args.universe)

    end_date = (
        date.fromisoformat(args.end) if args.end
        else date.today() - timedelta(days=1)
    )
    if args.start:
        start_date = date.fromisoformat(args.start)
    elif args.days is not None:
        start_date = end_date - timedelta(days=int(args.days))
    elif args.years is not None:
        start_date = end_date - timedelta(days=int(round(365.25 * args.years)))
    else:
        # Default: 1 year back.
        start_date = end_date - timedelta(days=365)

    if start_date > end_date:
        logger.error("start_date %s is after end_date %s", start_date, end_date)
        return 2

    label = (
        f"{len(tickers)} tickers (allowlist)" if tickers
        else "all FINRA-published symbols"
    )
    logger.info(
        "FINRA backfill: %s → %s (%d days), filter=%s",
        start_date, end_date,
        (end_date - start_date).days + 1,
        label,
    )

    results = asyncio.run(
        run_backfill(start=start_date, end=end_date, tickers=tickers)
    )

    days_ok = sum(1 for v in results.values() if isinstance(v, int))
    total_rows = sum(v for v in results.values() if isinstance(v, int))
    failures = {d: v for d, v in results.items() if not isinstance(v, int)}

    logger.info(
        "Backfill complete: %d/%d days OK, %d total rows written",
        days_ok, len(results), total_rows,
    )
    if failures:
        logger.warning("Failures (%d):", len(failures))
        for d, err in sorted(failures.items()):
            logger.warning("  %s: %s", d, err)

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
