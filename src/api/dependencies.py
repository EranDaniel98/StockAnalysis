"""Shared FastAPI dependencies.

Singletons live on `app.state` (set in the lifespan); request-scoped objects
(db session) are yielded per-request.
"""

from __future__ import annotations

from functools import lru_cache
from typing import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.cache.redis_adapter import RedisCacheRepository
from src.config_loader import Config
from src.db.session import get_sessionmaker
from src.storage.parquet_ohlcv import ParquetPriceRepository


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Process-wide Config singleton. YAML + .env load is non-trivial; cache it."""
    return Config()


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Per-request async session bound to the app's sessionmaker."""
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


def get_redis(request: Request) -> RedisCacheRepository:
    return request.app.state.redis


def get_price_repo(request: Request) -> ParquetPriceRepository:
    return request.app.state.price_repo


__all__ = [
    "get_config",
    "get_db_session",
    "get_redis",
    "get_price_repo",
    "Depends",
]
