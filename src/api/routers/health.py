"""Liveness + readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db_session, get_redis
from src.cache.redis_adapter import RedisCacheRepository

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Cheap liveness check — process is up and serving."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(
    db: AsyncSession = Depends(get_db_session),
    redis: RedisCacheRepository = Depends(get_redis),
) -> dict[str, str]:
    """Readiness check — verifies Postgres + Redis are reachable.

    Returns 200 only when both adapters round-trip. Use this from a deploy
    health probe; use /health for fast process-alive checks.
    """
    await db.execute(text("SELECT 1"))
    await redis.set("stocknew:api:readiness", b"ok", ttl_seconds=10)
    return {"status": "ready", "db": "ok", "redis": "ok"}
