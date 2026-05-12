"""/api/market — broader-market regime + macro indicators."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends

from src.api.dependencies import get_config
from src.api.schemas.market import MarketRegime
from src.api.services.market_regime import compute_regime_sync
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
