"""Redis-backed cache adapter.

Implements src.contracts.protocols.cache.CacheRepository. Uses redis-py's
asyncio API (built into redis>=4.2) with connection pooling.

Serialization is the caller's concern — this adapter stores bytes. Use
orjson for dict/list payloads; offload DataFrame OHLCV to Parquet (Stream D)
and store only the Parquet path in Redis.

Configuration via env:
  STOCKNEW_REDIS_URL   default: redis://localhost:6379/0
  STOCKNEW_REDIS_TIMEOUT_S  default: 2.0   (socket + command timeout)
"""

from __future__ import annotations

import os
from typing import Optional

from redis.asyncio import Redis, from_url

from src.cache.ttl_policy import MarketAwareTTLPolicy

DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
# 127.0.0.1 not localhost — Docker Desktop on Windows occasionally adds a
# DNS round trip for localhost that exceeds tight asyncio timeouts.
DEFAULT_TIMEOUT_S = 2.0


def get_redis_url() -> str:
    return os.environ.get("STOCKNEW_REDIS_URL", DEFAULT_REDIS_URL)


def get_redis_timeout() -> float:
    raw = os.environ.get("STOCKNEW_REDIS_TIMEOUT_S")
    if not raw:
        return DEFAULT_TIMEOUT_S
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_S


class RedisCacheRepository:
    """Implements src.contracts.protocols.cache.CacheRepository.

    Single shared connection pool per process. The redis-py client handles
    pool management internally; callers don't see the pool.

    Construction is cheap — the actual TCP connect happens lazily on first
    command. Use `await close()` (or `aclose()` on newer redis-py) for
    explicit shutdown.
    """

    def __init__(
        self,
        client: Optional[Redis] = None,
        ttl_policy: Optional[MarketAwareTTLPolicy] = None,
    ) -> None:
        if client is None:
            client = from_url(
                get_redis_url(),
                socket_timeout=get_redis_timeout(),
                socket_connect_timeout=get_redis_timeout(),
                decode_responses=False,  # we want raw bytes
            )
        self._client = client
        self._ttl_policy = ttl_policy or MarketAwareTTLPolicy()

    async def get(self, key: str) -> bytes | None:
        """Return raw bytes for the key, or None on miss or expiry.
        Redis handles expiry automatically — no manual TTL check needed."""
        return await self._client.get(key)

    async def set(
        self,
        key: str,
        value: bytes,
        ttl_seconds: int | None = None,
    ) -> None:
        """Set with explicit or policy-derived TTL.

        If ttl_seconds is None, consults the market-aware policy. Both forms
        use Redis EXPIRE under the hood — Redis will evict the key when the
        TTL elapses; no manual sweeping required.
        """
        if ttl_seconds is None:
            ttl_seconds = self._ttl_policy.ttl_seconds_for(key)
        await self._client.set(key, value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def exists(self, key: str) -> bool:
        # EXISTS returns int (number of keys present, 0 or 1 for a single arg)
        return bool(await self._client.exists(key))

    async def close(self) -> None:
        """Close the underlying connection pool. Call at process shutdown.
        Newer redis-py (>=5) prefers aclose; we provide both for compat."""
        try:
            await self._client.aclose()  # type: ignore[attr-defined]
        except AttributeError:
            await self._client.close()  # legacy
