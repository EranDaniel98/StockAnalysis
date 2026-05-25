"""SSE streaming channels.

Channels:
  - /api/stream/portfolio       live Alpaca P&L snapshot every N seconds
  - /api/stream/heartbeat       process liveness ticker (debug/dev)
  - /api/stream/prices          live Alpaca trade ticks for requested symbols
                                via the shared LivePriceBus
  - /api/stream/trade-updates   account-wide Alpaca order events via the
                                shared TradeUpdatesBus

``/api/stream/scan`` was deleted 2026-05-23 along with the legacy 5-engine
``POST /api/scans`` route — both ran the on-demand scoring chain that no
live FE component still calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from sse_starlette.sse import EventSourceResponse

from src.api.dependencies import (
    get_live_prices,
    get_trade_updates,
)
from src.api.services.live_prices import LivePriceBus, LivePriceBusError
from src.api.services.trade_updates import TradeUpdatesBus, TradeUpdatesBusError
from src.execution.alpaca import AlpacaClient, AlpacaClientError

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Portfolio + heartbeat (existing) ────────────────────────────────────────


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
    return EventSourceResponse(_heartbeat_stream(request))


# ─── Live prices ─────────────────────────────────────────────────────────────


async def _prices_event_stream(
    request: Request, bus: LivePriceBus, symbols: set[str]
) -> AsyncIterator[dict]:
    """Subscribe to the shared LivePriceBus and re-emit each trade as an SSE
    ``trade`` event. Sends a ``heartbeat`` every second when no trade fires so
    intermediaries don't drop the connection during quiet markets."""
    try:
        async with bus.subscribe(symbols) as subscriber:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(subscriber.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
                    continue
                yield {"event": "trade", "data": json.dumps(event.to_dict())}
    except LivePriceBusError as e:
        yield {"event": "error", "data": json.dumps({"detail": str(e)})}


@router.get("/prices")
async def stream_prices(
    request: Request,
    symbols: str = Query(
        ..., description="Comma-separated symbols (e.g. AAPL,MSFT,TSLA)"
    ),
    bus: LivePriceBus = Depends(get_live_prices),
) -> EventSourceResponse:
    """Live trade feed over SSE. Emits ``trade`` events
    ``{symbol, price, size, timestamp}`` for every Alpaca trade tick on the
    requested symbols; ``heartbeat`` events when idle.

    All clients share one underlying Alpaca data-websocket connection — the
    free-tier quota is one socket per account, so the server multiplexes.
    """
    requested = {s.strip().upper() for s in symbols.split(",") if s.strip()}
    return EventSourceResponse(_prices_event_stream(request, bus, requested))


# ─── Trade updates (order fills, stops, take-profits) ───────────────────────


async def _trade_updates_stream(
    request: Request, bus: TradeUpdatesBus
) -> AsyncIterator[dict]:
    try:
        async with bus.subscribe() as subscriber:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(subscriber.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
                    continue
                yield {"event": "update", "data": json.dumps(event.to_dict())}
    except TradeUpdatesBusError as e:
        yield {"event": "error", "data": json.dumps({"detail": str(e)})}


@router.get("/trade-updates")
async def stream_trade_updates(
    request: Request,
    bus: TradeUpdatesBus = Depends(get_trade_updates),
) -> EventSourceResponse:
    """Account-wide Alpaca order events. Emits ``update`` per order state
    change (new, partial_fill, fill, canceled, stop_loss_filled,
    take_profit_filled, etc.). Frontend turns these into toasts."""
    return EventSourceResponse(_trade_updates_stream(request, bus))


# /api/stream/scan was deleted 2026-05-23. It ran the legacy 5-engine
# scoring chain through src.api.services.scan_runner; no live FE component
# still consumes it (the scan page now SSE-tails scripts.run_daily_pipeline
# via /api/stream/pipeline-progress).
