"""HTTP middleware.

So far one entry: ``RequestIdMiddleware``. Honors an incoming
``X-Request-ID`` header (preserve cross-system correlation when the
client is, say, a CLI script that wants its own ID), otherwise mints
a UUID. Binds the ID to structlog contextvars so every log line from
the request handler carries it.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.observability.logging import bind_request_id, clear_request_context

HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Bind X-Request-ID to logging context for the lifetime of the request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(HEADER) or request.headers.get(HEADER.lower())
        request_id = bind_request_id(incoming)
        try:
            response = await call_next(request)
        finally:
            # Clear *after* call_next so any error logging during the
            # handler still has the ID. The structlog contextvars are
            # task-local; explicit clear matters when uvicorn reuses
            # the same task for back-to-back requests.
            clear_request_context()
        response.headers[HEADER] = request_id
        return response
