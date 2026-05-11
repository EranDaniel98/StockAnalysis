"""Redis-backed cache adapter and TTL policy.

Concrete implementation of src.contracts.protocols.cache.CacheRepository.
Replaces src.data.cache.DataCache (SQLite key-value store) — same key shapes,
same market-aware TTL behavior.
"""

from src.cache.keys import (
    fundamentals_key,
    price_key,
    realtime_key,
    screener_key,
)
from src.cache.redis_adapter import RedisCacheRepository
from src.cache.ttl_policy import MarketAwareTTLPolicy, is_market_open

__all__ = [
    "MarketAwareTTLPolicy",
    "RedisCacheRepository",
    "fundamentals_key",
    "is_market_open",
    "price_key",
    "realtime_key",
    "screener_key",
]
