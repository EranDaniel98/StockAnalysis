"""Unit tests for the background filing-event monitor.

Mocks the EDGAR client so the test stays self-contained — no network,
no sentence-transformers warm-up (we feed in an empty filing body so
the chunker returns zero chunks).

Skipped when Postgres isn't reachable.
"""

from __future__ import annotations

import socket
from datetime import date
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.config_loader import Config
from src.db.models import FilingNotification, MonitoredTicker
from src.db.session import get_dsn
from src.research_agent.event_monitor import EventMonitor


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


class _FakeEDGARClient:
    """Drop-in for EDGARClient.

    ``submissions_by_cik`` maps CIK → the full ``submissions`` blob the
    real EDGAR endpoint returns (only the ``filings.recent`` arrays
    matter to the monitor). ``filing_text_by_accn`` maps accession_no →
    raw HTML/text; empty string means "no chunks" so we don't pay the
    embedder cost during the test.
    """

    def __init__(
        self,
        submissions_by_cik: dict[int, dict[str, Any]],
        filing_text_by_accn: dict[str, str] | None = None,
    ) -> None:
        self._submissions = submissions_by_cik
        self._texts = filing_text_by_accn or {}

    async def fetch_submissions(self, cik: int) -> dict[str, Any]:
        return self._submissions[cik]

    async def fetch_filing_text(
        self, cik: int, accession_no: str, primary_doc: str
    ) -> str:
        return self._texts.get(accession_no, "")

    async def aclose(self) -> None:
        return None


def _make_submissions(forms_dates_accns: list[tuple[str, str, str, str]]) -> dict:
    """Build the EDGAR ``submissions`` JSON shape from a list of
    ``(form, filing_date, accession_no, primary_doc)`` tuples — newest first.
    """
    return {
        "filings": {
            "recent": {
                "form": [t[0] for t in forms_dates_accns],
                "filingDate": [t[1] for t in forms_dates_accns],
                "accessionNumber": [t[2] for t in forms_dates_accns],
                "primaryDocument": [t[3] for t in forms_dates_accns],
            }
        }
    }


async def _cleanup_ticker(ticker: str) -> None:
    engine = create_async_engine(get_dsn())
    try:
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as s:
            await s.execute(
                delete(FilingNotification).where(FilingNotification.ticker == ticker)
            )
            await s.execute(
                delete(MonitoredTicker).where(MonitoredTicker.ticker == ticker)
            )
            await s.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_first_poll_initializes_watermark_without_firing() -> None:
    """Fresh ticker → record the most recent accession, fire zero
    notifications. Otherwise the feed would get flooded with the user's
    backlog on first run."""
    ticker = "ZZTEST1"
    cik = 9000001
    submissions = _make_submissions(
        [
            ("8-K", "2026-05-01", "9999999999-26-000001", "doc.htm"),
            ("10-Q", "2026-04-01", "9999999999-26-000000", "doc.htm"),
        ]
    )
    fake = _FakeEDGARClient({cik: submissions})

    engine = create_async_engine(get_dsn())
    try:
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
        monitor = EventMonitor(sessionmaker=SessionLocal, config=Config())

        await monitor._poll_one(fake, {ticker: cik}, ticker)  # noqa: SLF001

        async with SessionLocal() as s:
            wm = await s.get(MonitoredTicker, ticker)
            assert wm is not None
            assert wm.last_seen_accession_no == "9999999999-26-000001"

            notifs = (
                await s.execute(
                    FilingNotification.__table__.select().where(
                        FilingNotification.ticker == ticker
                    )
                )
            ).all()
            assert notifs == []

        await _cleanup_ticker(ticker)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_new_accession_fires_notification_and_advances_watermark() -> None:
    """Second poll with a brand-new accession → one notification, watermark
    advances to it. Notification also published on the bus."""
    ticker = "ZZTEST2"
    cik = 9000002

    engine = create_async_engine(get_dsn())
    try:
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

        # Seed the watermark from a "previous" poll.
        async with SessionLocal() as s:
            s.add(
                MonitoredTicker(
                    ticker=ticker,
                    last_seen_accession_no="9999999999-26-000010",
                )
            )
            await s.commit()

        # Now EDGAR shows two newer filings (newest first).
        submissions = _make_submissions(
            [
                ("8-K", "2026-05-03", "9999999999-26-000012", "doc.htm"),
                ("8-K", "2026-05-02", "9999999999-26-000011", "doc.htm"),
                ("10-Q", "2026-04-01", "9999999999-26-000010", "doc.htm"),
            ]
        )
        # Empty filing text so the chunker returns nothing and we skip the
        # embedder — keeps the test fast.
        fake = _FakeEDGARClient({cik: submissions}, {})
        monitor = EventMonitor(sessionmaker=SessionLocal, config=Config())

        # Subscribe to the bus so we can assert the publish ordering.
        async with monitor.bus.subscribe() as sub:
            await monitor._poll_one(fake, {ticker: cik}, ticker)  # noqa: SLF001

            # Bus should have the two events oldest-first.
            published = []
            while not sub.queue.empty():
                published.append(sub.queue.get_nowait())
            assert [p.accession_no for p in published] == [
                "9999999999-26-000011",
                "9999999999-26-000012",
            ]
            assert all(p.ticker == ticker for p in published)

        async with SessionLocal() as s:
            wm = await s.get(MonitoredTicker, ticker)
            assert wm is not None
            assert wm.last_seen_accession_no == "9999999999-26-000012"

            notifs = (
                await s.execute(
                    FilingNotification.__table__.select()
                    .where(FilingNotification.ticker == ticker)
                    .order_by(FilingNotification.id)
                )
            ).all()
            accessions = [n.accession_no for n in notifs]
            assert accessions == [
                "9999999999-26-000011",
                "9999999999-26-000012",
            ]

        await _cleanup_ticker(ticker)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_repoll_with_no_new_filings_is_a_noop() -> None:
    """When EDGAR has nothing newer than the watermark, the monitor
    just bumps last_polled_at and writes zero notifications."""
    ticker = "ZZTEST3"
    cik = 9000003

    engine = create_async_engine(get_dsn())
    try:
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

        async with SessionLocal() as s:
            s.add(
                MonitoredTicker(
                    ticker=ticker,
                    last_seen_accession_no="9999999999-26-000020",
                )
            )
            await s.commit()

        submissions = _make_submissions(
            [
                ("10-K", "2026-03-01", "9999999999-26-000020", "doc.htm"),
                ("10-Q", "2026-02-01", "9999999999-26-000019", "doc.htm"),
            ]
        )
        fake = _FakeEDGARClient({cik: submissions})
        monitor = EventMonitor(sessionmaker=SessionLocal, config=Config())

        await monitor._poll_one(fake, {ticker: cik}, ticker)  # noqa: SLF001

        async with SessionLocal() as s:
            wm = await s.get(MonitoredTicker, ticker)
            assert wm is not None
            assert wm.last_seen_accession_no == "9999999999-26-000020"
            assert wm.last_polled_at is not None

            notifs = (
                await s.execute(
                    FilingNotification.__table__.select().where(
                        FilingNotification.ticker == ticker
                    )
                )
            ).all()
            assert notifs == []

        await _cleanup_ticker(ticker)
    finally:
        await engine.dispose()
