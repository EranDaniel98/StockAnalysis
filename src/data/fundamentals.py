"""
Fundamental data fetcher - downloads financial metrics from yfinance.
"""

import yfinance as yf
import time
import logging

logger = logging.getLogger(__name__)


class FundamentalsFetcher:
    def __init__(self, config, cache):
        self.config = config
        self.cache = cache
        self.delay = config.get("data", "request_delay_seconds", default=0.5)

    def fetch(self, ticker):
        """
        Fetch fundamental data for a ticker.
        Returns a dict of financial metrics, or None on failure.
        """
        cache_key = f"fundamentals_{ticker}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            stock = yf.Ticker(ticker)
            info = stock.info

            if not info or info.get("trailingPE") is None and info.get("sector") is None:
                logger.warning(f"No fundamental data for {ticker}")
                return None

            fundamentals = {
                # Identification
                "ticker": ticker,
                "name": info.get("longName") or info.get("shortName", ticker),
                "sector": info.get("sector", "Unknown"),
                "industry": info.get("industry", "Unknown"),
                "description": info.get("longBusinessSummary", ""),

                # Valuation
                "market_cap": info.get("marketCap"),
                "pe_trailing": info.get("trailingPE"),
                "pe_forward": info.get("forwardPE"),
                "peg_ratio": info.get("pegRatio"),
                "pb_ratio": info.get("priceToBook"),
                "ps_ratio": info.get("priceToSalesTrailing12Months"),
                "ev_to_ebitda": info.get("enterpriseToEbitda"),

                # Growth
                "revenue_growth": info.get("revenueGrowth"),
                "earnings_growth": info.get("earningsGrowth"),
                "earnings_quarterly_growth": info.get("earningsQuarterlyGrowth"),

                # Profitability
                "profit_margin": info.get("profitMargins"),
                "operating_margin": info.get("operatingMargins"),
                "roe": info.get("returnOnEquity"),
                "roa": info.get("returnOnAssets"),
                "gross_margins": info.get("grossMargins"),

                # Financial Health
                "debt_to_equity": info.get("debtToEquity"),
                "current_ratio": info.get("currentRatio"),
                "quick_ratio": info.get("quickRatio"),
                "free_cash_flow": info.get("freeCashflow"),
                "total_cash": info.get("totalCash"),
                "total_debt": info.get("totalDebt"),

                # Dividends
                "dividend_yield": info.get("dividendYield"),
                "dividend_rate": info.get("dividendRate"),
                "payout_ratio": info.get("payoutRatio"),
                "ex_dividend_date": info.get("exDividendDate"),

                # Trading Info
                "avg_volume": info.get("averageVolume"),
                "avg_volume_10d": info.get("averageDailyVolume10Day"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                "fifty_day_avg": info.get("fiftyDayAverage"),
                "two_hundred_day_avg": info.get("twoHundredDayAverage"),
                "beta": info.get("beta"),

                # Analyst
                "target_mean_price": info.get("targetMeanPrice"),
                "target_high_price": info.get("targetHighPrice"),
                "target_low_price": info.get("targetLowPrice"),
                "recommendation": info.get("recommendationKey"),
                "num_analyst_opinions": info.get("numberOfAnalystOpinions"),
            }

            self.cache.set(cache_key, fundamentals)
            time.sleep(self.delay)
            return fundamentals

        except Exception as e:
            logger.error(f"Error fetching fundamentals for {ticker}: {e}")
            return None

    def fetch_batch(self, tickers):
        """Fetch fundamentals for multiple tickers."""
        results = {}
        total = len(tickers)
        for i, ticker in enumerate(tickers, 1):
            logger.info(f"Fetching fundamentals [{i}/{total}]: {ticker}")
            data = self.fetch(ticker)
            if data is not None:
                results[ticker] = data
        logger.info(f"Fetched fundamentals for {len(results)}/{total} tickers")
        return results

    def passes_filters(self, fundamentals):
        """
        Check if a stock passes the fundamental filters from config.
        Returns (passes: bool, reasons: list of failed filters).
        """
        filters = self.config.get("fundamental_filters", default={})
        reasons = []

        checks = [
            ("pe_trailing", "max_pe_ratio", "<=", "P/E too high"),
            ("pe_trailing", "min_pe_ratio", ">=", "Negative earnings"),
            ("peg_ratio", "max_peg_ratio", "<=", "PEG too high"),
            ("debt_to_equity", "max_debt_to_equity", "<=", "Debt too high"),
            ("current_ratio", "min_current_ratio", ">=", "Current ratio too low"),
        ]

        for metric_key, filter_key, op, reason in checks:
            value = fundamentals.get(metric_key)
            threshold = filters.get(filter_key)
            if value is None or threshold is None:
                continue
            if op == "<=" and value > threshold:
                reasons.append(f"{reason}: {value:.2f} > {threshold}")
            elif op == ">=" and value < threshold:
                reasons.append(f"{reason}: {value:.2f} < {threshold}")

        # Percentage-based checks (stored as decimals in yfinance)
        pct_checks = [
            ("revenue_growth", "min_revenue_growth_pct", "Revenue growth too low"),
            ("roe", "min_roe_pct", "ROE too low"),
            ("profit_margin", "min_profit_margin_pct", "Profit margin too low"),
        ]

        for metric_key, filter_key, reason in pct_checks:
            value = fundamentals.get(metric_key)
            threshold = filters.get(filter_key)
            if value is None or threshold is None:
                continue
            # yfinance returns decimals (0.10 = 10%), config is in percent
            if value * 100 < threshold:
                reasons.append(f"{reason}: {value*100:.1f}% < {threshold}%")

        return len(reasons) == 0, reasons
