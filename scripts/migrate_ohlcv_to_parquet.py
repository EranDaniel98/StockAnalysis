"""One-shot migration: data/cache.db (SQLite cache, JSON DataFrames) → Parquet.

Walks every `price_*` key in the SQLite cache, decodes the JSON-serialized
DataFrame, normalizes columns/index, and writes to the per-year-per-ticker
Parquet layout via ParquetPriceRepository.write_history.

The SQLite cache stays in place during Phase 0 — fetchers can still hit it as
a read-through fallback until Stream B carve removes the legacy code path.

Usage:
    uv run python -m scripts.migrate_ohlcv_to_parquet
    uv run python -m scripts.migrate_ohlcv_to_parquet --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

import pandas as pd

from src.storage.parquet_ohlcv import ParquetPriceRepository

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate_ohlcv_to_parquet")


def _decode_cached_df(raw_json: str) -> pd.DataFrame | None:
    """The legacy cache calls `df.to_dict()` then json.dumps. Decode the
    inverse: dict-of-dicts → DataFrame.

    Index keys are date strings — some entries (notably ^VIX and futures
    tickers) had tz-aware indexes serialized with explicit offsets; pandas
    refuses to convert mixed-offset arrays without `utc=True`. Parse as
    UTC then strip the tz to land on the tz-naive convention our Parquet
    layer expects.
    """
    try:
        d = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or not d:
        return None
    df = pd.DataFrame(d)
    try:
        df.index = pd.to_datetime(df.index, utc=True, errors="raise").tz_localize(None)
    except (ValueError, TypeError):
        return None
    return df


def _run(source: Path, dry_run: bool) -> None:
    if not source.exists():
        logger.error("Source not found: %s", source)
        sys.exit(1)

    conn = sqlite3.connect(str(source))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT key, value FROM cache WHERE key LIKE 'price_%' ORDER BY key"
    ).fetchall()
    logger.info("Price entries in source: %d", len(rows))

    if dry_run:
        conn.close()
        return

    repo = ParquetPriceRepository()
    migrated_tickers = 0
    migrated_bars = 0
    skipped = 0

    for row in rows:
        # Key shape: price_{TICKER}_{PERIOD}_{INTERVAL}
        # Migration only handles 1d interval. Skip everything else.
        parts = row["key"].split("_")
        if len(parts) < 4 or parts[-1] != "1d":
            skipped += 1
            continue
        # Ticker is parts[1] — period+interval are the trailing pieces but
        # in some keys the period itself might have an underscore. Safer to
        # join the middle:
        ticker = parts[1]

        df = _decode_cached_df(row["value"])
        if df is None or df.empty:
            skipped += 1
            continue

        try:
            written = repo.write_history(ticker, df)
            migrated_tickers += 1
            migrated_bars += written
        except Exception as e:
            logger.warning("Failed to write %s: %s", ticker, e)
            skipped += 1

    conn.close()
    logger.info(
        "Migration complete: %d tickers, %d bars (skipped %d)",
        migrated_tickers,
        migrated_bars,
        skipped,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "cache.db",
        help="Path to source SQLite cache (default: data/cache.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count price entries only; do not write Parquet",
    )
    args = parser.parse_args()
    _run(args.source, args.dry_run)


if __name__ == "__main__":
    main()
