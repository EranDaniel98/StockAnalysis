"""DERA bulk ingest orchestrator.

Single-quarter and multi-quarter entry points. The bulk path runs
synchronous (the zip read + pandas parse is CPU/IO-bound on local disk;
no async win), but the Postgres upserts go through the same async
PostgresFundamentalsRepository as the companyfacts ingestor.

Multi-quarter merge: when ``ingest_range`` walks across multiple zips
for the same ticker, ``valid_to`` chaining and YoY computation need to
see the full per-ticker history — not just one quarter's snapshots in
isolation. We re-run the chaining pass after merging across quarters.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping

from sqlalchemy.ext.asyncio import async_sessionmaker

from src.contracts.entities.fundamentals import FundamentalSnapshot
from src.db.repositories import PostgresFundamentalsRepository
from src.market_data.edgar_bulk.client import BulkArchiveClient
from src.market_data.edgar_bulk.parser import _chain_and_yoy, parse_quarter_zip

logger = logging.getLogger(__name__)


def _invert_ticker_to_cik(ticker_to_cik: Mapping[str, int]) -> dict[int, str]:
    """Existing helpers (e.g. ``get_ticker_to_cik``) return ticker → CIK; the
    bulk parser keys by CIK because that's the join column in sub.txt. Drop
    duplicates defensively — rare but possible when a CIK has multiple
    classes of stock (e.g. GOOG/GOOGL share CIK 1652044)."""
    out: dict[int, str] = {}
    for tkr, cik in ticker_to_cik.items():
        if cik in out:
            # First ticker wins; warn if a second one shows up.
            logger.debug(
                "CIK %d maps to multiple tickers (%s, %s); keeping %s",
                cik, out[cik], tkr, out[cik],
            )
            continue
        out[int(cik)] = tkr.upper()
    return out


def ingest_quarter_sync(
    year: int,
    quarter: int,
    ticker_to_cik: Mapping[str, int],
    client: BulkArchiveClient | None = None,
    download: bool = False,
) -> list[FundamentalSnapshot]:
    """Parse one quarter zip into ``FundamentalSnapshot`` rows.

    Pure CPU/IO work, no DB. ``download=True`` will fetch the zip if not
    cached; default False keeps tests + offline runs honest (cache must
    be pre-populated)."""
    client = client or BulkArchiveClient()
    if download:
        path = client.download_quarter(year, quarter)
    else:
        path = client.cached_path(year, quarter)
        if not path.is_file():
            raise FileNotFoundError(
                f"DERA zip not cached at {path}; pass download=True or pre-fetch."
            )
    cik_to_ticker = _invert_ticker_to_cik(ticker_to_cik)
    snaps = parse_quarter_zip(path, cik_to_ticker)
    logger.info(
        "Parsed %d snapshots from %s (cache hit: %s)",
        len(snaps), path.name, path.is_file(),
    )
    return snaps


async def _upsert_snapshots(
    snapshots: Iterable[FundamentalSnapshot],
    sessionmaker: async_sessionmaker,
) -> int:
    """Write all snapshots through PostgresFundamentalsRepository. One commit
    per snapshot — matches the companyfacts ingestor; rolling into a single
    transaction would be a follow-up optimization."""
    n = 0
    async with sessionmaker() as session:
        repo = PostgresFundamentalsRepository(session)
        for snap in snapshots:
            await repo.upsert(snap)
            n += 1
    return n


async def ingest_quarter(
    year: int,
    quarter: int,
    ticker_to_cik: Mapping[str, int],
    sessionmaker: async_sessionmaker,
    client: BulkArchiveClient | None = None,
    download: bool = False,
) -> int:
    """Parse one quarter and upsert. Returns number of rows written."""
    snaps = ingest_quarter_sync(
        year, quarter, ticker_to_cik, client=client, download=download
    )
    if not snaps:
        return 0
    return await _upsert_snapshots(snaps, sessionmaker)


def _rechain_across_quarters(
    all_snaps: list[FundamentalSnapshot],
) -> list[FundamentalSnapshot]:
    """Single-quarter ``parse_quarter_zip`` chains valid_to within that zip
    only. Merging quarters means the last row of zip N has a valid_to of
    None when it actually should chain to the first row of zip N+1. Group
    by ticker and re-run the chain/YoY pass over the combined set.
    """
    by_ticker: dict[str, list[FundamentalSnapshot]] = defaultdict(list)
    for snap in all_snaps:
        by_ticker[snap.ticker].append(snap)
    out: list[FundamentalSnapshot] = []
    for snaps in by_ticker.values():
        # _chain_and_yoy is destructive (sorts in-place); ok because each
        # ticker's list is private to this function.
        out.extend(_chain_and_yoy(snaps))
    return out


async def ingest_range(
    year_q_pairs: Iterable[tuple[int, int]],
    ticker_to_cik: Mapping[str, int],
    sessionmaker: async_sessionmaker,
    client: BulkArchiveClient | None = None,
    download: bool = False,
) -> dict[tuple[int, int], int]:
    """Multi-quarter ingest. Parses every zip, merges results across
    quarters so YoY/chain math sees the full timeline, then upserts.

    Returns {(year, q): rows_written_for_that_quarter} for reporting.
    """
    client = client or BulkArchiveClient()
    pair_to_snaps: dict[tuple[int, int], list[FundamentalSnapshot]] = {}
    for year, q in year_q_pairs:
        try:
            snaps = ingest_quarter_sync(
                year, q, ticker_to_cik, client=client, download=download
            )
        except FileNotFoundError as e:
            logger.warning("Skipping %dq%d: %s", year, q, e)
            pair_to_snaps[(year, q)] = []
            continue
        pair_to_snaps[(year, q)] = snaps

    flat: list[FundamentalSnapshot] = [s for v in pair_to_snaps.values() for s in v]
    rechained = _rechain_across_quarters(flat)

    written = await _upsert_snapshots(rechained, sessionmaker)
    # Per-pair counts: snapshots stay tagged to their source quarter via
    # valid_from (≈ filing date). Approximate by counting input snaps per
    # pair — the upsert is keyed by (ticker, valid_from, source) so the
    # count is exact even if rechain renamed valid_to.
    pair_counts = {pair: len(snaps) for pair, snaps in pair_to_snaps.items()}
    logger.info(
        "Bulk ingest done: %d total rows upserted across %d quarters",
        written, len(pair_counts),
    )
    return pair_counts
