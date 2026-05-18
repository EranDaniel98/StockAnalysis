"""yfinance-backed sector cache for the factor pipeline.

The EDGAR PIT loader (``src/scoring/fundamentals_pit_loader.py``) carries a
``sector`` field on every snapshot — but the ingest path never populates
it, so every row reads ``sector=None``. The sector-cap selector in the
factor pipeline then buckets every ticker as "Unknown" and the cap binds
on a single bucket, evicting most of the top decile.

This module fixes the gap by reading sectors from ``yf.Ticker(t).info``
(same source the OLD analyzer pipeline uses) and caching them to disk
so repeated runs don't hit yfinance per call. Sectors rarely change —
weekly refresh is plenty.

Schema of the cache file (``data/cache/sectors.json``)::

    {
      "AAPL": {"sector": "Technology", "industry": "Consumer Electronics",
                "fetched_at": "2026-05-18"},
      "OXY":  {"sector": "Energy",     "industry": "Oil & Gas E&P",
                "fetched_at": "2026-05-18"}
    }

Returned ``get_sectors`` is a flat ``ticker -> sector_string`` mapping.
Tickers with no data return ``None`` from ``lookup_sector`` and bucket
as "Unknown" downstream — same posture as before, but now only for
the rare ticker yfinance can't classify, not the whole universe.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = Path("data/cache/sectors.json")
# Sectors change extremely rarely (M&A, spin-offs). 30 days is generous;
# bring it down if you spot a stale label.
DEFAULT_TTL_DAYS = 30


def _load_cache_file(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            logger.warning("Sector cache at %s is not a dict; ignoring", path)
            return {}
        return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read sector cache at %s: %s", path, exc)
        return {}


def _save_cache_file(path: Path, data: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True),
                    encoding="utf-8")


def _is_fresh(row: dict, ttl_days: int) -> bool:
    fetched_at = row.get("fetched_at")
    if not fetched_at:
        return False
    try:
        d = date.fromisoformat(fetched_at)
    except (TypeError, ValueError):
        return False
    return (date.today() - d) <= timedelta(days=ttl_days)


def _fetch_one(ticker: str, timeout_seconds: float = 8.0) -> Optional[dict]:
    """Hit yfinance for one ticker. Returns None on any failure.

    Wrapped through ``call_with_timeout`` so a wedged yfinance request
    can't block the batch — the same pattern ``src/data/fundamentals.py``
    uses.
    """
    try:
        import yfinance as yf
        from src.data.fetcher import call_with_timeout
    except ImportError as exc:
        logger.warning("yfinance import failed: %s", exc)
        return None

    info, err = call_with_timeout(
        lambda: yf.Ticker(ticker).info,
        timeout_seconds=timeout_seconds,
        name=f"yf.info({ticker})",
    )
    if err is not None or not info:
        return None
    sector = info.get("sector")
    industry = info.get("industry")
    if not sector:
        return None
    return {"sector": str(sector), "industry": str(industry or "")}


def get_sectors(
    tickers: Iterable[str],
    *,
    cache_path: Path | str = DEFAULT_CACHE_PATH,
    ttl_days: int = DEFAULT_TTL_DAYS,
    refresh: bool = False,
    max_fetches: Optional[int] = None,
) -> dict[str, str]:
    """Return ``{ticker: sector}`` for as many tickers as possible.

    Read-through cache: a ticker with a fresh cached row skips the
    network. Stale or missing rows hit yfinance; the result is written
    back to disk for the next caller.

    ``refresh=True`` forces a re-fetch for every ticker (use sparingly;
    yfinance rate-limits aggressively at ~500 calls / 5 minutes).
    ``max_fetches`` caps the network calls per invocation so a cold-cache
    run inside a critical path can't stall the pipeline; remaining
    misses return None and re-attempt next call.
    """
    cache_path = Path(cache_path)
    cache = _load_cache_file(cache_path)
    out: dict[str, str] = {}
    pending: list[str] = []

    for t in tickers:
        t = t.upper()
        row = cache.get(t)
        if not refresh and row and _is_fresh(row, ttl_days):
            sector = row.get("sector")
            if sector:
                out[t] = sector
            continue
        pending.append(t)

    if not pending:
        return out

    today_iso = date.today().isoformat()
    fetched = 0
    for t in pending:
        if max_fetches is not None and fetched >= max_fetches:
            break
        info = _fetch_one(t)
        fetched += 1
        if info is None:
            # Don't pollute the cache with negative rows — re-attempt
            # next call. yfinance occasionally drops a ticker for one
            # request and serves it on the next.
            continue
        cache[t] = {
            "sector": info["sector"],
            "industry": info["industry"],
            "fetched_at": today_iso,
        }
        out[t] = info["sector"]

    if fetched > 0:
        _save_cache_file(cache_path, cache)
        logger.info(
            "Sector cache: fetched %d / %d misses (cache now %d rows)",
            fetched, len(pending), len(cache),
        )

    return out


def lookup_sector(
    ticker: str,
    *,
    cache_path: Path | str = DEFAULT_CACHE_PATH,
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> Optional[str]:
    """Single-ticker convenience wrapper. Returns None on cache miss
    + network failure."""
    sectors = get_sectors(
        [ticker], cache_path=cache_path, ttl_days=ttl_days, max_fetches=1,
    )
    return sectors.get(ticker.upper())


__all__ = [
    "get_sectors",
    "lookup_sector",
    "DEFAULT_CACHE_PATH",
    "DEFAULT_TTL_DAYS",
]
