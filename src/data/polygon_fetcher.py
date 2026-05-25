"""Polygon-backed drop-in for src.data.fetcher.DataFetcher.

Mirrors DataFetcher's method signatures so it can be swapped in behind a
``data.source`` factory (Phase B) with no caller changes. Returns the same
canonical OHLCV frame, but **deterministic** and **delisting-inclusive** —
the whole point of the migration (kills the yfinance ±0.4 Sharpe envelope).

Frames are naive-UTC (storage + momentum convention). ``config`` and ``cache``
are optional so the adapter is usable standalone (parity harness, scripts).

Out of scope (documented in project memory project_polygon_data_migration):
  * ^VIX — Polygon's I:VIX is Indices-plan, not $29 Stocks. Keep VIX on yfinance.
  * Real-time for execution — Alpaca stays authoritative; Polygon $29 is 15-min
    delayed, so fetch_realtime_* here is display-grade only.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from src.market_data.polygon import PolygonClient, PolygonError, bars_to_frame

logger = logging.getLogger(__name__)


class PolygonDataFetcher:
    def __init__(self, config=None, cache=None, *, client: PolygonClient | None = None):
        self.config = config
        self.cache = cache
        self.client = client or PolygonClient()
        self.history_years = self._cfg("history_years", 5)
        self.interval = self._cfg("interval", "1d")
        self.max_workers = max(1, int(self._cfg("max_concurrent_downloads", 10)))

    def _cfg(self, key, default):
        return self.config.get("data", key, default=default) if self.config is not None else default

    def fetch_price_data(self, ticker, period=None, interval=None, *, adjusted: bool = True):
        """OHLCV for one ticker. adjusted=True (split/div-adjusted) for factors;
        pass adjusted=False for raw prints. Returns DataFrame or None on miss."""
        interval = interval or self.interval
        period = period or f"{self.history_years}y"
        multiplier, timespan = _interval_to_polygon(interval)
        start, end = _period_to_range(period)

        cache_key = f"polygon_{ticker}_{period}_{interval}_{'adj' if adjusted else 'raw'}"
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                df = pd.DataFrame(cached)
                df.index = pd.to_datetime(df.index)
                return df

        try:
            bars = self.client.aggregates(ticker, start, end, timespan=timespan,
                                           multiplier=multiplier, adjusted=adjusted)
        except PolygonError as e:
            logger.warning("polygon fetch failed for %s: %s", ticker, e)
            return None
        df = bars_to_frame(bars, daily=(timespan == "day"))
        if df.empty:
            return None
        if self.cache is not None:
            cache_data = df.copy()
            cache_data.index = cache_data.index.astype(str)
            self.cache.set(cache_key, cache_data.to_dict())
        return df

    def fetch_batch(self, tickers, period=None, interval=None, *, adjusted: bool = True):
        """Parallel multi-ticker fetch. Returns {ticker: DataFrame} (misses dropped)."""
        results: dict[str, pd.DataFrame] = {}
        if not tickers:
            return results
        workers = min(self.max_workers, len(tickers))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(self.fetch_price_data, t, period, interval, adjusted=adjusted): t
                    for t in tickers}
            for fut in as_completed(futs):
                t = futs[fut]
                try:
                    df = fut.result()
                except Exception as e:
                    logger.error("polygon worker error for %s: %s", t, e)
                    df = None
                if df is not None and not df.empty:
                    results[t] = df
        logger.info("polygon fetched %d/%d tickers (workers=%d)", len(results), len(tickers), workers)
        return results

    def fetch_intraday(self, ticker, period="1d", interval="5m"):
        """Intraday bars — raw prints (adjusted=False), microstructure-faithful."""
        return self.fetch_price_data(ticker, period=period, interval=interval, adjusted=False)

    def fetch_realtime_price(self, ticker):
        """Latest close (15-min delayed on $29). Display-grade ONLY — execution
        and stop-loss stay on Alpaca. Returns dict matching the legacy shape."""
        df = self.fetch_price_data(ticker, period="5d", interval="1d", adjusted=False)
        if df is None or df.empty:
            return None
        last = df.iloc[-1]
        return {"last_price": float(last["Close"]), "previous_close": None,
                "open": float(last["Open"]), "day_high": float(last["High"]),
                "day_low": float(last["Low"]), "last_volume": float(last["Volume"]),
                "market_cap": None}

    def fetch_realtime_batch(self, tickers):
        out = {}
        for t in tickers or []:
            rt = self.fetch_realtime_price(t)
            if rt:
                out[t] = rt
        return out


def _period_to_range(period: str):
    """yfinance period vocabulary ('5y','6mo','2y','60d') -> (start, end) Timestamps."""
    today = pd.Timestamp.today().normalize()
    m = re.fullmatch(r"(\d+)(d|wk|mo|y)", str(period).strip())
    if not m:
        return today - pd.DateOffset(years=5), today
    n, unit = int(m.group(1)), m.group(2)
    start = {"d": lambda: today - pd.Timedelta(days=n),
             "wk": lambda: today - pd.Timedelta(weeks=n),
             "mo": lambda: today - pd.DateOffset(months=n),
             "y": lambda: today - pd.DateOffset(years=n)}[unit]()
    return start, today


def _interval_to_polygon(interval: str):
    """yfinance interval ('1d','5m','1h','1wk') -> (multiplier, timespan)."""
    m = re.fullmatch(r"(\d+)?(m|h|d|wk|mo)", str(interval).strip())
    if not m:
        return 1, "day"
    n = int(m.group(1) or 1)
    return n, {"m": "minute", "h": "hour", "d": "day", "wk": "week", "mo": "month"}[m.group(2)]
