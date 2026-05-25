"""
Fundamental data fetcher - downloads financial metrics from yfinance.

`yf.Ticker.info` is the slowest yfinance endpoint (5-15s on a healthy
network) and has no timeout, so every call is wrapped in
src.data.fetch_outcome.call_with_timeout. Tier-1 audit #8.
"""

import sys
import yfinance as yf
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from src.data.fetch_outcome import call_with_timeout
from src.data.numeric import coerce_numeric as _coerce_numeric

# Rich Progress drives a Live thread that writes to stdout. Under
# uvicorn worker threads on Windows the LegacyWindowsTerm flush raises
# OSError [Errno 22] on exit (stdout isn't a real console there), and
# the exception propagates out of fetch_batch — crashing every API
# route that fetches fundamentals. Disable progress whenever stdout
# isn't a TTY so server contexts are unaffected.
_RICH_PROGRESS_DISABLED = not sys.stdout.isatty()

logger = logging.getLogger(__name__)

# 15s allows for a slow but healthy yfinance .info round-trip (vendor
# claims 5-15s typical). A hung connection past this gets cut so the
# worker pool doesn't drain on bad tickers.
_INFO_TIMEOUT_SECONDS = 15.0


class FundamentalsFetcher:
    def __init__(self, config, cache):
        self.config = config
        self.cache = cache
        self.max_workers = max(1, int(config.get("data", "max_concurrent_downloads", default=10)))

    def fetch(self, ticker):
        """
        Fetch fundamental data for a ticker.
        Returns a dict of financial metrics, or None on failure.
        """
        cache_key = f"fundamentals_{ticker}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        info, err = call_with_timeout(
            lambda: yf.Ticker(ticker).info,
            timeout_seconds=_INFO_TIMEOUT_SECONDS,
            name=f"yf.info({ticker})",
        )
        if err is not None:
            # Timeout or exception. call_with_timeout already logged.
            # Returning None loses the "fetch failed" vs "no data exists"
            # distinction; callers that need it should switch to the
            # FetchOutcome-returning shape in src.data.fetch_outcome.
            return None
        try:
            if not info:
                logger.warning(f"No fundamental data for {ticker}")
                return None

            # Both trailingPE and sector missing usually means yfinance
            # returned a stub (delisted ticker, ETF, fund). Don't return
            # the full dict in that case — but DO preserve the
            # identifying fields (name, longName) so the instrument
            # classifier downstream can detect leveraged / inverse /
            # daily ETFs that previously slipped through with name=ticker.
            if info.get("trailingPE") is None and info.get("sector") is None:
                long_name = info.get("longName") or info.get("shortName")
                if long_name:
                    logger.warning(
                        "No fundamental data for %s (name=%r) — returning "
                        "name-only stub so the instrument classifier can "
                        "still flag non-stock instruments.",
                        ticker, long_name,
                    )
                    return {
                        "ticker": ticker,
                        "name": long_name,
                        "sector": None,
                        "industry": None,
                        "market_cap": None,
                    }
                logger.warning(f"No fundamental data for {ticker}")
                return None

            # Every numeric field goes through _coerce_numeric so downstream
            # analyzers can rely on float-or-None semantics. yfinance
            # occasionally returns the string 'Infinity' for undefined P/E
            # (negative-earnings filers) and 'NaN' for missing values,
            # which previously crashed comparisons like ``pe > 0`` in
            # src/scoring/analyzers/fundamental.py. Discovered when BILL
            # tripped the new fail-loud score-error log on every Monday
            # from 2024-05-20 onward.
            fundamentals = {
                # Identification (always string)
                "ticker": ticker,
                "name": info.get("longName") or info.get("shortName", ticker),
                "sector": info.get("sector", "Unknown"),
                "industry": info.get("industry", "Unknown"),
                "description": info.get("longBusinessSummary", ""),

                # Valuation
                "market_cap": _coerce_numeric(info.get("marketCap")),
                "pe_trailing": _coerce_numeric(info.get("trailingPE")),
                "pe_forward": _coerce_numeric(info.get("forwardPE")),
                "peg_ratio": _coerce_numeric(info.get("pegRatio")),
                "pb_ratio": _coerce_numeric(info.get("priceToBook")),
                "ps_ratio": _coerce_numeric(info.get("priceToSalesTrailing12Months")),
                "ev_to_ebitda": _coerce_numeric(info.get("enterpriseToEbitda")),

                # Growth
                "revenue_growth": _coerce_numeric(info.get("revenueGrowth")),
                "earnings_growth": _coerce_numeric(info.get("earningsGrowth")),
                "earnings_quarterly_growth": _coerce_numeric(info.get("earningsQuarterlyGrowth")),

                # Profitability
                "profit_margin": _coerce_numeric(info.get("profitMargins")),
                "operating_margin": _coerce_numeric(info.get("operatingMargins")),
                "roe": _coerce_numeric(info.get("returnOnEquity")),
                "roa": _coerce_numeric(info.get("returnOnAssets")),
                "gross_margins": _coerce_numeric(info.get("grossMargins")),

                # Financial Health
                "debt_to_equity": _coerce_numeric(info.get("debtToEquity")),
                "current_ratio": _coerce_numeric(info.get("currentRatio")),
                "quick_ratio": _coerce_numeric(info.get("quickRatio")),
                "free_cash_flow": _coerce_numeric(info.get("freeCashflow")),
                "total_cash": _coerce_numeric(info.get("totalCash")),
                "total_debt": _coerce_numeric(info.get("totalDebt")),

                # Dividends
                "dividend_yield": _coerce_numeric(info.get("dividendYield")),
                "dividend_rate": _coerce_numeric(info.get("dividendRate")),
                "payout_ratio": _coerce_numeric(info.get("payoutRatio")),
                # ex_dividend_date is a unix epoch int from yfinance — also numeric
                "ex_dividend_date": _coerce_numeric(info.get("exDividendDate")),

                # Trading Info
                "avg_volume": _coerce_numeric(info.get("averageVolume")),
                "avg_volume_10d": _coerce_numeric(info.get("averageDailyVolume10Day")),
                "fifty_two_week_high": _coerce_numeric(info.get("fiftyTwoWeekHigh")),
                "fifty_two_week_low": _coerce_numeric(info.get("fiftyTwoWeekLow")),
                "fifty_day_avg": _coerce_numeric(info.get("fiftyDayAverage")),
                "two_hundred_day_avg": _coerce_numeric(info.get("twoHundredDayAverage")),
                "beta": _coerce_numeric(info.get("beta")),

                # Analyst
                "target_mean_price": _coerce_numeric(info.get("targetMeanPrice")),
                "target_high_price": _coerce_numeric(info.get("targetHighPrice")),
                "target_low_price": _coerce_numeric(info.get("targetLowPrice")),
                "recommendation": info.get("recommendationKey"),  # string label
                "num_analyst_opinions": _coerce_numeric(info.get("numberOfAnalystOpinions")),

                # Earnings calendar — UNIX EPOCH SECONDS, UTC.
                # earnings_announcement_ts: when the EPS/revenue release
                #   drops, typically 16:00 ET ("after market close").
                # earnings_call_ts: when the management Q&A conference
                #   call starts, typically 17:00 ET (one hour after the
                #   release). This is the call where forward guidance
                #   and analyst questions move the stock.
                # earnings_window_start/end: yfinance sometimes only
                #   knows the day range (e.g. "between Jul 28-Aug 1");
                #   when set, the FE should render "between X and Y"
                #   instead of a single timestamp.
                "earnings_announcement_ts": _coerce_numeric(
                    info.get("earningsTimestamp"),
                ),
                "earnings_call_ts": _coerce_numeric(
                    info.get("earningsCallTimestampStart"),
                ),
                "earnings_window_start": _coerce_numeric(
                    info.get("earningsTimestampStart"),
                ),
                "earnings_window_end": _coerce_numeric(
                    info.get("earningsTimestampEnd"),
                ),
            }

            self.cache.set(cache_key, fundamentals)
            return fundamentals

        except Exception as e:
            logger.error(f"Error fetching fundamentals for {ticker}: {e}")
            return None

    def fetch_batch(self, tickers):
        """
        Fetch fundamentals for multiple tickers in parallel.
        Returns dict of {ticker: fundamentals_dict}.
        """
        results = {}
        total = len(tickers)
        if total == 0:
            return results

        workers = min(self.max_workers, total)
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold]Fundamentals[/bold]"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("{task.fields[ticker]}"),
            transient=True,
            disable=_RICH_PROGRESS_DISABLED,
        ) as progress:
            task = progress.add_task("fetching", total=total, ticker="")
            with ThreadPoolExecutor(max_workers=workers) as ex:
                future_to_ticker = {ex.submit(self.fetch, t): t for t in tickers}
                for fut in as_completed(future_to_ticker):
                    ticker = future_to_ticker[fut]
                    progress.update(task, ticker=ticker)
                    try:
                        data = fut.result()
                    except Exception as e:
                        logger.error(f"Worker error for {ticker}: {e}")
                        data = None
                    if data is not None:
                        results[ticker] = data
                    progress.advance(task)

        logger.info(f"Fetched fundamentals for {len(results)}/{total} tickers (workers={workers})")
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
