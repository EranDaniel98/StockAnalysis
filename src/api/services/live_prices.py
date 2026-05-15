"""Shared Alpaca data-stream bus.

Alpaca free-tier accounts get **one** concurrent data-websocket connection,
so every SSE subscriber on /api/stream/prices has to share a single
``StockDataStream``. This module owns that singleton.

Design:
  - Refcount per symbol — subscribe to Alpaca only when the first listener
    cares, unsubscribe when the last leaves
  - Per-subscriber asyncio.Queue fanout — Alpaca's callback fires in the
    stream's own task; we hop back to the listener's loop via
    ``loop.call_soon_threadsafe`` since the stream callback runs in its
    own thread when ``stream.run()`` is started from ``asyncio.to_thread``
  - Lazy connect — bus stays cold until the first SSE client arrives, so
    a cold dev server doesn't burn the connection quota
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
class TradeEvent:
    symbol: str
    price: float
    size: float
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "size": self.size,
            "timestamp": self.timestamp,
        }


@dataclass(eq=False)
class _Subscriber:
    """Per-client state: which symbols + the queue we push trades into.
    Anchored to the listener's loop so we can hop threads safely.

    ``eq=False`` so the dataclass falls back to identity-based __eq__ and
    __hash__, which lets us put instances in the refcount sets without
    requiring frozen=True (we need to mutate ``failed`` from the stream
    callback thread)."""

    symbols: set[str]
    queue: asyncio.Queue[TradeEvent]
    loop: asyncio.AbstractEventLoop
    failed: bool = field(default=False)


class LivePriceBusError(RuntimeError):
    """Raised when the bus can't talk to Alpaca (missing creds, etc.)."""


class LivePriceBus:
    """Shared Alpaca data-stream fanout.

    Methods are async — internal state is mutated under a single lock so
    refcount math stays consistent across concurrent ``subscribe`` /
    ``unsubscribe`` calls.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._stream = None  # alpaca.data.live.StockDataStream
        self._run_task: asyncio.Task[None] | None = None
        self._symbol_refcounts: dict[str, int] = {}
        self._subscribers: dict[str, set[_Subscriber]] = {}
        self._closed = False
        # Tier-2 #24: same silent-death surface as TradeUpdatesBus.
        # ``self._run_task`` being a Task object doesn't tell us the
        # stream is alive — it could be in the done state.
        self._stream_healthy = False
        self._stream_last_error: str | None = None

    @property
    def is_healthy(self) -> bool:
        """True iff the stream task is alive AND the stream object exists."""
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
    async def subscribe(self, symbols: set[str]) -> AsyncIterator[_Subscriber]:
        """Open a subscription for ``symbols``; yield a ``_Subscriber`` whose
        ``queue`` receives ``TradeEvent`` instances. Cleans up on exit."""
        if self._closed:
            raise LivePriceBusError("bus is closed")

        symbols = {s.upper() for s in symbols if s}
        if not symbols:
            # No symbols to subscribe — yield a dead subscriber so the caller
            # can still treat this uniformly. Its queue stays empty.
            yield _Subscriber(
                symbols=set(), queue=asyncio.Queue(), loop=asyncio.get_running_loop()
            )
            return

        subscriber = _Subscriber(
            symbols=symbols,
            queue=asyncio.Queue(maxsize=256),
            loop=asyncio.get_running_loop(),
        )

        await self._add(subscriber)
        try:
            yield subscriber
        finally:
            await self._remove(subscriber)

    async def close(self) -> None:
        """Tear down the stream + cancel its run task. Called from the
        FastAPI lifespan."""
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
                    logger.debug("stop_ws raised on close: %s", e)
            self._stream = None
            self._run_task = None
            self._symbol_refcounts.clear()
            self._subscribers.clear()

    # ──────────────────────────────────────────────────────────────────
    # Internal — refcount + Alpaca interaction
    # ──────────────────────────────────────────────────────────────────

    async def _ensure_stream(self) -> None:
        """Lazily build the StockDataStream and start its run task."""
        if self.is_healthy:
            return

        # Clear stale state from any prior death before re-creating.
        self._stream = None
        self._run_task = None
        self._stream_healthy = False

        api_key = os.getenv("ALPACA_API_KEY")
        api_secret = os.getenv("ALPACA_API_SECRET")
        if not api_key or not api_secret:
            raise LivePriceBusError(
                "ALPACA_API_KEY and ALPACA_API_SECRET must be set to stream prices"
            )

        # Import inside the function so a missing alpaca-py at import time
        # doesn't break the whole API.
        from alpaca.data.live import StockDataStream

        self._stream = StockDataStream(api_key, api_secret)

        # `stream.run()` is sync and blocks; alpaca-py drives its own asyncio
        # loop inside. Run it in a thread so it doesn't fight our loop.
        loop = asyncio.get_running_loop()
        self._run_task = loop.create_task(
            asyncio.to_thread(self._stream.run), name="alpaca-data-stream"
        )
        # Tier-2 #24: same done-callback resilience as TradeUpdatesBus.
        self._run_task.add_done_callback(self._on_stream_exit)
        self._stream_healthy = True
        self._stream_last_error = None

    def _on_stream_exit(self, task: asyncio.Task[Any]) -> None:
        """Stream task ended for any reason — log and clear so the next
        subscribe call reconnects. Never raises (callback)."""
        self._stream_healthy = False
        if task.cancelled():
            self._stream_last_error = "task cancelled"
            logger.info("live_prices stream task cancelled (clean shutdown)")
            return
        exc = task.exception()
        if exc is not None:
            self._stream_last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "live_prices stream task died: %s — bus will reconnect on "
                "next subscribe. In-flight subscribers will see no ticks "
                "until then.",
                self._stream_last_error,
            )
        else:
            self._stream_last_error = "task exited cleanly (no exception)"
            logger.warning(
                "live_prices stream task ended without exception — "
                "alpaca-py may have lost the connection silently."
            )
        # Janitor: mark all subscribers as failed so the next iteration
        # drops them and the SSE caller reconnects, picking up the new bus.
        for symbol_subs in self._subscribers.values():
            for sub in tuple(symbol_subs):
                sub.failed = True

    async def _add(self, subscriber: _Subscriber) -> None:
        async with self._lock:
            await self._ensure_stream()

            new_symbols: list[str] = []
            for sym in subscriber.symbols:
                if self._symbol_refcounts.get(sym, 0) == 0:
                    new_symbols.append(sym)
                self._symbol_refcounts[sym] = self._symbol_refcounts.get(sym, 0) + 1
                self._subscribers.setdefault(sym, set()).add(subscriber)

            if new_symbols and self._stream is not None:
                # subscribe_trades takes the handler + *symbols. Calling it
                # multiple times merges; same handler closure works across
                # all symbols.
                self._stream.subscribe_trades(self._on_trade, *new_symbols)

    async def _remove(self, subscriber: _Subscriber) -> None:
        async with self._lock:
            zeroed: list[str] = []
            for sym in subscriber.symbols:
                if sym in self._subscribers:
                    self._subscribers[sym].discard(subscriber)
                count = self._symbol_refcounts.get(sym, 0) - 1
                if count <= 0:
                    self._symbol_refcounts.pop(sym, None)
                    self._subscribers.pop(sym, None)
                    zeroed.append(sym)
                else:
                    self._symbol_refcounts[sym] = count

            if zeroed and self._stream is not None:
                try:
                    self._stream.unsubscribe_trades(*zeroed)
                except Exception as e:  # noqa: BLE001
                    logger.debug("unsubscribe_trades raised: %s", e)

    async def _on_trade(self, trade: Any) -> None:
        """Alpaca handler. Fan out to every subscriber that asked for this
        symbol. We DO NOT await each queue.put here — slow consumers would
        block the stream; instead we ``put_nowait`` and drop on overflow,
        which is the right tradeoff for tick data (next tick always wins)."""
        try:
            symbol = trade.symbol
            price = float(trade.price)
            size = float(getattr(trade, "size", 0) or 0)
            ts = getattr(trade, "timestamp", None)
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug("malformed trade event dropped: %s", e)
            return

        event = TradeEvent(symbol=symbol, price=price, size=size, timestamp=ts_str)

        subscribers = self._subscribers.get(symbol)
        if not subscribers:
            return
        # Snapshot the set so concurrent _remove doesn't trip iteration.
        for sub in tuple(subscribers):
            if sub.failed:
                continue
            try:
                sub.loop.call_soon_threadsafe(self._deliver, sub, event)
            except RuntimeError:
                # Listener loop has shut down — mark and let the SSE handler
                # discover it via the queue close path.
                sub.failed = True

    @staticmethod
    def _deliver(sub: _Subscriber, event: TradeEvent) -> None:
        try:
            sub.queue.put_nowait(event)
        except asyncio.QueueFull:
            # Drop oldest, keep newest — tick data, freshness wins.
            try:
                sub.queue.get_nowait()
                sub.queue.put_nowait(event)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass
