"""k-NN search over filings_corpus.

Embeds the query locally, asks pgvector for the closest chunks via
cosine distance (``<=>`` operator), returns them with metadata. The
HNSW index from migration 0005 keeps this sub-100ms for tens of
thousands of chunks.

Filter knobs: ticker, form, date_after — all server-side so the index
isn't bypassed. ``SET LOCAL hnsw.ef_search`` per-query for accuracy/
latency tradeoff (project convention: not globally).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.research_agent.rag.embedder import embed_one

logger = logging.getLogger(__name__)


@dataclass
class FilingHit:
    ticker: str
    form: str
    filing_date: date
    accession_no: str
    chunk_index: int
    chunk_text: str
    score: float
    """1 - cosine_distance, so higher is more relevant."""


async def search_filings(
    session: AsyncSession,
    query: str,
    *,
    top_k: int = 5,
    ticker: Optional[str] = None,
    form: Optional[str] = None,
    after: Optional[date] = None,
    ef_search: int = 64,
) -> list[FilingHit]:
    """Semantic k-NN search. ``query`` is embedded then matched against
    the HNSW-indexed embedding column."""
    if not query.strip():
        return []

    # Embedding happens off the event loop — it's CPU-bound.
    q_vec = await asyncio.to_thread(embed_one, query)
    q_str = "[" + ",".join(f"{x:.6f}" for x in q_vec.tolist()) + "]"

    where_clauses = []
    params: dict = {"q": q_str, "k": top_k}
    if ticker:
        where_clauses.append("ticker = :ticker")
        params["ticker"] = ticker.upper()
    if form:
        where_clauses.append("form = :form")
        params["form"] = form
    if after:
        where_clauses.append("filing_date >= :after")
        params["after"] = after

    where_sql = ""
    if where_clauses:
        where_sql = " WHERE " + " AND ".join(where_clauses)

    # Per-query ef_search — project convention is to scope this rather
    # than mutate the session globally.
    await session.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}"))

    sql = text(
        f"""
        SELECT
            ticker, form, filing_date, accession_no, chunk_index, chunk_text,
            1 - (embedding <=> CAST(:q AS vector)) AS score
        FROM filings_corpus
        {where_sql}
        ORDER BY embedding <=> CAST(:q AS vector)
        LIMIT :k
        """
    )
    result = await session.execute(sql, params)
    hits = [
        FilingHit(
            ticker=row.ticker,
            form=row.form,
            filing_date=row.filing_date,
            accession_no=row.accession_no,
            chunk_index=row.chunk_index,
            chunk_text=row.chunk_text,
            score=float(row.score),
        )
        for row in result
    ]
    return hits
