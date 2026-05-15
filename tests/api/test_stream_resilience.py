"""Tier-2 audit #24: stream buses surface task death and reconnect.

Pre-fix: ``TradeUpdatesBus._run_task`` was a Task object that could
end (auth rotation, network drop, alpaca-py internal exception) while
``self._stream`` stayed set. No code observed the done state, so a
liveness check based on ``_run_task is not None`` reported "alive"
forever after death. Operators missed fill notifications on real
trades.

After:
  * ``_run_task.add_done_callback(_on_stream_exit)`` fires when the
    task ends for any reason.
  * The callback flips ``_stream_healthy=False``, captures the
    exception, marks subscribers as failed, and clears the stream.
  * ``is_healthy`` property combines the flag with the task state.
  * Next ``_ensure_stream`` call reconnects.

Same fix applied to ``LivePriceBus``. This file pins both.
"""

from __future__ import annotations

import asyncio

import pytest

from src.api.services.live_prices import LivePriceBus
from src.api.services.trade_updates import TradeUpdatesBus


# --- TradeUpdatesBus -------------------------------------------------------


def test_trade_updates_bus_starts_unhealthy():
    """No stream yet → is_healthy is False, not True."""
    bus = TradeUpdatesBus()
    assert bus.is_healthy is False


@pytest.mark.asyncio
async def test_trade_updates_bus_flips_unhealthy_on_task_exception():
    """Simulate the failure mode: assign a finished task with an
    exception. The done-callback wires up via _ensure_stream, but for
    a unit test we exercise the callback directly with a stub task."""
    bus = TradeUpdatesBus()

    # Stand up minimal state as if _ensure_stream had succeeded.
    bus._stream = object()  # stand-in
    fake_task = asyncio.Future()
    fake_task.set_exception(RuntimeError("alpaca auth rotated"))
    # Avoid "exception never retrieved" warnings:
    fake_task.exception()
    bus._run_task = fake_task  # type: ignore[assignment]
    bus._stream_healthy = True

    # Now fire the callback — same path as add_done_callback would.
    bus._on_stream_exit(fake_task)  # type: ignore[arg-type]

    assert bus._stream_healthy is False
    assert "RuntimeError" in (bus._stream_last_error or "")
    assert "alpaca auth rotated" in (bus._stream_last_error or "")
    # is_healthy should now report False too (flag + done task).
    assert bus.is_healthy is False


@pytest.mark.asyncio
async def test_trade_updates_bus_flips_unhealthy_on_clean_exit():
    """The "task exited without exception" case — alpaca-py losing
    the connection silently. Pre-fix this was the WORST case because
    no exception ever surfaced. Now it logs a WARNING."""
    bus = TradeUpdatesBus()
    bus._stream = object()
    fake_task = asyncio.Future()
    fake_task.set_result(None)  # clean exit, no exception
    bus._run_task = fake_task  # type: ignore[assignment]
    bus._stream_healthy = True

    bus._on_stream_exit(fake_task)  # type: ignore[arg-type]

    assert bus._stream_healthy is False
    assert "no exception" in (bus._stream_last_error or "")


@pytest.mark.asyncio
async def test_trade_updates_bus_cancellation_is_quiet():
    """A cancelled task is a clean shutdown — don't WARN about it."""
    bus = TradeUpdatesBus()
    bus._stream = object()
    fake_task = asyncio.Future()
    fake_task.cancel()
    bus._run_task = fake_task  # type: ignore[assignment]
    bus._stream_healthy = True

    bus._on_stream_exit(fake_task)  # type: ignore[arg-type]

    assert bus._stream_healthy is False
    assert bus._stream_last_error == "task cancelled"


# --- LivePriceBus mirrors the same pattern ---------------------------------


def test_live_prices_bus_starts_unhealthy():
    bus = LivePriceBus()
    assert bus.is_healthy is False


@pytest.mark.asyncio
async def test_live_prices_bus_flips_unhealthy_on_exception():
    bus = LivePriceBus()
    bus._stream = object()
    fake_task = asyncio.Future()
    fake_task.set_exception(ConnectionError("ws closed by peer"))
    fake_task.exception()  # silence unretrieved warning
    bus._run_task = fake_task  # type: ignore[assignment]
    bus._stream_healthy = True

    bus._on_stream_exit(fake_task)  # type: ignore[arg-type]

    assert bus.is_healthy is False
    assert "ConnectionError" in (bus._stream_last_error or "")


@pytest.mark.asyncio
async def test_live_prices_bus_marks_subscribers_failed_on_death():
    """The janitor pass: after the stream dies, every existing
    subscriber must be marked failed=True so its SSE caller's next
    iteration drops it and reconnects."""
    from src.api.services.live_prices import _Subscriber

    bus = LivePriceBus()
    bus._stream = object()
    sub = _Subscriber(
        symbols={"AAPL"},
        queue=asyncio.Queue(),
        loop=asyncio.get_running_loop(),
    )
    bus._subscribers = {"AAPL": {sub}}

    fake_task = asyncio.Future()
    fake_task.set_exception(RuntimeError("network blip"))
    fake_task.exception()
    bus._run_task = fake_task  # type: ignore[assignment]
    bus._stream_healthy = True

    assert sub.failed is False
    bus._on_stream_exit(fake_task)  # type: ignore[arg-type]
    assert sub.failed is True


@pytest.mark.asyncio
async def test_trade_updates_marks_subscribers_failed_on_death():
    """Same janitor pass on the trade-updates bus."""
    from src.api.services.trade_updates import _Subscriber

    bus = TradeUpdatesBus()
    bus._stream = object()
    sub = _Subscriber(
        queue=asyncio.Queue(),
        loop=asyncio.get_running_loop(),
    )
    bus._subscribers = {sub}

    fake_task = asyncio.Future()
    fake_task.set_exception(RuntimeError("auth rotated"))
    fake_task.exception()
    bus._run_task = fake_task  # type: ignore[assignment]
    bus._stream_healthy = True

    assert sub.failed is False
    bus._on_stream_exit(fake_task)  # type: ignore[arg-type]
    assert sub.failed is True
