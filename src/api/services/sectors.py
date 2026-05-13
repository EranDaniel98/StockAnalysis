"""Sector rotation snapshot.

Uses State Street's Select Sector SPDRs as the sector proxy — they're the
de-facto reference in retail-quant research because they cap-weight the
S&P 500 components per GICS sector. Computes trailing 1-/5-/21-day total
returns plus a simple trend flag (last close above 50-day SMA).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from src.api.schemas.sectors import SectorMetric, SectorsResponse
from src.data.cache import DataCache
from src.data.fetcher import DataFetcher

logger = logging.getLogger(__name__)


# (ticker, display name). Order is the canonical XLK-first list in research.
SECTOR_ETFS: list[tuple[str, str]] = [
    ("XLK", "Technology"),
    ("XLC", "Communication"),
    ("XLY", "Consumer Cyclical"),
    ("XLP", "Consumer Defensive"),
    ("XLV", "Healthcare"),
    ("XLF", "Financial"),
    ("XLI", "Industrials"),
    ("XLE", "Energy"),
    ("XLB", "Materials"),
    ("XLU", "Utilities"),
    ("XLRE", "Real Estate"),
]


def _trailing_return(close: pd.Series, days: int) -> float | None:
    s = close.dropna()
    if len(s) <= days:
        return None
    return float(s.iloc[-1] / s.iloc[-days - 1] - 1) * 100


def compute_sectors_sync(config) -> SectorsResponse:
    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5
        ),
        force_fresh=False,
    )
    fetcher = DataFetcher(config, cache)

    tickers = [t for t, _ in SECTOR_ETFS]
    history = fetcher.fetch_batch(tickers, period="6mo")

    rows: list[SectorMetric] = []
    for ticker, name in SECTOR_ETFS:
        df = history.get(ticker)
        if df is None or df.empty or "Close" not in df.columns:
            rows.append(SectorMetric(ticker=ticker, name=name))
            continue
        close = df["Close"]
        last = float(close.iloc[-1])
        sma50 = float(close.rolling(50, min_periods=50).mean().iloc[-1]) if len(close) >= 50 else None
        # 30-day sparkline series — percent-from-start so all sectors render
        # on the same vertical scale regardless of absolute ETF price.
        history_30d_pct: list[float] = []
        tail = close.dropna().tail(30)
        if len(tail) >= 5:
            base = float(tail.iloc[0])
            if base > 0:
                history_30d_pct = [float(v / base - 1) * 100 for v in tail]
        rows.append(
            SectorMetric(
                ticker=ticker,
                name=name,
                last_close=last,
                sma50=sma50,
                above_sma50=last > sma50 if sma50 else None,
                return_1d_pct=_trailing_return(close, 1),
                return_5d_pct=_trailing_return(close, 5),
                return_21d_pct=_trailing_return(close, 21),
                history_30d_pct=history_30d_pct,
            )
        )

    return SectorsResponse(as_of=datetime.now(timezone.utc), sectors=rows)
