"""Shared Alpaca trade-update bus.

Same fanout pattern as ``LivePriceBus`` but for the account-wide
trading-event websocket (order placed / partial fill / fill / canceled /
stop-loss filled / take-profit filled). One Alpaca TradingStream
connection is held open; every SSE subscriber gets its own queue.

The trading stream is account-scoped — no per-symbol subscription — so
the refcount machinery is simpler: ``subscribe_trade_updates`` is called
once on first subscriber arrival; everyone gets the same firehose.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


@dataclass
class TradeUpdateEvent:
    """A slim summary of an Alpaca trade_update payload.

    The Alpaca SDK emits a dataclass with nested order detail; we squash to
    the fields the toast UI actually renders, plus the raw event name for
    debugging."""

    event: str
    """Alpaca event name — new, partial_fill, fill, canceled, expired,
    rejected, stop_loss_filled, take_profit_filled, etc."""

    symbol: str
    side: str
    qty: float
    filled_qty: float
    filled_price: float | None
    order_id: str
    client_order_id: str | None
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "filled_qty": self.filled_qty,
            "filled_price": self.filled_price,
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "timestamp": self.timestamp,
        }


@dataclass(eq=False)
class _Subscriber:
    queue: asyncio.Queue[TradeUpdateEvent]
    loop: asyncio.AbstractEventLoop
    failed: bool = field(default=False)


class TradeUpdatesBusError(RuntimeError):
    """Raised when the bus can't reach Alpaca (missing creds, etc.)."""


class TradeUpdatesBus:
    """Singleton fanout for Alpaca trade_updates."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._stream = None  # alpaca.trading.stream.TradingStream
        self._run_task: asyncio.Task[None] | None = None
        self._subscribers: set[_Subscriber] = set()
        self._closed = False
        # Tier-2 #24: surface stream-task death. Pre-fix the run task
        # could end (auth rotation, network drop, alpaca-py internal
        # exception) and ``monitor_status`` still reported the bus as
        # "running" because ``self._run_task`` was a Task object — it
        # just happened to be in the done state. Operators missed
        # fill notifications on real trades. The ``is_healthy`` flag is
        # flipped by ``_on_stream_exit`` when the run task ends for any
        # reason; next ``_ensure_stream`` call re-creates the connection.
        self._stream_healthy = False
        self._stream_last_error: str | None = None

    @property
    def is_healthy(self) -> bool:
        """True iff the run task is alive AND the stream object exists.
        Operators / liveness probes should read this, not _run_task."""
        return (
            self._stream_healthy
            and self._stream is not None
            and self._run_task is not None
            and not self._run_task.done()
        )

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[_Subscriber]:
        if self._closed:
            raise TradeUpdatesBusError("bus is closed")
        subscriber = _Subscriber(
            queue=asyncio.Queue(maxsize=64),
            loop=asyncio.get_running_loop(),
        )
        await self._add(subscriber)
        try:
            yield subscriber
        finally:
            await self._remove(subscriber)

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            if self._run_task is not None and not self._run_task.done():
                self._run_task.cancel()
                try:
                    await self._run_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            if self._stream is not None:
                try:
                    await self._stream.stop_ws()
                except Exception as e:  # noqa: BLE001
                    logger.debug("trade_updates stop_ws raised: %s", e)
            self._stream = None
            self._run_task = None
            self._subscribers.clear()

    # ──────────────────────────────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────────────────────────────

    async def _ensure_stream(self) -> None:
        if self.is_healthy:
            # Live and well; nothing to do. Note we read ``is_healthy``
            # rather than ``_stream is not None`` so a dead-but-not-yet-
            # cleared stream triggers a re-create.
            return

        # Clear any stale state from a prior death before re-creating.
        # The done-callback usually clears these but we belt+suspenders
        # in case of a torn shutdown / re-entry.
        self._stream = None
        self._run_task = None
        self._stream_healthy = False

        api_key = os.getenv("ALPACA_API_KEY")
        api_secret = os.getenv("ALPACA_API_SECRET")
        if not api_key or not api_secret:
            raise TradeUpdatesBusError(
                "ALPACA_API_KEY and ALPACA_API_SECRET must be set to stream trade updates"
            )

        from alpaca.trading.stream import TradingStream

        # paper=True everywhere in this project — we never touch a live account.
        self._stream = TradingStream(api_key, api_secret, paper=True)
        self._stream.subscribe_trade_updates(self._on_update)

        loop = asyncio.get_running_loop()
        self._run_task = loop.create_task(
            asyncio.to_thread(self._stream.run), name="alpaca-trade-updates"
        )
        # Tier-2 #24: callback fires when the run task terminates for any
        # reason (clean exit, exception, cancellation). Without this, the
        # task could die silently and the bus would keep reporting "alive"
        # while no trade events arrived.
        self._run_task.add_done_callback(self._on_stream_exit)
        self._stream_healthy = True
        self._stream_last_error = None

    def _on_stream_exit(self, task: asyncio.Task[Any]) -> None:
        """Called when the run task ends. Logs the reason and clears
        state so the next subscriber triggers a reconnect via
        ``_ensure_stream``. Never raises — callbacks that raise from
        ``add_done_callback`` propagate to ``asyncio`` and can wedge
        the loop."""
        self._stream_healthy = False
        if task.cancelled():
            self._stream_last_error = "task cancelled"
            logger.info("trade_updates stream task cancelled (clean shutdown)")
            return
        exc = task.exception()
        if exc is not None:
            self._stream_last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "trade_updates stream task died: %s — bus will reconnect on "
                "next subscribe. Subscribers currently in flight will miss "
                "events until then.",
                self._stream_last_error,
            )
        else:
            self._stream_last_error = "task exited cleanly (no exception)"
            logger.warning(
                "trade_updates stream task ended without exception — "
                "alpaca-py may have lost the connection silently. Bus "
                "will reconnect on next subscribe."
            )
        # Janitor: mark all subscribers as failed so the next event-loop
        # iteration drops them; their SSE callers will see end-of-stream
        # and reconnect, picking up the new (healthy) bus instance.
        for sub in tuple(self._subscribers):
            sub.failed = True

    async def _add(self, subscriber: _Subscriber) -> None:
        async with self._lock:
            await self._ensure_stream()
            self._subscribers.add(subscriber)

    async def _remove(self, subscriber: _Subscriber) -> None:
        async with self._lock:
            self._subscribers.discard(subscriber)

    async def _on_update(self, raw: Any) -> None:
        """Alpaca handler. ``raw`` is a TradeUpdate dataclass; fan a slim
        summary to every subscriber."""
        try:
            order = getattr(raw, "order", None)
            event = TradeUpdateEvent(
                event=str(getattr(raw, "event", "unknown")),
                symbol=str(getattr(order, "symbol", "") or ""),
                side=str(getattr(order, "side", "") or ""),
                qty=float(getattr(order, "qty", 0) or 0),
                filled_qty=float(getattr(order, "filled_qty", 0) or 0),
                filled_price=(
                    float(getattr(order, "filled_avg_price", 0) or 0)
                    if getattr(order, "filled_avg_price", None)
                    else None
                ),
                order_id=str(getattr(order, "id", "") or ""),
                client_order_id=str(getattr(order, "client_order_id", "") or "")
                or None,
                timestamp=str(getattr(raw, "timestamp", "") or ""),
            )
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug("malformed trade_update dropped: %s", e)
            return

        for sub in tuple(self._subscribers):
            if sub.failed:
                continue
            try:
                sub.loop.call_soon_threadsafe(self._deliver, sub, event)
            except RuntimeError:
                sub.failed = True

    @staticmethod
    def _deliver(sub: _Subscriber, event: TradeUpdateEvent) -> None:
        try:
            sub.queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                sub.queue.get_nowait()
                sub.queue.put_nowait(event)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass
