"""FastAPI surface for StockNew.

Phase 1 wraps the existing service layer (src/scoring, src/research, src/execution,
src/portfolio) in async HTTP endpoints. Heavy synchronous compute is offloaded via
asyncio.to_thread; Phase 4 will push async all the way down.
"""

from src.api.main import create_app

__all__ = ["create_app"]
