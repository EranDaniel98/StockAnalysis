"""
Price data fetcher - downloads OHLCV data from yfinance with caching.
"""

import yfinance as yf
import pandas as pd
import time
import logging

logger = logging.getLogger(__name__)


class DataFetcher:
    def __init__(self, config, cache):
        self.config = config
        self.cache = cache
        self.delay = config.get("data", "request_delay_seconds", default=0.5)
        self.history_years = config.get("data", "history_years", default=5)
        self.interval = config.get("data", "interval", default="1d")

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
                # Ensure numeric columns
                for col in ["Open", "High", "Low", "Close", "Volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                return df
            except Exception:
                pass

        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period=period, interval=interval)

            if df.empty:
                logger.warning(f"No price data returned for {ticker}")
                return None

            # Standardize column names
            df.columns = [c.strip() for c in df.columns]

            # Cache the data (convert to serializable format)
            cache_data = df.copy()
            cache_data.index = cache_data.index.astype(str)
            self.cache.set(cache_key, cache_data.to_dict())

            time.sleep(self.delay)
            return df

        except Exception as e:
            logger.error(f"Error fetching price data for {ticker}: {e}")
            return None

    def fetch_batch(self, tickers, period=None, interval=None):
        """
        Fetch price data for multiple tickers.
        Returns dict of {ticker: DataFrame}.
        """
        results = {}
        total = len(tickers)
        for i, ticker in enumerate(tickers, 1):
            logger.info(f"Fetching price data [{i}/{total}]: {ticker}")
            df = self.fetch_price_data(ticker, period=period, interval=interval)
            if df is not None and not df.empty:
                results[ticker] = df
        logger.info(f"Successfully fetched data for {len(results)}/{total} tickers")
        return results

    def fetch_realtime_price(self, ticker):
        """
        Fetch the latest real-time (or near real-time) price info.
        Uses 1-minute interval for most recent data.
        """
        try:
            stock = yf.Ticker(ticker)
            info = stock.fast_info
            return {
                "last_price": getattr(info, "last_price", None),
                "previous_close": getattr(info, "previous_close", None),
                "open": getattr(info, "open", None),
                "day_high": getattr(info, "day_high", None),
                "day_low": getattr(info, "day_low", None),
                "last_volume": getattr(info, "last_volume", None),
                "market_cap": getattr(info, "market_cap", None),
            }
        except Exception as e:
            logger.error(f"Error fetching real-time data for {ticker}: {e}")
            return None

    def fetch_intraday(self, ticker, period="1d", interval="5m"):
        """Fetch intraday data for short-term analysis."""
        return self.fetch_price_data(ticker, period=period, interval=interval)
