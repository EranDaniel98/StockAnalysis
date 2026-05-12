"""/api/research — autonomous research agent.

POST /api/research/ask           fire one research run synchronously
POST /api/research/ask/stream    same, but SSE-stream the agent's mid-run thoughts
GET  /api/research/runs          recent runs (newest first)
GET  /api/research/runs/{id}     one run; include_transcript=true for the full transcript

The streaming endpoint is the recommended one for the UI; the
synchronous endpoint is kept for scripted callers and parity.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_config, get_db_session, get_event_monitor
from src.api.schemas.research import (
    FilingNotificationItem,
    ResearchAskRequest,
    ResearchRunDetail,
    ResearchRunSummary,
    SummarizeNotificationResponse,
    ToolCallEntry,
)
from src.config_loader import Config
from src.db.models import FilingNotification, ResearchRun
from src.research_agent.event_monitor import EventMonitor
from src.research_agent.llm_client import DEFAULT_MODEL
from src.research_agent.orchestrator import run_research

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_summary(row: ResearchRun) -> ResearchRunSummary:
    return ResearchRunSummary(
        id=row.id,
        question=row.question,
        model=row.model,
        status=row.status,
        final_answer=row.final_answer,
        n_turns=row.n_turns,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        estimated_cost_usd=float(row.estimated_cost_usd or 0),
        started_at=row.started_at,
        completed_at=row.completed_at,
        error=row.error,
    )


def _to_detail(row: ResearchRun, *, include_transcript: bool) -> ResearchRunDetail:
    base = _to_summary(row).model_dump()
    return ResearchRunDetail(
        **base,
        tool_calls=[ToolCallEntry(**c) for c in (row.tool_calls or [])],
        transcript=list(row.transcript or []) if include_transcript else [],
    )


@router.post("/ask", response_model=ResearchRunDetail)
async def ask(
    body: ResearchAskRequest,
    request: Request,
    config: Config = Depends(get_config),
) -> ResearchRunDetail:
    """Kick off one synchronous research run. Returns the completed
    (or failed / budget_exceeded) run row inline.

    The orchestrator never raises on tool failures — those are threaded
    back into the transcript. We do raise 503 if the ANTHROPIC_API_KEY
    is missing so the UI can prompt for setup.
    """
    sessionmaker = request.app.state.sessionmaker
    try:
        row = await run_research(
            body.question,
            sessionmaker=sessionmaker,
            config=config,
            model=body.model or DEFAULT_MODEL,
            max_turns=body.max_turns,
            notes=body.notes,
        )
    except RuntimeError as e:
        # The only RuntimeError the orchestrator raises is the missing
        # API key from AnthropicClient.__init__. Other crashes are caught
        # internally and persisted with status='failed'.
        if "ANTHROPIC_API_KEY" in str(e):
            raise HTTPException(status_code=503, detail=str(e))
        raise

    return _to_detail(row, include_transcript=False)


@router.post("/ask/stream")
async def ask_stream(
    body: ResearchAskRequest,
    request: Request,
    config: Config = Depends(get_config),
) -> EventSourceResponse:
    """Stream the agent's mid-run thoughts over SSE.

    Events (named):
      - ``started``         {run_id, question}
      - ``turn_start``      {turn}
      - ``assistant_text``  {turn, text}   any prose the model emits
                                            alongside a tool call
      - ``tool_call``       {turn, tool, input}
      - ``tool_result``     {turn, tool, is_error, summary}
      - ``usage``           {turn, input_tokens, output_tokens, cost_usd}
      - ``final_answer``    {text}
      - ``complete``        {run_id, status}
      - ``error``           {detail, kind}

    Client disconnects cancel the worker task — the partial run row
    stays in the DB with whatever transcript it had at the time.
    """
    sessionmaker = request.app.state.sessionmaker
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def _on_event(event: dict[str, Any]) -> None:
        await queue.put(event)

    async def _runner() -> None:
        try:
            await run_research(
                body.question,
                sessionmaker=sessionmaker,
                config=config,
                model=body.model or DEFAULT_MODEL,
                max_turns=body.max_turns,
                notes=body.notes,
                on_event=_on_event,
            )
        except RuntimeError as e:
            # Missing API key — surface as an error event so the client
            # gets a clean failure instead of a hung stream.
            await queue.put({"event": "error", "detail": str(e), "kind": "setup"})
        finally:
            await queue.put(None)

    runner_task = asyncio.create_task(_runner())

    async def _stream() -> AsyncIterator[dict[str, str]]:
        try:
            while True:
                if await request.is_disconnected():
                    runner_task.cancel()
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Heartbeat so proxies don't time the connection out.
                    yield {"event": "heartbeat", "data": "{}"}
                    continue
                if event is None:
                    return
                yield {
                    "event": event.get("event", "message"),
                    "data": json.dumps(event, default=str),
                }
        finally:
            if not runner_task.done():
                runner_task.cancel()
            # Drain the cancellation so the task object doesn't get GC'd
            # with a pending exception.
            try:
                await runner_task
            except (asyncio.CancelledError, Exception):
                pass

    return EventSourceResponse(_stream())


@router.get("/runs", response_model=list[ResearchRunSummary])
async def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> list[ResearchRunSummary]:
    stmt = select(ResearchRun).order_by(desc(ResearchRun.started_at))
    if status:
        stmt = stmt.where(ResearchRun.status == status)
    stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_summary(r) for r in rows]


@router.get("/runs/{run_id}", response_model=ResearchRunDetail)
async def get_run(
    run_id: int,
    include_transcript: bool = Query(default=False),
    db: AsyncSession = Depends(get_db_session),
) -> ResearchRunDetail:
    row = await db.get(ResearchRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"research run {run_id} not found")
    return _to_detail(row, include_transcript=include_transcript)


# ─── filing notifications ───────────────────────────────────────────────────


def _notif_to_schema(row: FilingNotification) -> FilingNotificationItem:
    return FilingNotificationItem(
        id=row.id,
        ticker=row.ticker,
        form=row.form,
        accession_no=row.accession_no,
        filing_date=row.filing_date.isoformat(),
        primary_document=row.primary_document,
        detected_at=row.detected_at,
        research_run_id=row.research_run_id,
        summary=row.summary,
    )


@router.get("/notifications", response_model=list[FilingNotificationItem])
async def list_notifications(
    limit: int = Query(default=30, ge=1, le=200),
    ticker: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> list[FilingNotificationItem]:
    """Recent filings the background monitor surfaced. Newest first."""
    stmt = select(FilingNotification).order_by(desc(FilingNotification.detected_at))
    if ticker:
        stmt = stmt.where(FilingNotification.ticker == ticker.upper())
    stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [_notif_to_schema(r) for r in rows]


@router.post(
    "/notifications/{notification_id}/summarize",
    response_model=SummarizeNotificationResponse,
)
async def summarize_notification(
    notification_id: int,
    request: Request,
    config: Config = Depends(get_config),
    db: AsyncSession = Depends(get_db_session),
) -> SummarizeNotificationResponse:
    """Kick off an agent run to summarize one filing.

    Uses ``search_filings`` under the hood — the filing's chunks are
    already in the corpus (the monitor ingested them at detection
    time). Result is cached on ``filing_notifications.summary`` so
    repeat clicks return instantly.
    """
    row = await db.get(FilingNotification, notification_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"notification {notification_id} not found"
        )

    sessionmaker = request.app.state.sessionmaker

    # Build a sharply scoped prompt so the agent doesn't go on a tangent.
    question = (
        f"Summarize the key takeaways from {row.ticker}'s {row.form} filed on "
        f"{row.filing_date.isoformat()} (accession {row.accession_no}). "
        f"Use search_filings with ticker={row.ticker!r}, form={row.form!r} "
        f"to retrieve the relevant chunks, then write 3-5 bullets covering: "
        f"what happened, why it matters, and any forward-looking guidance."
    )

    try:
        run_row = await run_research(
            question,
            sessionmaker=sessionmaker,
            config=config,
            max_turns=4,
            notes=f"auto-summary of notification #{row.id}",
        )
    except RuntimeError as e:
        if "ANTHROPIC_API_KEY" in str(e):
            raise HTTPException(status_code=503, detail=str(e))
        raise

    # Re-fetch the notification and link it. ``row`` is from before the
    # nested transactions inside run_research; refresh first.
    await db.refresh(row)
    row.research_run_id = run_row.id
    row.summary = run_row.final_answer
    await db.commit()
    await db.refresh(row)

    return SummarizeNotificationResponse(
        notification=_notif_to_schema(row),
        run=_to_detail(run_row, include_transcript=False),
    )


@router.get("/notifications/stream")
async def stream_notifications(
    request: Request,
    monitor: EventMonitor = Depends(get_event_monitor),
) -> EventSourceResponse:
    """SSE channel: live filing notifications. Events are named
    ``notification`` with the persisted row's slim shape.

    No ``status`` event on the channel — the EventMonitor is either
    running (background task alive) or not (env-disabled); the API
    surface for that lives at ``GET /api/research/monitor/status``."""

    async def _stream() -> AsyncIterator[dict[str, str]]:
        async with monitor.bus.subscribe() as sub:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
                    continue
                yield {
                    "event": "notification",
                    "data": json.dumps(event.to_dict(), default=str),
                }

    return EventSourceResponse(_stream())


@router.get("/monitor/status")
async def monitor_status(
    monitor: EventMonitor = Depends(get_event_monitor),
) -> dict[str, Any]:
    """Lightweight liveness probe for the /research/feed page header."""
    return {
        "running": monitor.is_running,
        "poll_seconds": monitor._poll_seconds,  # noqa: SLF001 — read-only
        "forms": list(monitor._forms),  # noqa: SLF001 — read-only
    }
