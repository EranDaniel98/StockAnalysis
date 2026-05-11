"""Cache repository protocol — used by Redis adapter (Stream C) and the
in-memory test double."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class CacheRepository(Protocol):
    """Key/value cache with market-aware TTL.

    Concrete implementation: src/cache/redis_adapter.py:RedisCacheRepository.
    """

    async def get(self, key: str) -> bytes | None:
        """Return raw bytes for the key, or None on miss or expiry.
        Serialization is the caller's concern (orjson / pyarrow / etc.)."""
        ...

    async def set(self, key: str, value: bytes, ttl_seconds: int | None = None) -> None:
        """Set with optional explicit TTL. When omitted, the adapter consults
        the TTL policy (market-aware: 5min open / 24h closed)."""
        ...

    async def delete(self, key: str) -> None:
        ...

    async def exists(self, key: str) -> bool:
        ...


@runtime_checkable
class TTLPolicy(Protocol):
    """Decides the TTL for a cache key based on its semantic class
    (price / fundamentals / screener) and the current market state."""

    def ttl_seconds_for(self, key: str) -> int:
        """Return TTL in seconds. Implementation defaults: 5min during market
        hours and 24h when closed for price+intraday keys; 24h always for
        fundamentals; 24h always for screener results."""
        ...
