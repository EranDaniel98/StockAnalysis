"""One-shot migration: data/cache.db (SQLite key-value cache) → Redis.

Preserves the original write timestamp so the TTL math stays correct: each
entry's remaining TTL is computed as (TTL_policy_for_key - age_in_seconds)
and written via SETEX. Entries already past their TTL are skipped.

Price entries with serialized DataFrames are pushed back to Redis as-is
(they're small JSON blobs in the source). Stream D will later replace
DataFrame storage with Parquet, but for Phase 0 parity we keep the existing
JSON-in-Redis behavior so the cache contents look identical to callers.

Usage:
    docker compose up -d                  # ensure Redis is running
    uv run python -m scripts.migrate_cache_to_redis
    uv run python -m scripts.migrate_cache_to_redis --dry-run   # count only
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
import sys
import time
from pathlib import Path

from src.cache.redis_adapter import RedisCacheRepository
from src.cache.ttl_policy import MarketAwareTTLPolicy

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate_cache_to_redis")


async def _run(source: Path, dry_run: bool) -> None:
    if not source.exists():
        logger.error("Source not found: %s", source)
        sys.exit(1)

    sqlite_conn = sqlite3.connect(str(source))
    sqlite_conn.row_factory = sqlite3.Row
    rows = sqlite_conn.execute("SELECT key, value, timestamp FROM cache").fetchall()
    logger.info("Source entries: %d", len(rows))

    if dry_run:
        # Bucket by key prefix for visibility
        buckets: dict[str, int] = {}
        for row in rows:
            prefix = row["key"].split("_", 1)[0]
            buckets[prefix] = buckets.get(prefix, 0) + 1
        for prefix, count in sorted(buckets.items()):
            logger.info("  %-12s %d", prefix, count)
        sqlite_conn.close()
        return

    repo = RedisCacheRepository()
    policy = MarketAwareTTLPolicy()
    now = time.time()
    migrated = 0
    expired = 0
    try:
        for row in rows:
            key = row["key"]
            value = row["value"]
            ts = row["timestamp"]
            age = now - ts

            policy_ttl = policy.ttl_seconds_for(key)
            remaining_ttl = int(policy_ttl - age)
            if remaining_ttl <= 0:
                expired += 1
                continue

            # value is TEXT in SQLite — encode to bytes for Redis storage
            payload = value.encode("utf-8") if isinstance(value, str) else value
            await repo.set(key, payload, ttl_seconds=remaining_ttl)
            migrated += 1
    finally:
        await repo.close()

    sqlite_conn.close()
    logger.info(
        "Migrated %d entries (skipped %d already-expired)", migrated, expired
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "cache.db",
        help="Path to source SQLite cache (default: data/cache.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count entries by prefix; do not write to Redis",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.source, args.dry_run))


if __name__ == "__main__":
    main()
