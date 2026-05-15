"""
Fundamental data fetcher - downloads financial metrics from yfinance.

`yf.Ticker.info` is the slowest yfinance endpoint (5-15s on a healthy
network) and has no timeout, so every call is wrapped in
src.data.fetch_outcome.call_with_timeout. Tier-1 audit #8.
"""

import yfinance as yf
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from src.data.fetch_outcome import call_with_timeout

logger = logging.getLogger(__name__)

# 15s allows for a slow but healthy yfinance .info round-trip (vendor
# claims 5-15s typical). A hung connection past this gets cut so the
# worker pool doesn't drain on bad tickers.
_INFO_TIMEOUT_SECONDS = 15.0


def _coerce_numeric(value):
    """Coerce a yfinance value to float or None.

    yfinance returns string sentinels for undefined numerics — most
    commonly ``'Infinity'`` when a P/E is undefined because earnings
    are negative, but ``'NaN'`` / ``'Inf'`` / ``''`` also appear. Pre-fix,
    these strings propagated into downstream analyzers where
    ``value > 0`` exploded with TypeError. Caught BILL on 2024-05-20 in
    the in-flight sweep battery — every Monday from there on was
    silently skipped before the audit promoted the score-ticker
    exception log from debug to warning (commit 9345a74).

    None / NaN / Inf / unparseable strings all map to None; downstream
    analyzers already handle missing fields gracefully via
    ``value is not None`` guards.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Numerically NaN / Inf are not useful for comparisons either —
        # treat them the same as None to keep downstream guards uniform.
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        if f != f or f in (float("inf"), float("-inf")):  # NaN or +/-Inf
            return None
        return f
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() in {"nan", "inf", "infinity", "-inf", "-infinity", "none", "null"}:
            return None
        try:
            return _coerce_numeric(float(stripped))
        except (TypeError, ValueError):
            return None
    return None


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
            if not info or info.get("trailingPE") is None and info.get("sector") is None:
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
