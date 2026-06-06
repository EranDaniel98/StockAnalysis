"""/api/market — broader-market regime + macro indicators."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends

from src.api.dependencies import get_config
from src.api.routers.news import compute_market_news
from src.api.schemas.market import MarketOutlook, MarketRegime
from src.api.schemas.sectors import SectorsResponse
from src.api.services.market_outlook import (
    INDEX_PROXIES,
    build_outlook,
    fetch_prepost,
)
from src.api.services.market_regime import compute_regime_sync
from src.api.services.sectors import compute_sectors_sync
from src.config_loader import Config

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/regime", response_model=MarketRegime)
async def get_regime(config: Config = Depends(get_config)) -> MarketRegime:
    """Current market-regime snapshot.

    Reads SPY + VIX recent history (via the DataFetcher cache, so subsequent
    calls within market-hours TTL are free), computes SMA200 + recent VIX
    average, and returns a bull/bear/chop label plus the raw inputs the UI
    needs to render context.
    """
    return await asyncio.to_thread(compute_regime_sync, config)


@router.get("/sectors", response_model=SectorsResponse)
async def get_sectors(config: Config = Depends(get_config)) -> SectorsResponse:
    """Per-sector momentum snapshot via the SPDR Select Sector ETFs.

    Returns trailing 1-/5-/21-day total return for each sector ETF plus a
    50-day-SMA trend flag. UI renders this as a colored tile grid.
    """
    return await asyncio.to_thread(compute_sectors_sync, config)


@router.get("/outlook", response_model=MarketOutlook)
async def get_outlook(config: Config = Depends(get_config)) -> MarketOutlook:
    """Directional 'lean' read — a transparent tally of trend, VIX, news
    sentiment, and SPY after-hours drift into risk-on / neutral / risk-off,
    with the pre/post-market moves behind it. Conditions, not a forecast
    (the caveat ships in the payload).

    Runs the three inputs concurrently: regime (SPY/VIX) and pre/post (Polygon
    extended-hours) off the thread pool, news off the shared 5-min cache.
    """
    regime, news, (session_date, prepost) = await asyncio.gather(
        asyncio.to_thread(compute_regime_sync, config),
        compute_market_news(config),
        asyncio.to_thread(fetch_prepost, INDEX_PROXIES),
    )
    return build_outlook(regime, news.sentiment_counts, session_date, prepost)
