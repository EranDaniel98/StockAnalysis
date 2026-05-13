"""Form 4 ingestion orchestrator.

For each ticker, list Form 4 filings on/after a watermark, fetch each
XML, parse, upsert into Postgres. Incremental — relies on
``InsiderTransactionRepository.latest_filing_date`` to skip filings we
already ingested.

Rate-limited inside the underlying ``EDGARClient`` (8 req/sec, half
SEC's cap). Bounded concurrency so we don't fan out faster than the
rate limit can absorb — concurrency=4 is the practical max.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Iterable

from src.contracts.errors import DomainError, ExternalAPIError
from src.db.repositories import InsiderTransactionRepository
from src.db.session import dispose_engine, get_sessionmaker
from src.market_data.edgar.client import EDGARClient, get_ticker_to_cik
from src.market_data.insider.client import fetch_form4_xml, list_form4_filings
from src.market_data.insider.parser import parse_form4

logger = logging.getLogger(__name__)


class InsiderIngestor:
    """Top-level orchestrator. Owns an EDGARClient + the Postgres
    session factory. Exposes ``ingest_ticker`` and ``ingest_universe``.
    """

    def __init__(
        self,
        client: EDGARClient | None = None,
        ticker_to_cik: dict[str, int] | None = None,
    ) -> None:
        self._client = client or EDGARClient()
        self._owns_client = client is None
        self._ticker_to_cik = ticker_to_cik
        self._SessionLocal = get_sessionmaker()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _ensure_cik_map(self) -> None:
        if self._ticker_to_cik is None:
            logger.info("Fetching SEC ticker→CIK index...")
            self._ticker_to_cik = await get_ticker_to_cik(self._client)
            logger.info("Loaded %d ticker mappings", len(self._ticker_to_cik))

    async def _watermark(self, ticker: str) -> date | None:
        """Most recent filing_date we already ingested for this ticker,
        used as the lower bound on the next list call."""
        async with self._SessionLocal() as session:
            repo = InsiderTransactionRepository(session)
            return await repo.latest_filing_date(ticker)

    async def ingest_ticker(
        self,
        ticker: str,
        *,
        since: date | None = None,
    ) -> int:
        """Pull every new Form 4 for ``ticker``, parse, upsert.

        Returns the count of transactions upserted across all new
        filings (NOT the count of filings, since one filing can have
        multiple non-derivative rows × multiple reporting owners).

        ``since`` overrides the watermark — useful for the initial
        backfill where the caller wants to force "3 years back" even
        though the table is currently empty.
        """
        await self._ensure_cik_map()
        cik = self._ticker_to_cik.get(ticker.upper())
        if cik is None:
            raise DomainError(f"No CIK known for ticker {ticker!r}")

        # Watermark: take the explicit `since` argument or the most
        # recent ingested filing_date (+1 day so we don't re-fetch it).
        if since is None:
            wm = await self._watermark(ticker)
            since = (wm + timedelta(days=1)) if wm is not None else None

        filings = await list_form4_filings(self._client, cik, since=since)
        if not filings:
            return 0

        all_txs = []
        for filing in filings:
            try:
                xml = await fetch_form4_xml(
                    self._client, cik, filing.accession_no,
                    primary_document=filing.primary_document,
                )
            except ExternalAPIError as e:
                # One bad filing shouldn't sink the whole ticker.
                logger.warning(
                    "Skipping %s %s: %s", ticker, filing.accession_no, e
                )
                continue
            txs = parse_form4(
                xml,
                accession_no=filing.accession_no,
                filing_date=filing.filing_date,
            )
            # Force ticker upper-case + override XML's ticker tag with
            # ours — Form 4's <issuerTradingSymbol> is occasionally
            # missing for newly-public companies but we already know
            # the ticker from the caller.
            txs = [
                tx.__class__(**{**tx.__dict__, "ticker": ticker.upper()})
                for tx in txs
            ]
            all_txs.extend(txs)

        if not all_txs:
            return 0

        async with self._SessionLocal() as session:
            repo = InsiderTransactionRepository(session)
            n = await repo.upsert_many(all_txs)
        logger.info(
            "%s: upserted %d transactions across %d filings",
            ticker, n, len(filings),
        )
        return n

    async def ingest_universe(
        self,
        tickers: Iterable[str],
        *,
        since: date | None = None,
        max_concurrent: int = 4,
    ) -> dict[str, int | str]:
        """Backfill many tickers. Returns ``{ticker: count_or_error}``.

        Concurrency is bounded — the SEC 10/sec limit is the choke
        point, and each filing requires 2 sequential requests (list
        the archive dir + fetch the XML) so we don't gain much past
        ~4 concurrent tickers.
        """
        await self._ensure_cik_map()
        results: dict[str, int | str] = {}
        sem = asyncio.Semaphore(max_concurrent)

        async def _one(t: str) -> None:
            async with sem:
                try:
                    n = await self.ingest_ticker(t, since=since)
                    results[t] = n
                except ExternalAPIError as e:
                    logger.warning("API error for %s: %s", t, e)
                    results[t] = f"api_error: {e}"
                except DomainError as e:
                    logger.warning("Domain error for %s: %s", t, e)
                    results[t] = f"domain_error: {e}"
                except Exception as e:  # belt-and-suspenders
                    logger.exception("Unexpected error for %s", t)
                    results[t] = f"unexpected: {type(e).__name__}: {e}"

        tasks = [asyncio.create_task(_one(t.upper())) for t in tickers]
        await asyncio.gather(*tasks)
        return results


async def run_backfill(
    tickers: list[str],
    *,
    since: date | None = None,
) -> dict[str, int | str]:
    """Convenience entry point — handles client + engine lifecycle.

    ``since`` defaults to None (use per-ticker watermarks). For the
    first run on a fresh table, pass ``date.today() - timedelta(days=N)``
    to bound the historical fetch — leaving it None pulls every Form 4
    in the SEC's submissions index (typically 2-5 years for an active
    large-cap, ~1000-row hard cap).
    """
    ingestor = InsiderIngestor()
    try:
        return await ingestor.ingest_universe(tickers, since=since)
    finally:
        await ingestor.aclose()
        await dispose_engine()
