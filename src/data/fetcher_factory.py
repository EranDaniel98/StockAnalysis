"""Selects the OHLCV fetcher implementation from config ``data.source``.

Default ``"yfinance"`` keeps legacy behavior; ``"polygon"`` routes to the
deterministic, delisting-inclusive PolygonDataFetcher. Both implement the same
interface, so callers swap transparently — flip the flag in config/settings.yaml.

Index symbols (``^VIX``) transparently fall back to yfinance inside
PolygonDataFetcher (Polygon's I:VIX is Indices-tier, not on the $29 Stocks plan),
so the regime/VIX gates keep working regardless of source.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def get_data_fetcher(config=None, cache=None):
    source = (config.get("data", "source", default="yfinance")
              if config is not None else "yfinance")
    if str(source).lower() == "polygon":
        from src.data.polygon_fetcher import PolygonDataFetcher

        logger.info("OHLCV source = polygon (deterministic, delisting-inclusive)")
        return PolygonDataFetcher(config, cache)
    from src.data.fetcher import DataFetcher

    return DataFetcher(config, cache)
