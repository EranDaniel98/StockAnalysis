"""RequestIdMiddleware contract tests.

Hits a one-route FastAPI app (no DB, no Alpaca, no event monitor) so the
test is deterministic and fast.
"""

from __future__ import annotations

import os
import re

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.api.middleware import HEADER, RequestIdMiddleware
from src.observability.logging import configure_logging


def _build_app() -> FastAPI:
    """Minimal app with the middleware + an echo route that returns the
    structlog-bound request_id so we can assert it matches the header."""
    # Force JSON to a tmp path so we don't pollute the project's logs/ during
    # the test run. STOCKNEW_LOG_FILE="" disables file output entirely.
    os.environ.setdefault("STOCKNEW_LOG_FILE", "")
    configure_logging()

    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/echo")
    def echo(request: Request):
        # Inspect the structlog contextvars directly — that's what the
        # middleware binds. The header is set in the response phase, so
        # we don't read it here.
        from structlog.contextvars import get_contextvars

        return get_contextvars()

    return app


def test_request_id_is_minted_when_missing() -> None:
    """No incoming header → server mints one, echoes it back."""
    app = _build_app()
    with TestClient(app) as c:
        resp = c.get("/echo")
    assert resp.status_code == 200
    header = resp.headers.get(HEADER)
    assert header is not None
    # UUID4 hex (32 lowercase hex chars).
    assert re.fullmatch(r"[0-9a-f]{32}", header)
    assert resp.json()["request_id"] == header


def test_request_id_is_preserved_when_provided() -> None:
    """Incoming X-Request-ID → server uses it verbatim and echoes it."""
    app = _build_app()
    custom = "my-shell-script-trace-1234"
    with TestClient(app) as c:
        resp = c.get("/echo", headers={HEADER: custom})
    assert resp.status_code == 200
    assert resp.headers.get(HEADER) == custom
    assert resp.json()["request_id"] == custom


def test_request_id_clears_between_requests() -> None:
    """The middleware's clear_contextvars() in finally means request N+1
    doesn't inherit request N's ID via stale task-local state."""
    app = _build_app()
    with TestClient(app) as c:
        r1 = c.get("/echo", headers={HEADER: "request-one"})
        r2 = c.get("/echo")
    assert r1.headers[HEADER] == "request-one"
    assert r2.headers[HEADER] != "request-one"
    assert r2.json()["request_id"] == r2.headers[HEADER]
