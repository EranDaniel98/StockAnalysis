"""Sync runner that drives the existing backtest engine without CLI output.

Mirrors src/main.py:cmd_backtest minus the Rich console + arg parsing. Returns
the raw result dict from src/backtest/engine.run_backtest.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from src.api.schemas.backtest import BacktestRequest
from src.backtest.engine import (
    BacktestConfig,
    fetch_earnings_history,
    run_backtest,
)
from src.data.cache import DataCache
from src.data.fetcher import DataFetcher
from src.data.fundamentals import FundamentalsFetcher

logger = logging.getLogger(__name__)


def _resolve_universe(config, body: BacktestRequest) -> tuple[list[str], str]:
    """Returns (tickers, universe_label) for the requested universe kind."""
    if body.universe == "tickers":
        if not body.tickers:
            raise ValueError("universe='tickers' requires a non-empty tickers list")
        tickers = [t.strip().upper() for t in body.tickers if t.strip()]
        return tickers, f"custom ({len(tickers)} tickers)"
    if body.universe == "portfolio":
        from src.portfolio import Portfolio

        tickers = Portfolio(config).get_tickers()
        return tickers, f"portfolio ({len(tickers)})"
    if body.universe == "themes":
        tickers = config.get_theme_tickers()
        return tickers, f"themes ({len(tickers)})"
    # watchlist
    tickers = config.get_watchlist()
    return tickers, f"watchlist ({len(tickers)})"


def run_backtest_sync(config, body: BacktestRequest) -> dict[str, Any]:
    """Execute a walk-forward backtest. Returns raw result dict from the
    engine plus our own universe_label / window metadata stitched in.

    Heavy compute (price fetch + analyzers + sim) runs inline — caller should
    offload to a worker thread.
    """
    strategy = config.get_strategy(body.strategy)
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
    bench = fetcher.fetch_batch(["SPY", "^VIX"], period=fetch_period)
    spy_df = bench.get("SPY")
    vix_df = bench.get("^VIX")

    earnings_history = fetch_earnings_history(list(price_data.keys()))
    earnings_dates: dict = {}
    if body.earnings_blackout > 0:
        for t, df_h in earnings_history.items():
            earnings_dates[t] = (
                sorted(df_h.index.tolist())
                if df_h is not None and not df_h.empty
                else []
            )

    min_score = (
        body.min_score if body.min_score is not None else strategy.get("min_score", 65)
    )
    # Time-stop resolution mirrors min_score: explicit request wins,
    # otherwise the strategy's literature-calibrated default. Falls
    # back to 90 (legacy BacktestConfig default) only when neither
    # has a value.
    hold_days = (
        body.hold_days if body.hold_days is not None
        else int(strategy.get("time_stop_days", 90))
    )

    bt_cfg = BacktestConfig(
        start_date=start,
        end_date=end,
        min_score=min_score,
        max_open_positions=body.max_positions,
        max_position_pct=body.position_pct,
        starting_cash=body.cash,
        max_hold_days=hold_days,
        commission_per_trade=body.commission,
        slippage_bps=body.slippage_bps,
        regulatory_bps_on_sale=body.regulatory_bps,
        earnings_blackout_days=body.earnings_blackout,
        accept_lookahead=body.accept_lookahead,
        oos_split_pct=body.oos_split,
        bootstrap_resamples=body.bootstrap_resamples,
        vol_target_risk_pct=body.vol_target_risk,
    )

    result = run_backtest(
        price_data,
        fundamentals,
        config,
        strategy,
        bt_cfg,
        spy_df=spy_df,
        vix_df=vix_df,
        earnings_dates=earnings_dates,
        earnings_history=earnings_history,
    )

    result.setdefault("strategy", body.strategy)
    result.setdefault("window_start", start.isoformat())
    result.setdefault("window_end", end.isoformat())
    result.setdefault("universe_label", universe_label)
    return result
