"""Integration tests for src.scoring.insider_narrative.

The narrative-enrichment helper queries ``filings_corpus`` directly
(no embedding similarity used — pure recency match on filing_date +
form filter), so the test just needs:

  * A reachable local Postgres with the pgvector extension and the
    0005_filings_corpus migration applied.
  * The ability to insert dummy rows. Embedding column is filled with
    a zero-vector — pgvector accepts it; we never run a similarity
    query against these rows.

Skipped when Postgres isn't reachable, same pattern as
tests/research/test_event_monitor.py.
"""

from __future__ import annotations

import socket
from datetime import date

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.session import get_dsn
from src.scoring.insider_narrative import (
    DEFAULT_CATALYST_FORMS,
    NarrativeContext,
    find_nearest_filing,
)


def _postgres_reachable() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", 5432))
        return True
    except OSError:
        return False
    finally:
        s.close()


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="Postgres not reachable — `docker compose up` first",
)


# pgvector encodes a 384-dim zero vector as "[0,0,...,0]"
ZERO_VEC_384 = "[" + ",".join(["0"] * 384) + "]"
TEST_TICKER = "ZNAR"  # unique-prefix sentinel so we never collide with real data


async def _wipe(session):
    await session.execute(
        text("DELETE FROM filings_corpus WHERE ticker = :t"),
        {"t": TEST_TICKER},
    )
    await session.commit()


async def _insert_chunk(
    session,
    *,
    form: str,
    filing_date: date,
    accession_no: str,
    chunk_text: str,
    chunk_index: int = 0,
) -> None:
    """Insert a single fake filings_corpus row. Zero-vector embedding
    is fine — we never query by similarity in these tests."""
    await session.execute(
        text(
            """
            INSERT INTO filings_corpus (
                ticker, cik, form, accession_no, filing_date, primary_doc,
                chunk_index, chunk_text, chunk_tokens, embedding, embedding_model
            ) VALUES (
                :ticker, :cik, :form, :accn, :fdate, :pdoc,
                :cidx, :ctext, :ctok, CAST(:emb AS vector), :model
            )
            """
        ),
        {
            "ticker": TEST_TICKER,
            "cik": 999999,
            "form": form,
            "accn": accession_no,
            "fdate": filing_date,
            "pdoc": f"{accession_no}.htm",
            "cidx": chunk_index,
            "ctext": chunk_text,
            "ctok": len(chunk_text.split()),
            "emb": ZERO_VEC_384,
            "model": "test-zero",
        },
    )
    await session.commit()


@pytest.fixture
async def session_factory():
    """Fresh async session factory for each test. Cleans the test
    ticker's rows on setup and teardown."""
    engine = create_async_engine(get_dsn(), echo=False)
    SF = async_sessionmaker(engine, expire_on_commit=False)
    async with SF() as s:
        await _wipe(s)
    try:
        yield SF
    finally:
        async with SF() as s:
            await _wipe(s)
        await engine.dispose()


@pytest.mark.asyncio
async def test_finds_8k_within_lookback(session_factory) -> None:
    SF = session_factory
    async with SF() as s:
        await _insert_chunk(
            s,
            form="8-K",
            filing_date=date(2024, 6, 10),
            accession_no="0000000001-24-000001",
            chunk_text=(
                "Item 5.02 Departure of Directors or Certain Officers; "
                "Election of Directors. The CFO has resigned effective immediately."
            ),
        )
    async with SF() as s:
        ctx = await find_nearest_filing(
            s,
            ticker=TEST_TICKER,
            cluster_end_date=date(2024, 6, 15),
            lookback_days=14,
        )
    assert ctx is not None
    assert ctx.form == "8-K"
    assert ctx.filing_date == date(2024, 6, 10)
    assert ctx.days_to_cluster == 5
    assert "Item 5.02" in ctx.excerpt


@pytest.mark.asyncio
async def test_returns_none_when_no_filing_in_window(session_factory) -> None:
    SF = session_factory
    async with SF() as s:
        await _insert_chunk(
            s,
            form="8-K",
            filing_date=date(2024, 1, 1),  # outside default 14-day window
            accession_no="0000000001-24-000099",
            chunk_text="ancient filing",
        )
    async with SF() as s:
        ctx = await find_nearest_filing(
            s,
            ticker=TEST_TICKER,
            cluster_end_date=date(2024, 6, 15),
            lookback_days=14,
            # No fallback either — keep it strict for this test
            fallback_forms=(),
        )
    assert ctx is None


@pytest.mark.asyncio
async def test_future_filings_ignored_lookahead_safe(session_factory) -> None:
    """A filing dated AFTER the cluster_end must not be returned, even
    if it's the only 8-K we have — that would be lookahead bias."""
    SF = session_factory
    async with SF() as s:
        await _insert_chunk(
            s,
            form="8-K",
            filing_date=date(2024, 6, 20),  # AFTER cluster_end
            accession_no="0000000001-24-000010",
            chunk_text="future news",
        )
    async with SF() as s:
        ctx = await find_nearest_filing(
            s,
            ticker=TEST_TICKER,
            cluster_end_date=date(2024, 6, 15),
            lookback_days=30,
            fallback_forms=(),
        )
    assert ctx is None


@pytest.mark.asyncio
async def test_falls_back_to_10q_when_no_recent_8k(session_factory) -> None:
    """No 8-K in the 14-day window but a 10-Q exists in the 90-day
    fallback — fallback should return the 10-Q."""
    SF = session_factory
    async with SF() as s:
        await _insert_chunk(
            s,
            form="10-Q",
            filing_date=date(2024, 5, 1),
            accession_no="0000000001-24-000020",
            chunk_text="quarterly report periodic disclosure",
        )
    async with SF() as s:
        ctx = await find_nearest_filing(
            s,
            ticker=TEST_TICKER,
            cluster_end_date=date(2024, 6, 15),
            lookback_days=14,
            fallback_lookback_days=90,
        )
    assert ctx is not None
    assert ctx.form == "10-Q"


@pytest.mark.asyncio
async def test_prefers_most_recent_8k_over_older_one(session_factory) -> None:
    SF = session_factory
    async with SF() as s:
        await _insert_chunk(
            s,
            form="8-K",
            filing_date=date(2024, 6, 5),
            accession_no="0000000001-24-000005",
            chunk_text="older 8-K",
        )
        await _insert_chunk(
            s,
            form="8-K",
            filing_date=date(2024, 6, 12),
            accession_no="0000000001-24-000012",
            chunk_text="newer 8-K closer to cluster",
        )
    async with SF() as s:
        ctx = await find_nearest_filing(
            s,
            ticker=TEST_TICKER,
            cluster_end_date=date(2024, 6, 15),
            lookback_days=14,
        )
    assert ctx is not None
    assert ctx.filing_date == date(2024, 6, 12)
    assert "newer" in ctx.excerpt


@pytest.mark.asyncio
async def test_chunk_index_0_only(session_factory) -> None:
    """Filing has multiple chunks; we only return chunk_index=0 — the
    filing's lead chunk (cover / item-2.02 headline)."""
    SF = session_factory
    async with SF() as s:
        await _insert_chunk(
            s,
            form="8-K",
            filing_date=date(2024, 6, 10),
            accession_no="0000000001-24-000030",
            chunk_text="LEAD CHUNK with the catalyst",
            chunk_index=0,
        )
        await _insert_chunk(
            s,
            form="8-K",
            filing_date=date(2024, 6, 10),
            accession_no="0000000001-24-000030",
            chunk_text="trailing chunk with boilerplate",
            chunk_index=1,
        )
    async with SF() as s:
        ctx = await find_nearest_filing(
            s,
            ticker=TEST_TICKER,
            cluster_end_date=date(2024, 6, 15),
            lookback_days=14,
        )
    assert ctx is not None
    assert "LEAD" in ctx.excerpt
    assert "trailing" not in ctx.excerpt


def test_default_forms_are_8k_variants() -> None:
    """Sanity: the default form list targets 8-K (event-driven) only.
    10-Q/K live in the fallback list because they're periodic, not
    catalyst-bearing."""
    assert "8-K" in DEFAULT_CATALYST_FORMS
    assert "10-K" not in DEFAULT_CATALYST_FORMS


def test_to_dict_serializes_dates() -> None:
    """NarrativeContext.to_dict produces JSON-safe values — the UI / SSE
    payload needs ISO-format date strings, not date objects."""
    ctx = NarrativeContext(
        ticker="AAPL",
        cluster_end_date=date(2024, 6, 15),
        filing_date=date(2024, 6, 10),
        accession_no="x",
        form="8-K",
        days_to_cluster=5,
        excerpt="hello",
    )
    d = ctx.to_dict()
    assert d["filing_date"] == "2024-06-10"
    assert d["cluster_end_date"] == "2024-06-15"
    assert isinstance(d["days_to_cluster"], int)
