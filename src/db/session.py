"""Async SQLAlchemy 2.0 session manager.

Provides:
  - engine + sessionmaker for FastAPI (async, asyncpg driver)
  - sync wrapper for the CLI shim during Phase 0 (CLI is sync; we wrap
    async repository calls with asyncio.run at the CLI boundary)

DSN is read from STOCKNEW_DATABASE_URL env var. Default points at the local
docker compose Postgres instance (postgresql+asyncpg://stocknew:stocknew_dev
@localhost:5432/stocknew).
"""

from __future__ import annotations

import os
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

DEFAULT_DSN = "postgresql+asyncpg://stocknew:stocknew_dev@localhost:5432/stocknew"


def get_dsn() -> str:
    """Resolve the database DSN. Override via STOCKNEW_DATABASE_URL."""
    return os.environ.get("STOCKNEW_DATABASE_URL", DEFAULT_DSN)


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy 2.0 models in src/db/models.py."""


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Lazily build the async engine. Single-process singleton."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_dsn(),
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Use as: `db: AsyncSession = Depends(get_session)`."""
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    """Tear down the engine. Call at process shutdown."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None
