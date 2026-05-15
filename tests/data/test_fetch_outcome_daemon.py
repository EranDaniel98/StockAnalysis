"""Reviewer I5 regression: timeout-executor workers must be daemon threads.

The default ThreadPoolExecutor uses non-daemon workers and an atexit
hook that waits for them to drain. For a TIMEOUT pool, orphan workers
are by definition past their wall-clock budget but cannot be cancelled
(sync functions can't be interrupted) — so they keep running for
whatever yfinance's internal HTTP timeout is (minutes). Non-daemon
threads turn this into a SIGTERM stall on the FastAPI service.

Daemon workers are killed by the interpreter at process exit. We lose
in-flight orphan results, but those were already past their timeout,
so dropping them is the desired behavior.
"""

from __future__ import annotations

import time

from src.data.fetch_outcome import _TIMEOUT_EXECUTOR, call_with_timeout


def test_timeout_executor_workers_are_daemon():
    """Submit a no-op, force the pool to spin up a worker, then inspect
    the live threads to confirm daemon=True. Pre-fix the threads would
    be non-daemon (the default)."""
    # Ensure at least one worker is alive.
    fut = _TIMEOUT_EXECUTOR.submit(lambda: 42)
    assert fut.result(timeout=5) == 42

    threads = list(_TIMEOUT_EXECUTOR._threads)
    assert threads, "expected at least one live worker"
    for t in threads:
        assert t.daemon, (
            f"worker {t.name} is non-daemon — interpreter shutdown will "
            f"stall on this thread if it's running an orphan I/O call"
        )


def test_timeout_executor_returns_value_on_success():
    """Sanity: the daemon-pool subclass didn't break basic submit."""
    value, err = call_with_timeout(
        lambda: 7,
        timeout_seconds=1.0,
        name="trivial",
    )
    assert value == 7
    assert err is None


def test_timeout_executor_returns_timeout_msg_on_overrun():
    """The timeout path still fires (daemon flag doesn't interfere)."""
    def slow():
        time.sleep(2)
        return 1

    value, err = call_with_timeout(
        slow,
        timeout_seconds=0.1,
        name="slow-test",
    )
    assert value is None
    assert err is not None
    assert "timed out" in err
