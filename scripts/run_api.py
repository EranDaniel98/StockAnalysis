"""Dev launcher for the FastAPI app.

Usage:
    uv run python -m scripts.run_api                # default 127.0.0.1:8000
    uv run python -m scripts.run_api --reload       # auto-reload on file changes

Reads STOCKNEW_API_* env vars (see src/api/settings.py).
"""

from __future__ import annotations

import argparse

import uvicorn

from src.api.settings import ApiSettings


def main() -> None:
    settings = ApiSettings()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--reload", action="store_true", default=settings.reload)
    parser.add_argument("--log-level", default=settings.log_level)
    args = parser.parse_args()

    uvicorn.run(
        "src.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
