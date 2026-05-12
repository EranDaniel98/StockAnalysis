"""SSE streaming channels.

Two channels:
  - /api/stream/portfolio   live Alpaca P&L snapshot every N seconds
  - /api/stream/heartbeat   process liveness ticker (debug/dev)

/api/stream/scan-progress is reserved for Phase 1.7 follow-up — the existing
scan pipeline doesn't emit progress events yet (it prints to Rich console).
Wiring that requires threading an event queue through ScanRunner, which is
better done after the CLI carve lands in src/cli/.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

from src.execution.alpaca import AlpacaClient, AlpacaClientError

logger = logging.getLogger(__name__)
router = APIRouter()


async def _portfolio_event_stream(
    request: Request, poll_seconds: float
) -> AsyncIterator[dict]:
    """Yield SSE events with an Alpaca snapshot at each poll. Tears down when
    the client disconnects (FastAPI sets request.is_disconnected)."""
    try:
        client = AlpacaClient()
    except AlpacaClientError as e:
        yield {"event": "error", "data": json.dumps({"detail": str(e)})}
        return

    while True:
        if await request.is_disconnected():
            return
        try:
            account = await asyncio.to_thread(client.get_account)
            positions = await asyncio.to_thread(client.get_positions)
            yield {
                "event": "snapshot",
                "data": json.dumps(
                    {"account": account, "positions": positions, "n": len(positions)}
                ),
            }
        except Exception as e:
            # Emit and keep streaming — transient Alpaca errors shouldn't kill
            # the channel. Client decides how to react.
            logger.warning("portfolio stream snapshot failed: %s", e)
            yield {"event": "error", "data": json.dumps({"detail": str(e)})}
        await asyncio.sleep(poll_seconds)


@router.get("/portfolio")
async def stream_portfolio(
    request: Request,
    poll_seconds: float = Query(default=5.0, gt=1.0, le=60.0),
) -> EventSourceResponse:
    """Live portfolio P&L. Emits an `event: snapshot` every poll_seconds with
    {account, positions, n}. Heartbeats are auto-sent by sse_starlette."""
    return EventSourceResponse(_portfolio_event_stream(request, poll_seconds))


async def _heartbeat_stream(request: Request) -> AsyncIterator[dict]:
    n = 0
    while True:
        if await request.is_disconnected():
            return
        yield {"event": "tick", "data": json.dumps({"n": n})}
        n += 1
        await asyncio.sleep(2.0)


@router.get("/heartbeat")
async def stream_heartbeat(request: Request) -> EventSourceResponse:
    """Process-liveness ticker. Use for sanity-checking SSE plumbing."""
    return EventSourceResponse(_heartbeat_stream(request))
