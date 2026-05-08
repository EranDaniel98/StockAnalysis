"""
SQLite-based data cache with market-hours awareness.
Uses short expiry during market hours (prices change constantly)
and longer expiry after close (prices are final).
"""

import sqlite3
import json
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# US Eastern Time offset (UTC-5, UTC-4 during DST)
# We approximate — for exact DST handling, use pytz/zoneinfo if available
_ET_OFFSET_STANDARD = timedelta(hours=-5)
_ET_OFFSET_DST = timedelta(hours=-4)


def _get_et_now():
    """Get current time in US Eastern (approximate DST handling)."""
    utc_now = datetime.now(timezone.utc)
    # DST roughly: second Sunday in March to first Sunday in November
    month = utc_now.month
    if 3 < month < 11:
        offset = _ET_OFFSET_DST
    elif month == 3:
        offset = _ET_OFFSET_DST if utc_now.day >= 10 else _ET_OFFSET_STANDARD
    elif month == 11:
        offset = _ET_OFFSET_STANDARD if utc_now.day >= 3 else _ET_OFFSET_DST
    else:
        offset = _ET_OFFSET_STANDARD
    return utc_now + offset


def is_market_open():
    """
    Check if the US stock market is likely open right now.
    Market hours: Mon-Fri, 9:30 AM - 4:00 PM Eastern.
    Does NOT account for holidays.
    """
    et_now = _get_et_now()
    # Weekday: Monday=0 ... Friday=4
    if et_now.weekday() > 4:
        return False
    market_open = et_now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = et_now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= et_now <= market_close


class DataCache:
    def __init__(
        self,
        db_path=None,
        expiry_hours=24,
        market_hours_expiry_minutes=5,
        force_fresh=False,
    ):
        """
        Args:
            db_path: Path to SQLite database file
            expiry_hours: Cache expiry when market is CLOSED (default: 24h)
            market_hours_expiry_minutes: Cache expiry when market is OPEN (default: 5min)
            force_fresh: If True, always bypass cache reads (still writes for next time)
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "data" / "cache.db"
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(db_path)
        self.expiry_closed = expiry_hours * 3600
        self.expiry_open = market_hours_expiry_minutes * 60
        self.force_fresh = force_fresh
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cache_timestamp ON cache(timestamp)"
            )

    def _get_expiry_seconds(self, key=""):
        """Return the appropriate expiry based on market hours and data type."""
        # Screener results and fundamentals change slowly — always use long expiry
        if key.startswith("screener_") or key.startswith("fundamentals_"):
            return self.expiry_closed

        # Price data: short expiry if market is open
        if is_market_open():
            return self.expiry_open
        return self.expiry_closed

    def get(self, key):
        """Retrieve a cached value if it exists and hasn't expired."""
        if self.force_fresh:
            logger.debug(f"Cache bypassed (--fresh): {key}")
            return None

        expiry = self._get_expiry_seconds(key)

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value, timestamp FROM cache WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            value, ts = row
            age = time.time() - ts
            if age > expiry:
                age_str = f"{age/60:.0f}min" if age < 3600 else f"{age/3600:.1f}h"
                logger.debug(f"Cache expired ({age_str} old): {key}")
                return None
            logger.debug(f"Cache hit: {key}")
            return json.loads(value)

    def set(self, key, value):
        """Store a value in the cache."""
        serialized = json.dumps(value, default=str)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache (key, value, timestamp) VALUES (?, ?, ?)",
                (key, serialized, time.time()),
            )
        logger.debug(f"Cached key: {key}")

    def delete(self, key):
        """Delete a specific cache entry."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))

    def clear(self):
        """Clear all cached data."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM cache")
        logger.info("Cache cleared")

    def clear_expired(self):
        """Remove only expired entries."""
        # Use the shorter expiry for cleanup
        cutoff = time.time() - self.expiry_open
        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute(
                "DELETE FROM cache WHERE timestamp < ?", (cutoff,)
            )
            logger.info(f"Cleared {result.rowcount} expired cache entries")

    def get_stats(self):
        """Return cache statistics."""
        market_open = is_market_open()
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            # Count valid price entries using market-aware expiry
            price_expiry = self.expiry_open if market_open else self.expiry_closed
            price_cutoff = time.time() - price_expiry
            valid_prices = conn.execute(
                "SELECT COUNT(*) FROM cache WHERE timestamp >= ? AND key LIKE 'price_%'",
                (price_cutoff,),
            ).fetchone()[0]
            # Count valid non-price entries using long expiry
            other_cutoff = time.time() - self.expiry_closed
            valid_other = conn.execute(
                "SELECT COUNT(*) FROM cache WHERE timestamp >= ? AND key NOT LIKE 'price_%'",
                (other_cutoff,),
            ).fetchone()[0]
            return {
                "total_entries": total,
                "valid_entries": valid_prices + valid_other,
                "expired_entries": total - (valid_prices + valid_other),
                "market_open": market_open,
                "price_cache_expiry": f"{price_expiry/60:.0f} min",
            }
