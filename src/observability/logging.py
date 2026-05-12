"""structlog setup for StockNew.

Two output sinks:

  - stderr: human-readable colorized when running interactively, falls
    back to plain JSON if stderr isn't a TTY (the prod-style path).
  - logs/stocknew.jsonl: rotating JSON-lines file. Default 10MB × 5
    rolls so the disk footprint stays bounded.

stdlib ``logging`` is wrapped so third-party libraries (httpx, alembic,
SQLAlchemy) flow through structlog renderers unchanged. We're not
swapping the logging library wholesale — that would mean rewriting
every ``logger.info`` call in the project.

Overrides via env:
  - ``STOCKNEW_LOG_FORMAT``  : ``auto`` (default), ``json``, or ``console``
  - ``STOCKNEW_LOG_LEVEL``   : ``DEBUG``, ``INFO`` (default), ``WARNING``…
  - ``STOCKNEW_LOG_FILE``    : path; pass ``""`` to disable file output
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

# Library loggers that flood INFO with handshake / connection lifecycle
# noise. Keep them at WARNING unless the user explicitly raises the global
# level — the events that matter (errors) are still emitted.
_NOISY_LOGGERS = {
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "sqlalchemy.engine": logging.WARNING,
    "sqlalchemy.pool": logging.WARNING,
    "alembic.runtime.migration": logging.INFO,
    "watchfiles": logging.WARNING,
    "asyncio": logging.WARNING,
    "alpaca.common.websocket": logging.WARNING,
}


_configured = False


def configure_logging(
    *,
    level: Optional[str] = None,
    fmt: Optional[str] = None,
    log_file: Optional[str] = None,
) -> None:
    """Idempotent. Call once at process start.

    Re-calling is a no-op so importing the module from a test fixture
    that already configured logging doesn't double-wrap stderr.
    """
    global _configured
    if _configured:
        return

    resolved_level = (level or os.environ.get("STOCKNEW_LOG_LEVEL") or "INFO").upper()
    resolved_fmt = (fmt or os.environ.get("STOCKNEW_LOG_FORMAT") or "auto").lower()
    resolved_file = (
        log_file if log_file is not None else os.environ.get("STOCKNEW_LOG_FILE")
    )
    if resolved_file is None:
        # Default file location relative to repo root. CLI scripts running
        # from elsewhere will get the absolute path right since logs/ lives
        # alongside src/ in the working dir.
        resolved_file = "logs/stocknew.jsonl"

    # ─── shared structlog processor chain ─────────────────────────────
    # Order matters: contextvars first so request_id/scan_run_id ride
    # along with every event from the same logical operation.
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        # ``ExtraAdder`` surfaces logger.info("...", extra={...}) keys —
        # third-party libraries set these for free.
        structlog.stdlib.ExtraAdder(),
    ]

    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(resolved_level)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    use_console = resolved_fmt == "console" or (
        resolved_fmt == "auto" and sys.stderr.isatty()
    )
    stderr_renderer: Any
    if use_console:
        stderr_renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        stderr_renderer = structlog.processors.JSONRenderer()

    stderr_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            stderr_renderer,
        ],
    )

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(stderr_formatter)

    root = logging.getLogger()
    # Wipe any handlers a prior configure_logging() or basicConfig() set up
    # so re-runs (e.g. test sessions) don't double-emit.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(stderr_handler)
    root.setLevel(resolved_level)

    # File sink — JSON always, regardless of stderr format, because that's
    # what downstream parsers (Loki, jq, grep -E) expect.
    if resolved_file:
        file_path = Path(resolved_file)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            file_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=shared_processors,
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.JSONRenderer(),
                ],
            )
        )
        root.addHandler(file_handler)

    for name, lvl in _NOISY_LOGGERS.items():
        logging.getLogger(name).setLevel(lvl)

    _configured = True


def bind_request_id(request_id: Optional[str] = None) -> str:
    """Bind a request_id to the structlog contextvars so every event in
    the current asyncio task / thread carries it.

    Returns the resolved ID — caller can echo it back to the client in
    an ``X-Request-ID`` response header.
    """
    rid = request_id or uuid.uuid4().hex
    bind_contextvars(request_id=rid)
    return rid


def clear_request_context() -> None:
    """Tear down the per-request context. The middleware calls this in
    the response phase so the next request starts fresh."""
    clear_contextvars()
