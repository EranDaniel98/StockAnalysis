"""Compute the current market-regime snapshot.

Reads recent SPY + ^VIX history via the existing DataFetcher path, runs the
classification rule, and returns a typed ``MarketRegime``. Sync; call from
async handlers via ``asyncio.to_thread``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from src.api.schemas.market import MarketRegime, RegimeLabel
from src.data.cache import DataCache
from src.data.fetcher import DataFetcher

logger = logging.getLogger(__name__)


# Thresholds — kept inline because changing them is a market-regime decision,
# not a config knob. If you do want them tunable, lift to settings.yaml.
VIX_LOW = 20.0
VIX_HIGH = 25.0


def _last_valid(series: pd.Series) -> float | None:
    s = series.dropna()
    return float(s.iloc[-1]) if not s.empty else None


def _classify(
    spy_above_sma: bool | None, vix_level: float | None
) -> tuple[RegimeLabel, list[str]]:
    notes: list[str] = []
    if spy_above_sma is None or vix_level is None:
        notes.append("missing inputs — regime undetermined")
        return "unknown", notes

    if spy_above_sma and vix_level < VIX_LOW:
        notes.append(f"SPY > 200-SMA and VIX < {VIX_LOW} → risk-on")
        return "bull", notes
    if (not spy_above_sma) and vix_level > VIX_HIGH:
        notes.append(f"SPY < 200-SMA and VIX > {VIX_HIGH} → risk-off")
        return "bear", notes

    if spy_above_sma:
        notes.append(f"SPY above trend but VIX {vix_level:.1f} ≥ {VIX_LOW} → caution")
    else:
        notes.append(f"SPY below trend, VIX {vix_level:.1f} not panic yet → caution")
    return "chop", notes


def compute_regime_sync(config) -> MarketRegime:
    """Fetch SPY + VIX recent history, compute SMA200, classify regime."""
    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5
        ),
        force_fresh=False,
    )
    fetcher = DataFetcher(config, cache)

    # Need 200 trading days for the SMA, so pull ~1.5y to be safe.
    bench = fetcher.fetch_batch(["SPY", "^VIX"], period="2y")
    spy = bench.get("SPY")
    vix = bench.get("^VIX")

    spy_price = spy_sma200 = spy_pct = None
    spy_above = None
    if spy is not None and not spy.empty and "Close" in spy.columns:
        spy_price = _last_valid(spy["Close"])
        sma_series = spy["Close"].rolling(window=200, min_periods=200).mean()
        spy_sma200 = _last_valid(sma_series)
        if spy_price is not None and spy_sma200 is not None and spy_sma200 > 0:
            spy_above = spy_price > spy_sma200
            spy_pct = (spy_price / spy_sma200 - 1.0) * 100

    vix_level = vix_avg = None
    if vix is not None and not vix.empty and "Close" in vix.columns:
        vix_level = _last_valid(vix["Close"])
        recent = vix["Close"].dropna().tail(20)
        if not recent.empty:
            vix_avg = float(recent.mean())

    label, notes = _classify(spy_above, vix_level)

    return MarketRegime(
        as_of=datetime.now(timezone.utc),
        label=label,
        spy_price=spy_price,
        spy_sma200=spy_sma200,
        spy_above_sma200=spy_above,
        spy_pct_from_sma200=spy_pct,
        vix_level=vix_level,
        vix_avg_20d=vix_avg,
        notes=notes,
    )
