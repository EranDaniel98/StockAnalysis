"""Typed cache-key builders.

Same key shapes as the legacy SQLite cache so the parity test compares
hit-rate apples to apples. Each helper returns a plain str — no namespacing,
no hashing — so it round-trips with the migration script.

Original key formats observed in src/data/cache.py call sites:
  price_{TICKER}_{PERIOD}_{INTERVAL}     e.g. price_AAPL_5y_1d
  fundamentals_{TICKER}                  e.g. fundamentals_AAPL
  screener_{METHOD}_{SECTOR}             e.g. screener_finviz_technology
  realtime_{TICKER}                      (never cached — listed for completeness)
"""

from __future__ import annotations


def price_key(ticker: str, period: str = "5y", interval: str = "1d") -> str:
    return f"price_{ticker}_{period}_{interval}"


def fundamentals_key(ticker: str) -> str:
    return f"fundamentals_{ticker}"


def screener_key(method: str, sector: str | None = None) -> str:
    sector_part = sector or "all"
    return f"screener_{method}_{sector_part}"


def realtime_key(ticker: str) -> str:
    """Realtime quotes are NOT cached today — included here for callers that
    want to assert the absence of a key. The TTL policy returns 5min for
    these but src/data/fetcher.py:fetch_realtime_price short-circuits the
    cache layer entirely."""
    return f"realtime_{ticker}"
