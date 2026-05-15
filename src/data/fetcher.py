"""
Price data fetcher - downloads OHLCV data from yfinance with caching.

yfinance does not expose a per-call timeout, so every fetch is wrapped
in src.data.fetch_outcome.call_with_timeout. Tier-1 audit #8.
"""

import yfinance as yf
import pandas as pd
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from src.data.fetch_outcome import call_with_timeout

logger = logging.getLogger(__name__)

# Wall-clock budget per yfinance call. History is the slowest endpoint
# (10y of daily bars ~ 2500 rows), so it gets the longest leash. Snapshot
# endpoints are tight — a healthy fast_info round-trip is <500ms.
_HISTORY_TIMEOUT_SECONDS = 30.0
_REALTIME_TIMEOUT_SECONDS = 5.0


class DataFetcher:
    def __init__(self, config, cache):
        self.config = config
        self.cache = cache
        self.history_years = config.get("data", "history_years", default=5)
        self.interval = config.get("data", "interval", default="1d")
        self.max_workers = max(1, int(config.get("data", "max_concurrent_downloads", default=10)))

    def fetch_price_data(self, ticker, period=None, interval=None):
        """
        Fetch OHLCV data for a single ticker.
        Returns a pandas DataFrame or None on failure.
        """
        if interval is None:
            interval = self.interval
        if period is None:
            period = f"{self.history_years}y"

        cache_key = f"price_{ticker}_{period}_{interval}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            try:
                df = pd.DataFrame(cached)
                df.index = pd.to_datetime(df.index, utc=True)
                for col in ["Open", "High", "Low", "Close", "Volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                return df
            except Exception:
                pass

        df, err = call_with_timeout(
            lambda: yf.Ticker(ticker).history(period=period, interval=interval),
            timeout_seconds=_HISTORY_TIMEOUT_SECONDS,
            name=f"yf.history({ticker})",
        )
        if err is not None:
            # Timeout or exception. call_with_timeout already logged at
            # warning level; do not log again. Return None for back-compat
            # with existing callers that check `is not None`.
            return None
        if df is None or df.empty:
            logger.warning(f"No price data returned for {ticker}")
            return None

        df.columns = [c.strip() for c in df.columns]

        cache_data = df.copy()
        cache_data.index = cache_data.index.astype(str)
        self.cache.set(cache_key, cache_data.to_dict())

        return df

    def fetch_batch(self, tickers, period=None, interval=None):
        """
        Fetch price data for multiple tickers in parallel.
        Returns dict of {ticker: DataFrame}.
        """
        results = {}
        total = len(tickers)
        if total == 0:
            return results

        workers = min(self.max_workers, total)
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold]Price data[/bold]"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("{task.fields[ticker]}"),
            transient=True,
        ) as progress:
            task = progress.add_task("fetching", total=total, ticker="")
            with ThreadPoolExecutor(max_workers=workers) as ex:
                future_to_ticker = {
                    ex.submit(self.fetch_price_data, t, period, interval): t
                    for t in tickers
                }
                for fut in as_completed(future_to_ticker):
                    ticker = future_to_ticker[fut]
                    progress.update(task, ticker=ticker)
                    try:
                        df = fut.result()
                    except Exception as e:
                        logger.error(f"Worker error for {ticker}: {e}")
                        df = None
                    if df is not None and not df.empty:
                        results[ticker] = df
                    progress.advance(task)

        logger.info(f"Fetched price data for {len(results)}/{total} tickers (workers={workers})")
        return results

    def fetch_realtime_price(self, ticker):
        """
        Fetch the latest real-time (or near real-time) price info.
        Wrapped with a 5s wall-clock timeout (audit Tier-1 #8) so a hung
        TCP connection can't tie up the worker for minutes.
        """
        def _pull():
            info = yf.Ticker(ticker).fast_info
            return {
                "last_price": getattr(info, "last_price", None),
                "previous_close": getattr(info, "previous_close", None),
                "open": getattr(info, "open", None),
                "day_high": getattr(info, "day_high", None),
                "day_low": getattr(info, "day_low", None),
                "last_volume": getattr(info, "last_volume", None),
                "market_cap": getattr(info, "market_cap", None),
            }
        result, err = call_with_timeout(
            _pull,
            timeout_seconds=_REALTIME_TIMEOUT_SECONDS,
            name=f"yf.fast_info({ticker})",
        )
        # call_with_timeout already logs; on failure we just propagate None
        # so existing callers (which check `is not None`) keep working.
        return result if err is None else None

    def fetch_realtime_batch(self, tickers):
        """Fetch realtime prices for multiple tickers in parallel."""
        results = {}
        if not tickers:
            return results
        workers = min(self.max_workers, len(tickers))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            future_to_ticker = {ex.submit(self.fetch_realtime_price, t): t for t in tickers}
            for fut in as_completed(future_to_ticker):
                ticker = future_to_ticker[fut]
                try:
                    rt = fut.result()
                except Exception as e:
                    logger.error(f"Realtime worker error for {ticker}: {e}")
                    rt = None
                if rt:
                    results[ticker] = rt
        return results

    def fetch_intraday(self, ticker, period="1d", interval="5m"):
        """Fetch intraday data for short-term analysis."""
        return self.fetch_price_data(ticker, period=period, interval=interval)
