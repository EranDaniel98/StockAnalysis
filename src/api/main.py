"""FastAPI app factory + lifespan.

Lifespan owns the long-lived singletons:
  - SQLAlchemy async sessionmaker
  - Redis client
  - Parquet PriceRepository
  - Config

Routers are mounted under `/api/`. Health probe sits at `/health` (unprefixed
so reverse proxies can ping without rewriting paths).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.dependencies import get_config
from src.api.routers import (
    analytics,
    backtests,
    diagnostics,
    health,
    market,
    ml,
    portfolio,
    recommendations,
    research,
    scans,
    stream,
    trades,
)
from src.api.services.live_prices import LivePriceBus
from src.api.services.trade_updates import TradeUpdatesBus
from src.api.settings import ApiSettings
from src.cache.redis_adapter import RedisCacheRepository
from src.db.session import dispose_engine, get_sessionmaker
from src.research_agent.event_monitor import EventMonitor
from src.storage.parquet_ohlcv import ParquetPriceRepository

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Wire singletons on app start; dispose on shutdown."""
    app.state.config = get_config()
    app.state.sessionmaker = get_sessionmaker()
    app.state.redis = RedisCacheRepository()
    app.state.price_repo = ParquetPriceRepository()
    app.state.live_prices = LivePriceBus()
    app.state.trade_updates = TradeUpdatesBus()
    # Background filing-event monitor — long-running poll task.
    # Disabled at construction by STOCKNEW_EVENT_MONITOR=0 if the user
    # doesn't want EDGAR polling on every API process start.
    monitor = EventMonitor(
        sessionmaker=app.state.sessionmaker,
        config=app.state.config,
    )
    app.state.event_monitor = monitor
    if _event_monitor_enabled():
        monitor.start()
    logger.info(
        "API singletons wired (config + db sessionmaker + redis + parquet "
        "+ live_prices + trade_updates + event_monitor)"
    )

    try:
        yield
    finally:
        await monitor.stop()
        await app.state.trade_updates.close()
        await app.state.live_prices.close()
        await app.state.redis.close()
        await dispose_engine()
        logger.info("API singletons torn down")


def _event_monitor_enabled() -> bool:
    """Off-switch via env so tests and one-off uvicorn runs can skip
    the background poll loop. Default on."""
    import os

    val = os.environ.get("STOCKNEW_EVENT_MONITOR", "1").strip().lower()
    return val not in ("0", "false", "no", "off")


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    settings = settings or ApiSettings()

    app = FastAPI(
        title="StockNew API",
        version="0.1.0",
        description="Local async API surface over the StockNew quant platform.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
    app.include_router(scans.router, prefix="/api/scans", tags=["scans"])
    app.include_router(backtests.router, prefix="/api/backtests", tags=["backtests"])
    app.include_router(
        diagnostics.router, prefix="/api/diagnostics", tags=["diagnostics"]
    )
    app.include_router(
        recommendations.router,
        prefix="/api/recommendations",
        tags=["recommendations"],
    )
    app.include_router(stream.router, prefix="/api/stream", tags=["stream"])
    app.include_router(market.router, prefix="/api/market", tags=["market"])
    app.include_router(
        analytics.router, prefix="/api/analytics", tags=["analytics"]
    )
    app.include_router(trades.router, prefix="/api/trades", tags=["trades"])
    app.include_router(ml.router, prefix="/api/ml", tags=["ml"])
    app.include_router(research.router, prefix="/api/research", tags=["research"])

    return app


app = create_app()
