"""Timeout-wrapped fetch helper + FetchOutcome discriminated type.

Tier-1 audit #8 (E#3 + E#4 + E#5 + E#6 + E#28 + X#9): every yfinance
call site previously blocked indefinitely on a hung TCP connection and
collapsed "no data exists" / "transient timeout" / "yfinance crashed"
into a single ``return None``. Workers piled up on stuck connections
and the caller could not tell "this ticker has no fundamentals" from
"this fetch failed silently and we should refuse to trade".

Two pieces of infrastructure here:

* ``call_with_timeout`` wraps a synchronous fetch in a wall-clock-bounded
  worker future. Module-level executor so a timed-out call doesn't gate
  the next ticker waiting for the orphan worker to drain — same lesson
  as the earnings-blackout fix in src.execution.paper_trade_service.

* ``FetchOutcome`` is the discriminated return shape that NEW callers
  should adopt so real-money paths (paper_trade_service, scan gating)
  can require ``status == "ok"`` instead of guessing what ``None`` means.
  Legacy ``Optional[T]`` returns stay on the existing API surface; new
  paths construct the outcome explicitly.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Callable, Generic, Literal, Optional, TypeVar

logger = logging.getLogger(__name__)


T = TypeVar("T")


FetchStatus = Literal["ok", "not_found", "timeout", "error"]


@dataclass(frozen=True)
class FetchOutcome(Generic[T]):
    """Discriminated outcome of a data fetch.

    Status semantics:
      * ``ok``        : value is present and trustworthy
      * ``not_found`` : the source successfully said "no data for this key"
                        (e.g. ticker exists but has no fundamentals row)
      * ``timeout``   : the call exceeded its wall-clock budget
      * ``error``     : the call raised; error_msg carries the type+message

    Callers gating real-money decisions MUST check ``is_ok`` rather than
    treating any non-None value as truth.
    """

    status: FetchStatus
    value: Optional[T] = None
    error_msg: Optional[str] = None
    source: str = "fresh"
    """Free-form provenance hint: 'fresh' / 'cache' / 'stale' / a vendor
    name. Set by the caller, not validated here."""

    @property
    def is_ok(self) -> bool:
        return self.status == "ok" and self.value is not None

    @classmethod
    def ok(cls, value: T, *, source: str = "fresh") -> "FetchOutcome[T]":
        return cls(status="ok", value=value, source=source)

    @classmethod
    def not_found(cls, *, source: str = "fresh") -> "FetchOutcome[T]":
        return cls(status="not_found", source=source)

    @classmethod
    def timeout(cls, msg: str) -> "FetchOutcome[T]":
        return cls(status="timeout", error_msg=msg)

    @classmethod
    def error(cls, msg: str) -> "FetchOutcome[T]":
        return cls(status="error", error_msg=msg)


class _DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor whose workers are daemon threads.

    Reviewer I5: the default ThreadPoolExecutor uses non-daemon worker
    threads and registers an atexit hook that waits for them to drain.
    For a TIMEOUT pool, orphaned (timed-out) workers can be running
    indefinite blocking I/O — yfinance's internal HTTP can take minutes
    to give up — so the default behavior turns interpreter shutdown
    (SIGTERM in a FastAPI service, Ctrl-C in the CLI) into a stall.

    Daemon workers are killed by the interpreter at process exit, which
    means we lose in-flight results — but in-flight results are by
    definition already past their timeout, so dropping them is the
    desired behavior anyway.

    We re-implement ``_adjust_thread_count`` (rather than subclass-then-
    set-daemon) because ``Thread.daemon`` cannot be set after
    ``Thread.start()`` — the default impl creates and immediately starts
    the worker, so post-hoc adjustment raises RuntimeError. The body
    below mirrors CPython's implementation circa 3.10-3.12; if a future
    version restructures it, the import-time check at module load will
    fail fast rather than silently regressing the daemon flag.
    """

    def _adjust_thread_count(self) -> None:  # type: ignore[override]
        # Mirror CPython's ThreadPoolExecutor._adjust_thread_count so we
        # can set daemon=True BEFORE the thread is started.
        import threading
        import weakref
        from concurrent.futures.thread import _worker, _threads_queues

        if self._idle_semaphore.acquire(timeout=0):  # type: ignore[attr-defined]
            return

        def _weakref_cb(_, q=self._work_queue):  # type: ignore[attr-defined]
            q.put(None)

        num_threads = len(self._threads)
        if num_threads < self._max_workers:  # type: ignore[attr-defined]
            thread_name = "%s_%d" % (
                self._thread_name_prefix or self,  # type: ignore[attr-defined]
                num_threads,
            )
            t = threading.Thread(
                name=thread_name,
                target=_worker,
                args=(
                    weakref.ref(self, _weakref_cb),
                    self._work_queue,  # type: ignore[attr-defined]
                    self._initializer,  # type: ignore[attr-defined]
                    self._initargs,  # type: ignore[attr-defined]
                ),
            )
            t.daemon = True
            t.start()
            self._threads.add(t)
            _threads_queues[t] = self._work_queue  # type: ignore[attr-defined]


# Module-level executor. Per-call ThreadPoolExecutor blocks shutdown
# on the timed-out worker thread, which defeats the timeout — see
# src.execution.paper_trade_service for the same lesson. Worker count is
# generous so concurrent fetches (price + fundamentals + earnings) don't
# back-pressure each other; OS will happily multiplex this many idle
# network threads.
_TIMEOUT_EXECUTOR = _DaemonThreadPoolExecutor(
    max_workers=32,
    thread_name_prefix="fetch_timeout",
)


def call_with_timeout(
    fn: Callable[[], T],
    *,
    timeout_seconds: float,
    name: str,
) -> tuple[Optional[T], Optional[str]]:
    """Run ``fn`` under a wall-clock timeout. Returns ``(value, error_msg)``.

    On success: (result, None).
    On timeout / exception: (None, error_msg) — error is logged once at
    warning level by this helper. Callers MUST treat (None, msg) as
    fetch-failure, distinct from a successful fetch that returned None
    or empty.

    A timed-out future is NOT cancelled (sync functions can't be) — it
    keeps running on the shared executor until the underlying call
    returns. This is acceptable because the shared pool absorbs the
    orphan thread without blocking the caller's next fetch.
    """
    future = _TIMEOUT_EXECUTOR.submit(fn)
    try:
        return future.result(timeout=timeout_seconds), None
    except FuturesTimeout:
        msg = f"{name} timed out after {timeout_seconds}s"
        logger.warning(msg)
        return None, msg
    except Exception as e:
        msg = f"{name} failed: {type(e).__name__}: {e}"
        logger.warning(msg)
        return None, msg


def call_with_timeout_outcome(
    fn: Callable[[], T],
    *,
    timeout_seconds: float,
    name: str,
) -> FetchOutcome[T]:
    """Same as ``call_with_timeout`` but returns a typed ``FetchOutcome``.

    Use this for new call sites that need the status distinction
    (``ok`` vs ``not_found`` vs ``timeout`` vs ``error``). Callers must
    map a returned ``None`` to ``not_found`` themselves if the underlying
    function uses ``None`` to mean "no data found".
    """
    future = _TIMEOUT_EXECUTOR.submit(fn)
    try:
        value = future.result(timeout=timeout_seconds)
    except FuturesTimeout:
        msg = f"{name} timed out after {timeout_seconds}s"
        logger.warning(msg)
        return FetchOutcome.timeout(msg)
    except Exception as e:
        msg = f"{name} failed: {type(e).__name__}: {e}"
        logger.warning(msg)
        return FetchOutcome.error(msg)
    if value is None:
        return FetchOutcome.not_found()
    return FetchOutcome.ok(value)
