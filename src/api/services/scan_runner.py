"""Thin wrapper around the existing sync scan pipeline.

The full scan flow (discover → fundamentals → prices → analyze → score →
recommend) lives in src/main.py:cmd_scan. That function couples the compute
to Rich console output. This module re-implements the compute half without
the console, so the API can serve a typed result.

When Stream B's CLI carve completes (cmd_scan → src/cli/main.py), this can
share a single ScanService class with both surfaces.
"""

from __future__ import annotations

import logging
from typing import Any

from src.data.cache import DataCache
from src.data.fetcher import DataFetcher
from src.data.fundamentals import FundamentalsFetcher
from src.data.screener import StockScreener

logger = logging.getLogger(__name__)


def run_scan_sync(
    config,
    strategy: dict,
    *,
    theme: str | None = None,
    sector: str | None = None,
    fresh: bool = False,
) -> list[dict[str, Any]]:
    """Run a market scan and return ranked recommendation dicts.

    Intentionally sync — wraps the existing pipeline modules (which are sync,
    sometimes CPU-heavy, sometimes I/O via yfinance). Call from an async
    handler via asyncio.to_thread.

    Returns the legacy recommendation dict shape so the response model
    ScanResultItem can validate it directly. Length may be 0 if no tickers
    pass stage-2 fundamentals filtering.
    """
    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5
        ),
        force_fresh=fresh,
    )
    screener = StockScreener(config, cache)
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    if theme:
        tickers = screener.discover(theme_filter=theme)
    elif sector:
        tickers = screener.discover(sector_filter=sector)
    else:
        tickers = screener.discover_by_sectors()

    if not tickers:
        return []

    fundamentals_map = fund_fetcher.fetch_batch(tickers)
    filtered = screener.stage2_filter(tickers, fundamentals_map)
    if not filtered:
        return []

    price_data_map = fetcher.fetch_batch(filtered)
    if not price_data_map:
        return []

    # Reuse _analyze_and_score so behavior stays in lockstep with cmd_scan.
    # Acceptable Phase 1 coupling — the CLI carve removes this import boundary
    # when src/main.py moves under src/cli/.
    from src.main import _analyze_and_score

    return _analyze_and_score(price_data_map, fundamentals_map, config, strategy)
