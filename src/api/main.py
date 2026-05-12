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
    backtests,
    diagnostics,
    health,
    market,
    portfolio,
    recommendations,
    scans,
    stream,
)
from src.api.services.live_prices import LivePriceBus
from src.api.settings import ApiSettings
from src.cache.redis_adapter import RedisCacheRepository
from src.db.session import dispose_engine, get_sessionmaker
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
    logger.info(
        "API singletons wired (config + db sessionmaker + redis + parquet + live_prices)"
    )

    try:
        yield
    finally:
        await app.state.live_prices.close()
        await app.state.redis.close()
        await dispose_engine()
        logger.info("API singletons torn down")


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

    return app


app = create_app()
