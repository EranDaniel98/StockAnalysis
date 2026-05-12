"""Phase 6 observability surface.

``configure_logging()`` is the only public entry point. Call it once at
process start (the FastAPI lifespan does this for the API process; CLI
scripts call it from ``main()`` if they want structured logs).
"""

from src.observability.logging import bind_request_id, configure_logging

__all__ = ["configure_logging", "bind_request_id"]
