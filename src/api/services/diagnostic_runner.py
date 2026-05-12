"""Sync runner for the alphalens IC diagnostic."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from src.api.schemas.diagnostic import DiagnosticRequest
from src.backtest.engine import LookaheadGuardError, fetch_earnings_history
from src.data.cache import DataCache
from src.data.fetcher import DataFetcher
from src.data.fundamentals import FundamentalsFetcher
from src.research.diagnostic_service import (
    build_price_matrix,
    build_score_panel,
    run_alphalens,
)

logger = logging.getLogger(__name__)


def _resolve_universe(config, body: DiagnosticRequest) -> tuple[list[str], str]:
    if body.universe == "tickers":
        if not body.tickers:
            raise ValueError("universe='tickers' requires a non-empty tickers list")
        tickers = [t.strip().upper() for t in body.tickers if t.strip()]
        return tickers, f"custom ({len(tickers)})"
    if body.universe == "portfolio":
        from src.portfolio import Portfolio

        tickers = Portfolio(config).get_tickers()
        return tickers, f"portfolio ({len(tickers)})"
    if body.universe == "themes":
        tickers = config.get_theme_tickers()
        return tickers, f"themes ({len(tickers)})"
    tickers = config.get_watchlist()
    return tickers, f"watchlist ({len(tickers)})"


def run_diagnostic_sync(config, body: DiagnosticRequest) -> dict[str, Any]:
    """Run the panel build + alphalens IC computation. Returns the raw
    alphalens result dict plus window/universe metadata."""
    strategy = config.get_strategy(body.strategy)

    fund_weight = strategy.get("weights", {}).get("fundamental", 0)
    if fund_weight > 0.05 and not body.accept_lookahead:
        raise LookaheadGuardError(
            f"strategy weights fundamentals at {fund_weight*100:.0f}% — pass "
            f"accept_lookahead=true to override (results will be invalid)."
        )

    tickers, universe_label = _resolve_universe(config, body)
    if not tickers:
        return {"error": f"empty universe '{body.universe}'"}

    end = pd.Timestamp.now().normalize()
    start = end - pd.Timedelta(days=int(365.25 * body.years))
    fetch_period_years = max(body.years + 2, 5)
    fetch_period = f"{int(fetch_period_years)}y"

    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5
        ),
        force_fresh=body.fresh,
    )
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    price_data = fetcher.fetch_batch(tickers, period=fetch_period)
    fundamentals = fund_fetcher.fetch_batch(tickers)
    earnings_history = fetch_earnings_history(list(price_data.keys()))

    panel = build_score_panel(
        price_data, fundamentals, earnings_history, config, strategy, start, end
    )
    if panel.empty:
        return {"error": "empty panel — nothing to analyze"}

    prices = build_price_matrix(
        price_data, panel["date"].min(), end + pd.Timedelta(days=30)
    )
    result = run_alphalens(
        panel,
        prices,
        factor_column=body.factor,
        periods=tuple(body.periods),
        quantiles=body.quantiles,
    )
    result["universe_label"] = universe_label
    result["window_start"] = start.isoformat()
    result["window_end"] = end.isoformat()
    return result
