"""Thin wrapper around the existing sync scan pipeline.

The full scan flow (discover → fundamentals → prices → analyze → score →
recommend) lives in src/main.py:cmd_scan. That function couples the compute
to Rich console output. This module re-implements the compute half without
the console, so the API can serve a typed result.

`on_event` is an optional callback for progress reporting. It fires from the
worker thread, so SSE callers must use loop.call_soon_threadsafe to bridge
back to the asyncio loop (see src/api/routers/stream.py).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from src.data.cache import DataCache
from src.data.fetcher import DataFetcher
from src.data.fundamentals import FundamentalsFetcher
from src.data.screener import StockScreener

logger = logging.getLogger(__name__)


ScanEvent = dict[str, Any]
EventCallback = Callable[[ScanEvent], None]


def _noop(_: ScanEvent) -> None:
    pass


def run_scan_sync(
    config,
    strategy: dict,
    *,
    theme: str | None = None,
    sector: str | None = None,
    fresh: bool = False,
    live_signals: bool = True,
    on_event: EventCallback | None = None,
) -> list[dict[str, Any]]:
    """Run a market scan and return ranked recommendation dicts.

    Intentionally sync — wraps the existing pipeline modules (which are sync,
    sometimes CPU-heavy, sometimes I/O via yfinance). Call from an async
    handler via asyncio.to_thread.

    ``live_signals`` controls whether the two yfinance-backed live-only
    analyzers fire: ``analyst_revisions`` (upgrades/downgrades) and
    ``options_skew`` (IV-derived put/call sentiment). Fetching them adds
    roughly 0.5-2s per ticker, parallelized across worker pools. Disable
    for fast iteration; leave on for production scans so the sub-score
    breakdown is complete.

    When ``on_event`` is supplied, emits stage events:
      - ``discover_start``                        scan begins
      - ``discover_done`` {n}                     post-screener ticker count
      - ``fundamentals_start``
      - ``fundamentals_done`` {n}
      - ``stage2_done`` {n}                       fundamentals-filtered count
      - ``prices_start``
      - ``prices_done`` {n}
      - ``analyst_revisions_start`` / ``analyst_revisions_done`` {n_covered}
      - ``options_chains_start`` / ``options_chains_done`` {n_covered}
      - ``analyze_start`` {n}                     analyzer pipeline begins
      - ``score_done`` {n}                        ranked recommendations ready

    Per-ticker analyzer events flow through from ``analyze_and_score``.
    """
    emit = on_event or _noop

    emit({"stage": "discover_start"})
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
    emit({"stage": "discover_done", "n": len(tickers)})

    if not tickers:
        return []

    emit({"stage": "fundamentals_start"})
    fundamentals_map = fund_fetcher.fetch_batch(tickers)
    emit({"stage": "fundamentals_done", "n": len(fundamentals_map)})

    filtered = screener.stage2_filter(tickers, fundamentals_map)
    emit({"stage": "stage2_done", "n": len(filtered)})
    if not filtered:
        return []

    emit({"stage": "prices_start"})
    price_data_map = fetcher.fetch_batch(filtered)
    emit({"stage": "prices_done", "n": len(price_data_map)})
    if not price_data_map:
        return []

    scored_tickers = list(price_data_map.keys())
    analyst_revisions_data: dict[str, list] | None = None
    options_chains: dict[str, Any] | None = None

    if live_signals and scored_tickers:
        # yfinance-backed; both fetchers have internal worker pools and
        # swallow per-ticker failures, so a flaky symbol won't sink the run.
        from src.market_data.analyst_revisions_yf.fetcher import (
            fetch_revisions_batch,
        )
        from src.market_data.options_chains_yf.fetcher import fetch_chains_batch

        emit({"stage": "analyst_revisions_start", "n": len(scored_tickers)})
        try:
            analyst_revisions_data = fetch_revisions_batch(scored_tickers)
        except Exception as e:
            logger.warning("analyst_revisions batch fetch failed: %s", e)
            analyst_revisions_data = {}
        emit(
            {
                "stage": "analyst_revisions_done",
                "n": sum(1 for v in (analyst_revisions_data or {}).values() if v),
            }
        )

        emit({"stage": "options_chains_start", "n": len(scored_tickers)})
        try:
            options_chains = fetch_chains_batch(scored_tickers)
        except Exception as e:
            logger.warning("options_chains batch fetch failed: %s", e)
            options_chains = {}
        emit(
            {
                "stage": "options_chains_done",
                "n": len(options_chains or {}),
            }
        )

    emit({"stage": "analyze_start", "n": len(price_data_map)})

    # Shared bounded-context implementation; the CLI calls the same function
    # with a console-printing on_event. Per-ticker events flow through to
    # the SSE caller.
    from src.scoring.service import analyze_and_score

    results = analyze_and_score(
        price_data_map,
        fundamentals_map,
        config,
        strategy,
        analyst_revisions_data=analyst_revisions_data,
        options_chains=options_chains,
        on_event=emit,
    )
    emit({"stage": "score_done", "n": len(results)})
    return results
