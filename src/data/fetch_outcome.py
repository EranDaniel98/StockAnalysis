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


# Module-level executor. Per-call ThreadPoolExecutor blocks shutdown
# on the timed-out worker thread, which defeats the timeout — see
# src.execution.paper_trade_service for the same lesson. Worker count is
# generous so concurrent fetches (price + fundamentals + earnings) don't
# back-pressure each other; OS will happily multiplex this many idle
# network threads.
_TIMEOUT_EXECUTOR = ThreadPoolExecutor(
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
