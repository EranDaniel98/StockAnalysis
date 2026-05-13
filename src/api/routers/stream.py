"""SSE streaming channels.

Channels:
  - /api/stream/portfolio       live Alpaca P&L snapshot every N seconds
  - /api/stream/heartbeat       process liveness ticker (debug/dev)
  - /api/stream/scan            run a scan and stream progress events; final
                                event carries {run_id, n_results}
  - /api/stream/prices          live Alpaca trade ticks for requested symbols
                                via the shared LivePriceBus
  - /api/stream/trade-updates   account-wide Alpaca order events via the
                                shared TradeUpdatesBus
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from sse_starlette.sse import EventSourceResponse

from src.api.dependencies import (
    get_config,
    get_db_session,
    get_live_prices,
    get_trade_updates,
)
from src.api.schemas.scan import ScanResultItem
from src.api.services.live_prices import LivePriceBus, LivePriceBusError
from src.api.services.scan_runner import run_scan_sync
from src.api.services.trade_updates import TradeUpdatesBus, TradeUpdatesBusError
from src.config_loader import Config
from src.db.models import ScanRun
from src.execution.alpaca import AlpacaClient, AlpacaClientError
from sqlalchemy.ext.asyncio import AsyncSession

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


# ─── Scan progress ───────────────────────────────────────────────────────────


# Sentinel placed on the queue when the worker task is done. Distinct object
# identity (not a stage name) so a legitimate event named "_done" couldn't
# collide.
_QUEUE_DONE = object()


async def _scan_event_stream(
    request: Request,
    config: Config,
    db: AsyncSession,
    *,
    strategy_name: str,
    budget: float | None,
    universe: str | None,
    theme: str | None,
    sector: str | None,
    top: int | None,
    fresh: bool,
    live_signals: bool,
) -> AsyncIterator[dict]:
    """Run a scan in a worker thread, drain its progress events to the SSE
    client, then emit a final `complete` event carrying the persisted run_id.

    The runner's callback fires from the worker thread; we bridge with
    `loop.call_soon_threadsafe` so we never touch the asyncio queue from a
    foreign thread.
    """
    try:
        strategy_cfg = config.get_strategy(strategy_name)
    except KeyError:
        yield {
            "event": "error",
            "data": json.dumps({"detail": f"unknown strategy '{strategy_name}'"}),
        }
        return

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def on_event(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def worker() -> None:
        try:
            recs = await asyncio.to_thread(
                run_scan_sync,
                config,
                strategy_cfg,
                universe=universe,
                theme=theme,
                sector=sector,
                fresh=fresh,
                live_signals=live_signals,
                on_event=on_event,
            )
            if top is not None:
                recs = recs[:top]

            # Persist scan_run synchronously inside the worker so the
            # `complete` event already carries a usable run_id.
            results = [ScanResultItem.model_validate(r) for r in recs]
            run_id = str(uuid.uuid4())
            scan_ts = datetime.now(timezone.utc)
            row = ScanRun(
                strategy=strategy_name,
                scan_timestamp=scan_ts,
                universe_label=run_id,
                budget=budget,
                n_candidates=len(results),
                recommendations=[r.model_dump() for r in results],
            )
            db.add(row)
            await db.commit()

            await queue.put(
                {
                    "stage": "complete",
                    "run_id": run_id,
                    "n_results": len(results),
                    "strategy": strategy_name,
                }
            )
        except Exception as e:  # noqa: BLE001 — surface to client, keep server alive
            logger.exception("scan worker failed")
            await queue.put({"stage": "error", "detail": str(e)})
        finally:
            await queue.put(_QUEUE_DONE)

    task = asyncio.create_task(worker())

    try:
        while True:
            # Yield control + check for disconnect between events.
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if await request.is_disconnected():
                    task.cancel()
                    return
                # heartbeat keeps the connection warm during long stages
                yield {"event": "heartbeat", "data": "{}"}
                continue

            if event is _QUEUE_DONE:
                return

            if event.get("stage") == "error":
                yield {"event": "error", "data": json.dumps(event)}
                continue
            if event.get("stage") == "complete":
                yield {"event": "complete", "data": json.dumps(event)}
                continue
            yield {"event": "progress", "data": json.dumps(event)}
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


@router.get("/scan")
async def stream_scan(
    request: Request,
    strategy: str = Query(default="swing_trading"),
    budget: float | None = Query(default=None, gt=0),
    universe: str | None = Query(default=None),
    theme: str | None = Query(default=None),
    sector: str | None = Query(default=None),
    top: int | None = Query(default=None, gt=0, le=200),
    fresh: bool = Query(default=False),
    live_signals: bool = Query(default=True),
    config: Config = Depends(get_config),
    db: AsyncSession = Depends(get_db_session),
) -> EventSourceResponse:
    """Run a scan and stream progress over SSE.

    EventSource only supports GET, so all params come via query string.
    Emits these named events:
      - `progress`   {stage, n?}    pipeline stage transitions
      - `heartbeat`  {}             every ~1s when no progress event fires
      - `error`      {detail}       fatal failure; stream ends
      - `complete`   {run_id, n_results, strategy}   scan persisted

    Disconnect cancels the worker task. The complete event includes the
    `run_id` so the client can `GET /api/scans/{run_id}` for full results.
    """
    return EventSourceResponse(
        _scan_event_stream(
            request,
            config,
            db,
            strategy_name=strategy,
            budget=budget,
            universe=universe,
            theme=theme,
            sector=sector,
            top=top,
            fresh=fresh,
            live_signals=live_signals,
        )
    )
