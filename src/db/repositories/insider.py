"""Postgres-backed InsiderTransactionRepository.

Two responsibilities:
  * ``upsert_many`` — write parsed Form 4 rows idempotently. Re-running
    the ingestor on already-seen filings is a no-op.
  * ``open_market_buys(ticker, start, end)`` — primary read path used by
    the insider_flow analyzer's cluster detector.

We don't pre-load this into the contracts package — the analyzer
imports the repository directly, mirroring how Phase 4's feature
store accesses Postgres for cross-sectional reads.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from datetime import date, timedelta

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import InsiderTransaction as InsiderTxRow
from src.market_data.insider.parser import InsiderTransaction

logger = logging.getLogger(__name__)


# Codes that represent open-market purchases / sales (excludes grants,
# tax withholding, gifts, exercises, etc.). The cluster-buy signal we
# care about is exclusively code P.
OPEN_MARKET_BUY_CODE = "P"
OPEN_MARKET_SELL_CODE = "S"


def _to_row_dict(tx: InsiderTransaction) -> dict:
    """Map a parser ``InsiderTransaction`` dataclass to the row dict
    expected by ``insert(InsiderTxRow).values(...)``."""
    d = asdict(tx)
    # Decimals serialize fine through asyncpg's NUMERIC binding.
    return d


class InsiderTransactionRepository:
    """Implements upsert + windowed reads against the insider_transactions
    table. Methods are async so they compose with the rest of the
    SQLAlchemy 2.0 / asyncpg stack used by ingestion + analyzers."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # Postgres limits prepared-statement parameters to 32767. Each row
    # binds 16 columns → max ~2047 rows per single INSERT. Pick a
    # comfortable 1000 to leave headroom (different SA versions add
    # extra binds for timestamps).
    BATCH_SIZE = 1000

    async def upsert_many(self, txs: Iterable[InsiderTransaction]) -> int:
        """Insert rows; on conflict against the (accession, owner_cik,
        tx_date, tx_code, shares) natural key, do nothing.

        Batches at 1000 rows/statement so we don't hit Postgres's
        32767-parameter cap on bulky tickers — Tesla and Microsoft
        accumulate >2000 Form 4 transactions over 3 years.

        Returns the count of rows we attempted to upsert (NOT the
        count actually inserted — Postgres doesn't report that for
        ON CONFLICT DO NOTHING in a single round-trip without a
        RETURNING clause we'd have to parse).
        """
        payload = [_to_row_dict(t) for t in txs]
        if not payload:
            return 0
        for i in range(0, len(payload), self.BATCH_SIZE):
            batch = payload[i:i + self.BATCH_SIZE]
            stmt = pg_insert(InsiderTxRow).values(batch).on_conflict_do_nothing(
                constraint="uq_insider_tx_natural_key",
            )
            await self._session.execute(stmt)
        await self._session.commit()
        return len(payload)

    async def open_market_buys(
        self,
        ticker: str,
        start: date,
        end: date,
    ) -> Sequence[InsiderTxRow]:
        """Return open-market buys (code 'P', acquired) for ``ticker``
        in the inclusive date window. Ordered by transaction_date
        ascending for deterministic cluster detection.

        Returns ORM rows so the analyzer can read ``owner_cik``,
        ``owner_role``, ``officer_title``, ``shares``, ``value_usd``
        without a follow-up roundtrip.
        """
        stmt = (
            select(InsiderTxRow)
            .where(InsiderTxRow.ticker == ticker.upper())
            .where(InsiderTxRow.transaction_code == OPEN_MARKET_BUY_CODE)
            .where(InsiderTxRow.acquired_disposed == "A")
            .where(InsiderTxRow.transaction_date >= start)
            .where(InsiderTxRow.transaction_date <= end)
            .order_by(InsiderTxRow.transaction_date.asc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def recent_buys_many(
        self,
        tickers: Sequence[str],
        *,
        days_back: int,
        as_of: date,
    ) -> dict[str, list[InsiderTxRow]]:
        """Bulk-load open-market buys (code 'P', acquired) for a batch
        of tickers across a rolling window ending at ``as_of``. Used by
        the scan path so we can feed the ``insider_flow`` analyzer
        without N round-trips.

        Returns a dict keyed by ticker (uppercased); tickers with no
        qualifying rows are omitted (caller treats absence as "no
        insider signal" — same convention as the analyzer's None).
        """
        if not tickers:
            return {}
        upper = [t.upper() for t in tickers]
        start = as_of - timedelta(days=days_back)
        stmt = (
            select(InsiderTxRow)
            .where(InsiderTxRow.ticker.in_(upper))
            .where(InsiderTxRow.transaction_code == OPEN_MARKET_BUY_CODE)
            .where(InsiderTxRow.acquired_disposed == "A")
            .where(InsiderTxRow.transaction_date >= start)
            .where(InsiderTxRow.transaction_date <= as_of)
            .order_by(InsiderTxRow.transaction_date.asc())
        )
        result = await self._session.execute(stmt)
        out: dict[str, list[InsiderTxRow]] = {}
        for row in result.scalars().all():
            out.setdefault(row.ticker, []).append(row)
        return out

    async def latest_filing_date(self, ticker: str) -> date | None:
        """For the incremental ingester: skip Form 4 filings we've
        already processed for this ticker. Returns the most recent
        ``filing_date`` seen, or None if we have no rows yet."""
        stmt = (
            select(InsiderTxRow.filing_date)
            .where(InsiderTxRow.ticker == ticker.upper())
            .order_by(InsiderTxRow.filing_date.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar()
