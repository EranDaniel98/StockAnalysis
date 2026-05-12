"""Background filing-event monitor.

Long-running asyncio task wired into the FastAPI lifespan. Every poll
interval it:

  1. Resolves the universe of tickers to watch (Alpaca holdings if
     credentials are present; else the configured watchlist).
  2. Pulls the EDGAR submissions index for each ticker (rate-limited
     by the shared EDGARClient).
  3. Compares the latest accession against ``monitored_tickers``. On
     first observation we *only* record the watermark — no notification
     fires for historical filings the user has never seen.
  4. For each newer filing, ingests the chunks into ``filings_corpus``
     (so the RAG agent has the new data immediately) and inserts a
     ``filing_notifications`` row.
  5. Fans the notification out via ``FilingNotificationBus`` so the
     /research/feed SSE channel surfaces it live.

Failure tolerance: per-ticker errors are swallowed and logged. One
flaky CIK doesn't stall the whole sweep. The monitor itself never
exits — it sleeps and retries.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.contracts.errors import ExternalAPIError
from src.db.models import FilingNotification, MonitoredTicker
from src.market_data.edgar.client import EDGARClient, get_ticker_to_cik
from src.research_agent.rag.ingest import (
    ingest_one_filing,
    select_recent_filings,
)

logger = logging.getLogger(__name__)


DEFAULT_FORMS = ("8-K", "10-K", "10-Q")
"""8-K first — it's the form that carries actionable news."""

DEFAULT_POLL_SECONDS = float(os.environ.get("STOCKNEW_EVENT_POLL_SECONDS", "1800"))
"""30 minutes by default. EDGAR refresh is on the order of minutes;
shorter is fine if you want lower latency at the cost of more EDGAR
hits."""

DEFAULT_PER_FORM_LIMIT = 4


@dataclass
class FilingNotificationEvent:
    """Slim payload pushed to the SSE channel + persisted to DB."""

    id: int
    ticker: str
    form: str
    accession_no: str
    filing_date: str
    primary_document: Optional[str]
    detected_at: str

    @classmethod
    def from_row(cls, row: FilingNotification) -> "FilingNotificationEvent":
        return cls(
            id=row.id,
            ticker=row.ticker,
            form=row.form,
            accession_no=row.accession_no,
            filing_date=row.filing_date.isoformat(),
            primary_document=row.primary_document,
            detected_at=row.detected_at.isoformat(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "form": self.form,
            "accession_no": self.accession_no,
            "filing_date": self.filing_date,
            "primary_document": self.primary_document,
            "detected_at": self.detected_at,
        }


# ─── notification fanout bus ────────────────────────────────────────────────


@dataclass(eq=False)
class _Subscriber:
    """Per-subscriber queue. Identity-hashed so we can hold instances in
    a set without freezing the contents."""

    queue: asyncio.Queue[FilingNotificationEvent]


class FilingNotificationBus:
    """Multi-subscriber fanout — same pattern as TradeUpdatesBus, but the
    source isn't a websocket, it's the EventMonitor's poll loop. The
    monitor calls ``publish`` directly so we don't need refcounted
    upstream subscriptions."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._subscribers: set[_Subscriber] = set()
        self._closed = False

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[_Subscriber]:
        if self._closed:
            raise RuntimeError("FilingNotificationBus is closed")
        sub = _Subscriber(queue=asyncio.Queue(maxsize=64))
        async with self._lock:
            self._subscribers.add(sub)
        try:
            yield sub
        finally:
            async with self._lock:
                self._subscribers.discard(sub)

    async def publish(self, event: FilingNotificationEvent) -> None:
        # Snapshot under lock then release — delivery shouldn't block new
        # subscriptions.
        async with self._lock:
            subs = tuple(self._subscribers)
        for sub in subs:
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop the oldest so the newest event still gets through —
                # SSE clients catch up via the DB on reconnect.
                try:
                    sub.queue.get_nowait()
                    sub.queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            self._subscribers.clear()


# ─── monitor ────────────────────────────────────────────────────────────────


class EventMonitor:
    """Wraps the background poll loop + a shared notification bus.

    Lifecycle:
      ``start()`` spawns the loop task. ``stop()`` cancels + awaits it.
      Re-callable: ``stop()`` after ``stop()`` is a no-op. The bus is
      torn down on ``stop()`` so SSE subscribers get a clean close.
    """

    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        config,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        forms: tuple[str, ...] = DEFAULT_FORMS,
        per_form_limit: int = DEFAULT_PER_FORM_LIMIT,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._config = config
        self._poll_seconds = poll_seconds
        self._forms = forms
        self._per_form_limit = per_form_limit
        self._task: Optional[asyncio.Task[None]] = None
        self._stop_event = asyncio.Event()
        self.bus = FilingNotificationBus()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="filing-event-monitor")
        logger.info(
            "filing event monitor started (poll=%.0fs, forms=%s)",
            self._poll_seconds, self._forms,
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        await self.bus.close()

    # ─── loop body ──────────────────────────────────────────────────────

    async def _loop(self) -> None:
        # First poll runs immediately; subsequent polls wait poll_seconds.
        # Sleep is interruptible so ``stop()`` resolves promptly.
        while not self._stop_event.is_set():
            try:
                await self._poll_once()
            except Exception:  # noqa: BLE001 — keep the loop alive
                logger.exception("event monitor poll cycle crashed")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._poll_seconds
                )
                return
            except asyncio.TimeoutError:
                continue

    async def _poll_once(self) -> None:
        tickers = await self._resolve_universe()
        if not tickers:
            logger.debug("event monitor: no tickers to watch this cycle")
            return

        client = EDGARClient()
        try:
            ticker_to_cik = await get_ticker_to_cik(client)
            for ticker in tickers:
                try:
                    await self._poll_one(client, ticker_to_cik, ticker)
                except Exception:  # noqa: BLE001 — per-ticker isolation
                    logger.exception("event monitor: poll failed for %s", ticker)
        finally:
            await client.aclose()

    async def _poll_one(
        self,
        client: EDGARClient,
        ticker_to_cik: dict[str, int],
        ticker: str,
    ) -> None:
        ticker = ticker.upper()
        cik = ticker_to_cik.get(ticker)
        if cik is None:
            logger.debug("event monitor: no CIK for %s", ticker)
            return

        try:
            submissions = await client.fetch_submissions(cik)
        except ExternalAPIError as e:
            logger.warning("EDGAR submissions error for %s: %s", ticker, e)
            return

        filings = select_recent_filings(
            submissions, forms=self._forms, per_form_limit=self._per_form_limit
        )
        if not filings:
            return

        # Newest first per EDGAR — process accordingly.
        async with self._sessionmaker() as session:
            watermark = await session.get(MonitoredTicker, ticker)
            first_time = watermark is None
            last_seen = watermark.last_seen_accession_no if watermark else None
            newest_accession = filings[0].accession_no

            new_events: list[FilingNotificationEvent] = []

            if first_time:
                # First observation — just set the watermark. Skip notifications
                # so the feed doesn't get spammed with the user's historical
                # filings on first run.
                session.add(
                    MonitoredTicker(
                        ticker=ticker,
                        last_seen_accession_no=newest_accession,
                        last_polled_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()
                logger.info(
                    "event monitor: initialized watermark for %s @ %s",
                    ticker, newest_accession,
                )
                return

            # Collect the contiguous range of accessions newer than the
            # watermark. EDGAR returns newest-first, so walk until we hit
            # the last-seen.
            new_filings = []
            for f in filings:
                if f.accession_no == last_seen:
                    break
                new_filings.append(f)

            if not new_filings:
                watermark.last_polled_at = datetime.now(timezone.utc)
                await session.commit()
                return

            # Ingest oldest-first so the corpus order matches filing order.
            for meta in reversed(new_filings):
                try:
                    await ingest_one_filing(
                        session=session,
                        client=client,
                        ticker=ticker,
                        cik=cik,
                        meta=meta,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "event monitor: ingest failed for %s/%s — recording notification anyway",
                        ticker, meta.accession_no,
                    )

                notif = FilingNotification(
                    ticker=ticker,
                    form=meta.form,
                    accession_no=meta.accession_no,
                    filing_date=meta.filing_date,
                    primary_document=meta.primary_document,
                )
                session.add(notif)
                await session.flush()
                new_events.append(FilingNotificationEvent.from_row(notif))

            watermark.last_seen_accession_no = newest_accession
            watermark.last_polled_at = datetime.now(timezone.utc)
            await session.commit()

        # Publish *after* commit so subscribers can immediately fetch
        # the full row without racing the writer.
        for event in new_events:
            await self.bus.publish(event)
            logger.info(
                "event monitor: %s %s %s → notification #%d",
                event.ticker, event.form, event.filing_date, event.id,
            )

    # ─── universe resolution ────────────────────────────────────────────

    async def _resolve_universe(self) -> list[str]:
        """Prefer Alpaca holdings; fall back to the configured watchlist
        when Alpaca creds are missing. Either way, dedupe to upper-case."""
        tickers: list[str] = []

        from src.execution.alpaca import AlpacaClient, AlpacaClientError

        try:
            client = await asyncio.to_thread(AlpacaClient)
            positions = await asyncio.to_thread(client.get_positions)
            tickers = [p["ticker"] for p in positions if p.get("ticker")]
        except AlpacaClientError:
            logger.debug("event monitor: no Alpaca creds — using watchlist fallback")
        except Exception as e:  # noqa: BLE001
            logger.warning("event monitor: Alpaca call failed (%s) — using watchlist", e)

        if not tickers:
            try:
                tickers = list(self._config.get_watchlist() or [])
            except Exception:  # noqa: BLE001
                tickers = []

        return [t.upper() for t in tickers if t]
