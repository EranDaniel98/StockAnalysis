"""EDGAR filings → filings_corpus ingestion.

For each ticker we:
  1. Resolve ticker → CIK via the existing EDGAR client.
  2. Pull the submissions index, filter to the form types we care about
     (10-K, 10-Q, 8-K by default), keep the most recent N.
  3. Fetch each filing's primary document, strip HTML, chunk, embed,
     upsert. Re-ingesting the same accession_no replaces its chunks.

Network-bound by EDGAR's 8 req/sec limit. CPU-bound by sentence-
transformers (~5-15ms per chunk). For 36 tickers × 6 filings ×
~50 chunks ≈ 10k chunks → ~2-3 minutes wall clock on a single CPU.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.contracts.errors import DomainError, ExternalAPIError
from src.db.models import FilingCorpusChunk
from src.market_data.edgar.client import EDGARClient, get_ticker_to_cik
from src.research_agent.rag.chunker import chunk_text, strip_html
from src.research_agent.rag.embedder import EMBEDDING_MODEL, embed_texts

logger = logging.getLogger(__name__)


DEFAULT_FORMS = ("10-K", "10-Q", "8-K")
DEFAULT_PER_FORM_LIMIT = 4  # latest 4 of each form per ticker


@dataclass
class FilingMeta:
    accession_no: str
    form: str
    filing_date: date
    primary_document: str


@dataclass
class IngestStats:
    ticker: str
    n_filings: int
    n_chunks: int
    errors: list[str]


def select_recent_filings(
    submissions: dict, *, forms: tuple[str, ...], per_form_limit: int
) -> list[FilingMeta]:
    """Walk the EDGAR submissions blob, keep the latest N of each form."""
    recent = submissions.get("filings", {}).get("recent", {}) or {}
    forms_arr = recent.get("form") or []
    accs = recent.get("accessionNumber") or []
    dates = recent.get("filingDate") or []
    primary = recent.get("primaryDocument") or []

    out: list[FilingMeta] = []
    per_form_count: dict[str, int] = {f: 0 for f in forms}
    for i in range(len(forms_arr)):
        form = forms_arr[i]
        if form not in forms:
            continue
        if per_form_count[form] >= per_form_limit:
            continue
        try:
            filed = datetime.strptime(dates[i], "%Y-%m-%d").date()
        except (ValueError, IndexError):
            continue
        out.append(
            FilingMeta(
                accession_no=accs[i],
                form=form,
                filing_date=filed,
                primary_document=primary[i] if i < len(primary) else "",
            )
        )
        per_form_count[form] += 1
        if all(c >= per_form_limit for c in per_form_count.values()):
            break
    return out


async def ingest_one_filing(
    *,
    session: AsyncSession,
    client: EDGARClient,
    ticker: str,
    cik: int,
    meta: FilingMeta,
) -> int:
    """Fetch + chunk + embed + upsert one filing. Returns chunk count."""
    if not meta.primary_document:
        return 0

    # Skip if we've already ingested this accession_no — cheap probe.
    existing = await session.execute(
        select(FilingCorpusChunk.id).where(
            FilingCorpusChunk.accession_no == meta.accession_no
        )
    )
    if existing.first() is not None:
        logger.debug("%s %s already ingested", ticker, meta.accession_no)
        return 0

    raw_html = await client.fetch_filing_text(
        cik, meta.accession_no, meta.primary_document
    )
    text = strip_html(raw_html)
    chunks = chunk_text(text)
    if not chunks:
        return 0

    # Embedding is CPU-bound; run off the event loop.
    embeddings = await asyncio.to_thread(
        embed_texts, [c.text for c in chunks]
    )

    now = datetime.now(timezone.utc)
    rows = [
        FilingCorpusChunk(
            ticker=ticker.upper(),
            cik=int(cik),
            form=meta.form,
            accession_no=meta.accession_no,
            filing_date=meta.filing_date,
            primary_doc=meta.primary_document,
            chunk_index=i,
            chunk_text=chunk.text,
            chunk_tokens=chunk.approx_tokens,
            embedding=embeddings[i].tolist(),
            embedding_model=EMBEDDING_MODEL,
            ingested_at=now,
        )
        for i, chunk in enumerate(chunks)
    ]
    session.add_all(rows)
    await session.commit()
    logger.info(
        "ingested %s %s (%s): %d chunks",
        ticker, meta.form, meta.filing_date, len(rows),
    )
    return len(rows)


async def ingest_ticker(
    ticker: str,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    client: EDGARClient,
    ticker_to_cik: dict[str, int],
    forms: tuple[str, ...] = DEFAULT_FORMS,
    per_form_limit: int = DEFAULT_PER_FORM_LIMIT,
) -> IngestStats:
    """One-ticker ingestion. Catches per-filing errors so a single
    bad document doesn't abort the rest of the company's filings."""
    cik = ticker_to_cik.get(ticker.upper())
    if cik is None:
        return IngestStats(
            ticker=ticker.upper(),
            n_filings=0,
            n_chunks=0,
            errors=[f"no CIK known for {ticker}"],
        )

    try:
        submissions = await client.fetch_submissions(cik)
    except ExternalAPIError as e:
        return IngestStats(
            ticker=ticker.upper(), n_filings=0, n_chunks=0, errors=[str(e)]
        )

    filings = select_recent_filings(
        submissions, forms=forms, per_form_limit=per_form_limit
    )
    if not filings:
        return IngestStats(ticker=ticker.upper(), n_filings=0, n_chunks=0, errors=[])

    total_chunks = 0
    errors: list[str] = []
    async with sessionmaker() as session:
        for meta in filings:
            try:
                total_chunks += await _ingest_one_filing(
                    session=session,
                    client=client,
                    ticker=ticker.upper(),
                    cik=cik,
                    meta=meta,
                )
            except ExternalAPIError as e:
                errors.append(f"{meta.accession_no}: {e}")
            except Exception as e:  # noqa: BLE001 — one bad filing shouldn't poison batch
                logger.exception("filing ingest failed for %s/%s", ticker, meta.accession_no)
                errors.append(f"{meta.accession_no}: {type(e).__name__}: {e}")

    return IngestStats(
        ticker=ticker.upper(),
        n_filings=len(filings),
        n_chunks=total_chunks,
        errors=errors,
    )


async def ingest_universe(
    tickers: Iterable[str],
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    forms: tuple[str, ...] = DEFAULT_FORMS,
    per_form_limit: int = DEFAULT_PER_FORM_LIMIT,
    max_concurrent: int = 2,
) -> list[IngestStats]:
    """Backfill many tickers. Sequential per-ticker so embeddings don't
    fight for CPU; concurrency knob is for the network half (EDGAR
    fetches) and stays low because of the 8 req/sec SEC cap."""
    client = EDGARClient()
    try:
        ticker_to_cik = await get_ticker_to_cik(client)
        sem = asyncio.Semaphore(max_concurrent)
        results: list[IngestStats] = []

        async def _one(t: str) -> None:
            async with sem:
                stat = await ingest_ticker(
                    t,
                    sessionmaker=sessionmaker,
                    client=client,
                    ticker_to_cik=ticker_to_cik,
                    forms=forms,
                    per_form_limit=per_form_limit,
                )
                results.append(stat)

        await asyncio.gather(*(_one(t.upper()) for t in tickers))
        return results
    finally:
        await client.aclose()
