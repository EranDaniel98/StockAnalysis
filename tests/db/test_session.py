"""Engine-per-loop contract for sync wrappers.

Covers Tier-1 audit finding C#1/C#2/D#14/D#22: every sync wrapper that
calls into the async DB stack MUST dispose the global engine inside its
own asyncio.run, so the next sync caller starts with a fresh asyncpg
pool. Otherwise the global pool stays bound to the now-closed loop and
the next call hangs on Windows ProactorEventLoop.

These tests do not hit Postgres — they exercise the `run_with_dispose`
helper directly and verify dispose_engine fires regardless of whether
the wrapped coroutine succeeds or raises.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.db import session as session_mod
from src.db.session import run_with_dispose


# Patch dispose_engine with a real coroutine function (not a MagicMock
# returning a pre-built coroutine, which leaks "never awaited" warnings
# when the wrapper runs in a fresh loop). The list-append side-effect
# is the test signal — direct, no awaitable bookkeeping.

def _make_dispose_recorder():
    calls: list[None] = []

    async def _dispose():
        calls.append(None)

    return _dispose, calls


def test_run_with_dispose_returns_coroutine_value():
    dispose_fn, calls = _make_dispose_recorder()

    async def _coro():
        return "answer-42"

    with patch.object(session_mod, "dispose_engine", dispose_fn):
        result = run_with_dispose(_coro())

    assert result == "answer-42"
    assert len(calls) == 1


def test_run_with_dispose_disposes_even_when_coroutine_raises():
    """The whole point of the contract: a failed sync wrapper must NOT
    leave the engine bound to its dying loop. Otherwise the next sync
    caller hangs."""

    class _DomainError(RuntimeError):
        pass

    dispose_fn, calls = _make_dispose_recorder()

    async def _coro():
        raise _DomainError("downstream failure")

    with patch.object(session_mod, "dispose_engine", dispose_fn):
        with pytest.raises(_DomainError):
            run_with_dispose(_coro())

    assert len(calls) == 1


def test_run_with_dispose_disposes_once_per_call():
    """Two sequential sync wrappers in the same process must each get a
    fresh engine. We can't easily assert the asyncpg-pool binding from
    pytest, but the closest behavioural proxy is that dispose fires once
    per `run_with_dispose` call — that's the lever that breaks the
    loop/pool coupling."""

    dispose_fn, calls = _make_dispose_recorder()

    async def _coro_a():
        return "a"

    async def _coro_b():
        return "b"

    with patch.object(session_mod, "dispose_engine", dispose_fn):
        assert run_with_dispose(_coro_a()) == "a"
        assert run_with_dispose(_coro_b()) == "b"

    assert len(calls) == 2
