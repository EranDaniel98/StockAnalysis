"""Market-aware TTL policy.

Lifted verbatim from the original src/data/cache.py:18-50, 93-102 so behavior
is identical. The plan called for a verbatim port — same DST math, same
expiry rules, same key-prefix routing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# US Eastern Time offset (UTC-5, UTC-4 during DST).
# Approximate DST — for exact rules, swap in zoneinfo. The original code
# uses this approximation and the parity test must agree, so we keep it.
_ET_OFFSET_STANDARD = timedelta(hours=-5)
_ET_OFFSET_DST = timedelta(hours=-4)


def _get_et_now() -> datetime:
    """Current time in US Eastern, approximate DST handling. Verbatim port
    from src/data/cache.py:_get_et_now."""
    utc_now = datetime.now(timezone.utc)
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


def is_market_open() -> bool:
    """Mon-Fri 9:30 ET to 16:00 ET. Does NOT account for holidays.
    Verbatim port from src/data/cache.py:is_market_open."""
    et_now = _get_et_now()
    if et_now.weekday() > 4:
        return False
    market_open = et_now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = et_now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= et_now <= market_close


# Default TTLs (seconds), tuned to match the original DataCache defaults.
DEFAULT_MARKET_OPEN_TTL = 5 * 60       # 5 minutes
DEFAULT_MARKET_CLOSED_TTL = 24 * 3600  # 24 hours


class MarketAwareTTLPolicy:
    """Implements src.contracts.protocols.cache.TTLPolicy.

    Routing rules (preserved from DataCache._get_expiry_seconds):
      - keys starting with 'screener_' or 'fundamentals_' → always 24h
        (these change quarterly / on a slow cycle, no benefit to short TTL)
      - all other keys (notably 'price_*' and 'realtime_*') → 5min when
        market is open, 24h when closed
    """

    def __init__(
        self,
        market_open_ttl: int = DEFAULT_MARKET_OPEN_TTL,
        market_closed_ttl: int = DEFAULT_MARKET_CLOSED_TTL,
    ) -> None:
        self._market_open_ttl = market_open_ttl
        self._market_closed_ttl = market_closed_ttl

    def ttl_seconds_for(self, key: str) -> int:
        if key.startswith(("screener_", "fundamentals_")):
            return self._market_closed_ttl
        if is_market_open():
            return self._market_open_ttl
        return self._market_closed_ttl
