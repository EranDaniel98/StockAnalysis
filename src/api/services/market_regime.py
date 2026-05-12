"""Compute the current market-regime snapshot.

Reads recent SPY + ^VIX history via the existing DataFetcher path, then
delegates the classification rule to ``src.market_data.regime`` so the
live snapshot and the backtest entry gate share a single rule. Sync;
call from async handlers via ``asyncio.to_thread``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from src.api.schemas.market import MarketRegime
from src.data.cache import DataCache
from src.data.fetcher import DataFetcher
from src.market_data.regime import RegimeParams, classify_at

logger = logging.getLogger(__name__)


def compute_regime_sync(config) -> MarketRegime:
    """Fetch SPY + VIX recent history, compute the regime snapshot."""
    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5
        ),
        force_fresh=False,
    )
    fetcher = DataFetcher(config, cache)

    rf = config.get_regime_filter()
    params = RegimeParams(
        sma_period=int(rf.get("sma_period", 200)),
        vix_low=float(rf.get("vix_low", 20.0)),
        vix_high=float(rf.get("vix_high", 25.0)),
    )

    # Need ``sma_period`` trading days for the SMA, so pull ~1.5y to be safe.
    bench = fetcher.fetch_batch(["SPY", "^VIX"], period="2y")
    spy = bench.get("SPY")
    vix = bench.get("^VIX")

    as_of = pd.Timestamp.utcnow().tz_localize(None)
    snap = classify_at(spy, vix, as_of, params)

    vix_avg = None
    if vix is not None and not vix.empty and "Close" in vix.columns:
        recent = vix["Close"].dropna().tail(20)
        if not recent.empty:
            vix_avg = float(recent.mean())

    return MarketRegime(
        as_of=datetime.now(timezone.utc),
        label=snap.label,
        spy_price=snap.spy_price,
        spy_sma200=snap.spy_sma,
        spy_above_sma200=snap.spy_above_sma,
        spy_pct_from_sma200=snap.spy_pct_from_sma,
        vix_level=snap.vix_level,
        vix_avg_20d=vix_avg,
        notes=snap.notes,
    )
