"""FINRA Reg SHO daily-short-volume ingestion orchestrator.

For each trading day in the requested window, fetch FINRA's CNMS
daily file, parse, and upsert rows into Postgres. Optionally filter
by a ticker allowlist (cheaper writes when we only care about a small
universe like the Russell 1000).

Why orchestrate per-day rather than per-ticker: FINRA only publishes
one file *per day* containing ALL tickers. Fetching one day's file
costs the same whether the universe is 10 or 10000 tickers. We do the
ticker filter post-parse so we can write only the rows we care
about.

Idempotency: upsert on the (ticker, settlement_date) natural key. A
re-run of the same date overwrites with the latest FINRA file (FINRA
occasionally re-publishes a day's file with corrected values).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import date, timedelta
from typing import Iterable, Sequence

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.contracts.errors import ExternalAPIError
from src.db.models import ShortInterest as ShortInterestRow
from src.db.session import dispose_engine, get_sessionmaker
from src.market_data.short_interest_finra.client import (
    DailyShortRow,
    FINRADailyShortClient,
    trading_days,
)

logger = logging.getLogger(__name__)


# Postgres caps prepared statement params at 32767. Each row binds 6
# columns (ticker, settlement_date, short_volume, total_volume,
# short_exempt_volume, created_at) → cap at ~5000 rows/statement; we
# pick 2000 to leave headroom and keep transaction sizes small.
BATCH_SIZE = 2000


def _filter_tickers(
    rows: Iterable[DailyShortRow],
    allowlist: set[str] | None,
) -> list[DailyShortRow]:
    if allowlist is None:
        return list(rows)
    return [r for r in rows if r.ticker in allowlist]


async def _upsert_rows(
    session: AsyncSession,
    rows: Sequence[DailyShortRow],
) -> int:
    """Bulk-upsert daily-short rows on conflict against
    ``uq_short_interest_ticker_date``. Returns rows attempted (not
    rows actually changed — Postgres's ON CONFLICT DO UPDATE doesn't
    distinguish without a RETURNING clause we don't need)."""
    if not rows:
        return 0
    payload = [
        {
            "ticker": r.ticker,
            "settlement_date": r.settlement_date,
            "short_volume": int(r.short_volume),
            "total_volume": int(r.total_volume),
            "short_exempt_volume": int(r.short_exempt_volume),
        }
        for r in rows
    ]
    for i in range(0, len(payload), BATCH_SIZE):
        batch = payload[i:i + BATCH_SIZE]
        stmt = pg_insert(ShortInterestRow).values(batch)
        # ON CONFLICT DO UPDATE — FINRA does re-publish corrected
        # values occasionally; we prefer the latest fetched values.
        stmt = stmt.on_conflict_do_update(
            constraint="uq_short_interest_ticker_date",
            set_={
                "short_volume": stmt.excluded.short_volume,
                "total_volume": stmt.excluded.total_volume,
                "short_exempt_volume": stmt.excluded.short_exempt_volume,
            },
        )
        await session.execute(stmt)
    await session.commit()
    return len(payload)


class FINRAShortIngestor:
    """Top-level orchestrator. Owns the FINRA client + session factory."""

    def __init__(
        self,
        client: FINRADailyShortClient | None = None,
    ) -> None:
        self._client = client or FINRADailyShortClient()
        self._owns_client = client is None
        self._SessionLocal = get_sessionmaker()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def ingest_day(
        self,
        d: date,
        *,
        tickers: set[str] | None = None,
    ) -> int:
        """Fetch + upsert one day's FINRA file. Returns rows written.

        Returns 0 for holidays/weekends (FINRA 404 → empty list from
        the client). Raises ``ExternalAPIError`` on real HTTP errors.
        """
        rows = await self._client.fetch_daily(d)
        rows = _filter_tickers(rows, tickers)
        if not rows:
            return 0
        async with self._SessionLocal() as session:
            return await _upsert_rows(session, rows)

    async def ingest_range(
        self,
        start: date,
        end: date,
        *,
        tickers: set[str] | None = None,
    ) -> dict[date, int | str]:
        """Backfill all trading days in the inclusive window.

        Sequential. Each day is independently committed — if the
        ingest is interrupted halfway through, already-written days
        persist and a re-run picks up where we left off (idempotent
        via upsert).
        """
        results: dict[date, int | str] = {}
        for d in trading_days(start, end):
            try:
                n = await self.ingest_day(d, tickers=tickers)
                results[d] = n
                if n > 0:
                    logger.info("FINRA %s: wrote %d rows", d, n)
            except ExternalAPIError as e:
                logger.warning("FINRA error for %s: %s", d, e)
                results[d] = f"api_error: {e}"
            except Exception as e:  # belt-and-suspenders
                logger.exception("Unexpected error for %s", d)
                results[d] = f"unexpected: {type(e).__name__}: {e}"
        return results


async def run_backfill(
    *,
    start: date,
    end: date,
    tickers: list[str] | None = None,
) -> dict[date, int | str]:
    """Convenience entry point — handles client + engine lifecycle.

    ``tickers`` is normalized to upper-case + dot-stripped (matches
    FINRA's ticker format). Pass None to ingest every symbol FINRA
    publishes (~10k rows/day × N days; a 1-year backfill is ~2.5M
    rows — fine for Postgres but slow to write).
    """
    allow: set[str] | None = None
    if tickers is not None:
        allow = {t.upper().replace(".", "") for t in tickers if t}
    ingestor = FINRAShortIngestor()
    try:
        return await ingestor.ingest_range(start, end, tickers=allow)
    finally:
        await ingestor.aclose()
        await dispose_engine()


def default_range(years: float = 1.0, *, today: date | None = None) -> tuple[date, date]:
    """Default backfill window: today minus ``years`` to T-1.

    Used by the backfill driver when no explicit window is given.
    Avoid pulling today's file — FINRA publishes T-1 data at ~02:00 ET
    the next morning, so "today" returns 404 until then.
    """
    end = (today or date.today()) - timedelta(days=1)
    start = end - timedelta(days=int(round(365.25 * years)))
    return start, end
