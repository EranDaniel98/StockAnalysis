"""EDGAR ingestion orchestrator.

Fetches one company's full XBRL facts, parses them into FundamentalSnapshot
rows, upserts into Postgres via FundamentalsRepository. Designed to run as
either a one-shot backfill (across the current universe, slow but
unattended) or a daily incremental cron (cheap, just refreshes companies
whose last filed date predates today minus 24h).

Rate-limited inside the EDGARClient — 8 req/sec leaves headroom under
SEC's 10/sec cap. Errors per ticker are isolated (one bad CIK doesn't
stop the batch).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable

from src.contracts.errors import DomainError, ExternalAPIError
from src.db.repositories import PostgresFundamentalsRepository
from src.db.session import dispose_engine, get_sessionmaker
from src.market_data.edgar.client import EDGARClient, get_ticker_to_cik
from src.market_data.edgar.parser import parse_company_facts

logger = logging.getLogger(__name__)


class EDGARIngestor:
    """Top-level orchestrator. Holds an EDGARClient + a Postgres session
    factory; provides ingest_ticker and ingest_universe."""

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

    async def ingest_ticker(self, ticker: str) -> int:
        """Pull EDGAR facts for one ticker, parse, upsert into Postgres.
        Returns the count of FundamentalSnapshot rows written.

        Raises ExternalAPIError if EDGAR returns non-200; DomainError if
        the ticker has no known CIK."""
        await self._ensure_cik_map()
        cik = self._ticker_to_cik.get(ticker.upper())
        if cik is None:
            raise DomainError(f"No CIK known for ticker {ticker!r}")

        facts = await self._client.fetch_company_facts(cik)
        snapshots = parse_company_facts(ticker.upper(), facts)
        if not snapshots:
            logger.warning("No usable snapshots parsed for %s", ticker)
            return 0

        async with self._SessionLocal() as session:
            repo = PostgresFundamentalsRepository(session)
            for snap in snapshots:
                await repo.upsert(snap)
        logger.info("Upserted %d snapshots for %s", len(snapshots), ticker)
        return len(snapshots)

    async def ingest_universe(
        self,
        tickers: Iterable[str],
        max_concurrent: int = 4,
    ) -> dict[str, int | str]:
        """Backfill many tickers. Returns {ticker: row_count_or_error}.
        Concurrency is bounded — the SEC limit is the choke point.

        max_concurrent=4 is the practical max with 8 req/sec rate-limit
        and EDGAR's ~500ms typical companyfacts response time."""
        await self._ensure_cik_map()
        results: dict[str, int | str] = {}
        sem = asyncio.Semaphore(max_concurrent)

        async def _one(t: str) -> None:
            async with sem:
                try:
                    n = await self.ingest_ticker(t)
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


async def run_backfill(tickers: list[str]) -> dict[str, int | str]:
    """Convenience entry point — handles client + engine lifecycle."""
    ingestor = EDGARIngestor()
    try:
        return await ingestor.ingest_universe(tickers)
    finally:
        await ingestor.aclose()
        await dispose_engine()
