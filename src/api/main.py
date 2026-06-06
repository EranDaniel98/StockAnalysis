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
from src.api.middleware import RequestIdMiddleware
from src.api.routers import (
    briefing,
    dashboard,
    executions,
    factor_backtests,
    health,
    ic_reports,
    market,
    news,
    pipeline,
    portfolio,
    recommendations,
    research,
    scans,
    stocks,
    stream,
)
from src.api.services.live_prices import LivePriceBus
from src.api.services.trade_updates import TradeUpdatesBus
from src.api.settings import ApiSettings
from src.cache.redis_adapter import RedisCacheRepository
from src.db.session import dispose_engine, get_sessionmaker
from src.observability.logging import configure_logging
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
    logger.info(
        "API singletons wired (config + db sessionmaker + redis + parquet "
        "+ live_prices + trade_updates)"
    )

    try:
        yield
    finally:
        await app.state.trade_updates.close()
        await app.state.live_prices.close()
        await app.state.redis.close()
        await dispose_engine()
        logger.info("API singletons torn down")


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    settings = settings or ApiSettings()
    configure_logging()

    app = FastAPI(
        title="StockNew API",
        version="0.1.0",
        description="Local async API surface over the StockNew quant platform.",
        lifespan=lifespan,
    )

    # CORS comes first so OPTIONS preflights don't get a request_id
    # they can't echo back. Request-ID middleware runs on real requests.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex or None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestIdMiddleware)

    app.include_router(health.router)
    app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
    app.include_router(scans.router, prefix="/api/scans", tags=["scans"])
    app.include_router(stocks.router, prefix="/api/stocks", tags=["stocks"])
    app.include_router(
        recommendations.router,
        prefix="/api/recommendations",
        tags=["recommendations"],
    )
    app.include_router(stream.router, prefix="/api/stream", tags=["stream"])
    app.include_router(market.router, prefix="/api/market", tags=["market"])
    app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
    app.include_router(
        briefing.router, prefix="/api/dashboard/briefing", tags=["dashboard"],
    )
    app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])
    app.include_router(
        factor_backtests.router,
        prefix="/api/factor-backtests",
        tags=["factor-backtests"],
    )
    app.include_router(
        ic_reports.router,
        prefix="/api/ic-reports",
        tags=["ic-reports"],
    )
    app.include_router(
        executions.router,
        prefix="/api/executions",
        tags=["executions"],
    )
    app.include_router(
        research.router,
        prefix="/api/research",
        tags=["research"],
    )
    app.include_router(news.router, prefix="/api/news", tags=["news"])

    return app


app = create_app()
