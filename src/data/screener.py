"""
Stock screener - discovers stocks to analyze using staged filtering.

Stage 1: Broad discovery (finviz, local CSV, or watchlist)
Stage 2: Filter by config criteria (market cap, volume, sector)
"""

import hashlib
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _make_screener_cache_key(
    sector_filter: str,
    filters_dict: dict[str, str],
    max_stage1: int,
) -> str:
    """Tier-2 #13: include the full materialized filter set in the cache
    key so config knob changes (min_cap, min_volume, min_price, exchange)
    auto-invalidate. ``v2_`` prefix ensures legacy entries (which were
    keyed only on sector_filter) auto-expire on first read.

    Hash is a stable 16-char hex digest — sortable in cache backends,
    short enough to fit in Redis key budgets, long enough to make
    collision negligible at our scale (<10k distinct configs)."""
    payload = json.dumps(
        {"filters": filters_dict, "max_stage1": max_stage1},
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"screener_finviz_v2_{sector_filter}_{digest}"


class StockScreener:
    def __init__(self, config, cache):
        self.config = config
        self.cache = cache

    def discover(self, sector_filter=None, theme_filter=None):
        """
        Discover stocks using the configured discovery method.
        Returns a list of ticker symbols.

        Args:
            sector_filter: optional sector key to limit results (e.g., 'technology')
            theme_filter: optional theme key (e.g., 'artificial_intelligence')
        """
        method = self.config.get("screening", "discovery_method", default="finviz")

        # If a theme is specified, start with known tickers
        if theme_filter:
            theme = self.config.get_theme(theme_filter)
            if theme:
                tickers = theme.get("known_tickers", [])
                logger.info(
                    f"Theme '{theme_filter}': {len(tickers)} known tickers"
                )
                return tickers
            logger.warning(f"Theme '{theme_filter}' not found in config")

        if method == "finviz":
            return self._discover_finviz(sector_filter)
        elif method == "local_csv":
            return self._discover_csv()
        elif method == "watchlist":
            return self._discover_watchlist()
        else:
            logger.error(f"Unknown discovery method: {method}")
            return self._discover_watchlist()

    def _discover_finviz(self, sector_filter=None):
        """Use finvizfinance to screen stocks.

        Tier-2 audit #13: pre-fix the cache key was just
        ``screener_finviz_{sector_filter or 'all'}``. Two scans run with
        different ``markets.*`` config — different min_cap, min_volume,
        min_price, exchanges — would collide on the same cache entry,
        silently returning yesterday's filter results for today's
        config. Now we build the filters_dict FIRST, then hash it into
        the cache key so a config diff invalidates cleanly. The ``v2_``
        prefix auto-expires legacy entries from before the fix.
        """
        try:
            from finvizfinance.screener.overview import Overview
        except ImportError:
            logger.error(
                "finvizfinance not installed. Install with: pip install finvizfinance"
            )
            return self._discover_watchlist()

        # --- Build filter dict before hashing it for the cache key ----
        filters_dict: dict[str, str] = {}

        # Market cap filter
        min_cap = self.config.get("markets", "min_market_cap", default=0)
        if min_cap >= 10_000_000_000:
            filters_dict["Market Cap."] = "+Large (over $10bln)"
        elif min_cap >= 2_000_000_000:
            filters_dict["Market Cap."] = "+Mid (over $2bln)"
        elif min_cap >= 300_000_000:
            filters_dict["Market Cap."] = "+Small (over $300mln)"

        # Sector filter
        if sector_filter:
            sector_cfg = self.config.get_sector(sector_filter)
            if sector_cfg:
                finviz_name = sector_cfg.get("finviz_filter")
                if finviz_name:
                    filters_dict["Sector"] = finviz_name
        elif self.config.get_focused_sectors():
            # Use first focused sector if no specific filter
            # For multiple sectors, we'll run multiple screens
            pass

        # Exchange filter
        exchanges = self.config.get("markets", "exchanges", default=[])
        if exchanges:
            if len(exchanges) == 1:
                filters_dict["Exchange"] = exchanges[0]

        # Average volume filter
        min_vol = self.config.get("markets", "min_avg_volume", default=0)
        if min_vol >= 2_000_000:
            filters_dict["Average Volume"] = "Over 2M"
        elif min_vol >= 1_000_000:
            filters_dict["Average Volume"] = "Over 1M"
        elif min_vol >= 500_000:
            filters_dict["Average Volume"] = "Over 500K"
        elif min_vol >= 200_000:
            filters_dict["Average Volume"] = "Over 200K"

        # Price filter
        min_price = self.config.get("markets", "min_price", default=0)
        if min_price >= 10:
            filters_dict["Price"] = "Over $10"
        elif min_price >= 5:
            filters_dict["Price"] = "Over $5"

        # Apply stage 1 limit also influences the result; include in hash.
        max_stage1 = self.config.get(
            "screening", "stage1_max_stocks", default=500
        )

        # Cache key includes the full materialized filter set + cap so
        # any config knob change auto-busts the cache. v2_ prefix
        # auto-expires entries written under the old (under-keyed) name.
        cache_key = _make_screener_cache_key(
            sector_filter or "all", filters_dict, max_stage1,
        )

        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.info(f"Using cached screener results: {len(cached)} tickers")
            return cached

        try:
            screen = Overview()
            screen.set_filter(filters_dict=filters_dict)
            df = screen.screener_view()

            if df is None or df.empty:
                logger.warning("Finviz screener returned no results")
                return self._discover_watchlist()

            tickers = df["Ticker"].tolist()
            tickers = tickers[:max_stage1]

            self.cache.set(cache_key, tickers)
            logger.info(f"Finviz screener found {len(tickers)} stocks")
            return tickers

        except Exception as e:
            # ImportError is caught upstream (before key construction);
            # this branch handles screener_view() failures, network
            # blips, etc. Fall back to watchlist so a single finviz
            # outage doesn't take the whole scan down.
            logger.error(f"Finviz screener error: {e}")
            return self._discover_watchlist()

    def _discover_csv(self):
        """Load tickers from a local CSV file."""
        csv_path = self.config.get("screening", "local_csv_path")
        if not csv_path:
            logger.error("No local_csv_path configured")
            return self._discover_watchlist()

        path = Path(csv_path)
        if not path.exists():
            logger.error(f"CSV file not found: {path}")
            return self._discover_watchlist()

        try:
            with open(path, "r") as f:
                tickers = [
                    line.strip().upper()
                    for line in f
                    if line.strip() and not line.startswith("#")
                ]
            logger.info(f"Loaded {len(tickers)} tickers from {path}")
            return tickers
        except Exception as e:
            logger.error(f"Error reading CSV: {e}")
            return []

    def _discover_watchlist(self):
        """Use the watchlist + theme tickers from config."""
        watchlist = self.config.get_watchlist()
        theme_tickers = self.config.get_theme_tickers()
        combined = list(dict.fromkeys(watchlist + theme_tickers))  # dedupe, preserve order
        logger.info(f"Using watchlist + themes: {len(combined)} tickers")
        return combined

    def discover_by_sectors(self, sectors=None):
        """
        Discover stocks across multiple sectors.
        Returns deduplicated list of tickers.
        """
        if sectors is None:
            sectors = self.config.get_focused_sectors()

        all_tickers = []
        sector_map = self.config.get_all_sectors()

        for sector_name in sectors:
            # Find matching sector key
            sector_key = None
            for key, val in sector_map.items():
                if val.get("display_name", "").lower() == sector_name.lower():
                    sector_key = key
                    break

            if sector_key:
                tickers = self.discover(sector_filter=sector_key)
                all_tickers.extend(tickers)
                time.sleep(1)  # Rate limit between screens

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for t in all_tickers:
            if t not in seen:
                seen.add(t)
                unique.append(t)

        # Add watchlist tickers
        for t in self.config.get_watchlist():
            if t not in seen:
                seen.add(t)
                unique.append(t)

        max_stage1 = self.config.get("screening", "stage1_max_stocks", default=500)
        return unique[:max_stage1]

    def stage2_filter(self, tickers, fundamentals_map):
        """
        Stage 2: Deep filter using fundamental data.
        Returns the top N tickers ranked by quality signals.
        """
        max_stage2 = self.config.get("screening", "stage2_max_stocks", default=50)
        scored = []

        for ticker in tickers:
            fund = fundamentals_map.get(ticker)
            if fund is None:
                continue

            # Quick quality score for ranking
            score = 0

            # Market cap bonus (larger = more reliable data)
            mcap = fund.get("market_cap") or 0
            if mcap > 100_000_000_000:
                score += 3
            elif mcap > 10_000_000_000:
                score += 2
            elif mcap > 1_000_000_000:
                score += 1

            # Revenue growth
            rg = fund.get("revenue_growth")
            if rg is not None and rg > 0.1:
                score += 2
            elif rg is not None and rg > 0:
                score += 1

            # Profitability
            pm = fund.get("profit_margin")
            if pm is not None and pm > 0.1:
                score += 2
            elif pm is not None and pm > 0:
                score += 1

            # Analyst sentiment
            rec = fund.get("recommendation")
            if rec in ("strongBuy", "buy"):
                score += 2
            elif rec == "hold":
                score += 1

            # Volume (higher = more liquid)
            vol = fund.get("avg_volume") or 0
            min_vol = self.config.get("markets", "min_avg_volume", default=500_000)
            if vol >= min_vol:
                score += 1

            scored.append((ticker, score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        filtered = [t for t, _ in scored[:max_stage2]]
        logger.info(
            f"Stage 2 filter: {len(tickers)} -> {len(filtered)} stocks"
        )
        return filtered
