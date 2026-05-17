"""Shared boilerplate for sweep scripts.

The 13 ``scripts/sweep_*.py`` scripts all follow the same shape:

    1. argparse for sweep-specific values + a common set of risk knobs
    2. Resolve a ticker universe (themes / watchlist / custom)
    3. Fetch prices + fundamentals + SPY + VIX + earnings history
    4. Loop over sweep values, build a BacktestConfig, run_backtest
    5. Summarize, print a Rich table, save JSON

Everything except (1) and the body of (4) is genuinely identical
across the sweeps. This module hosts (2-3) and provides a helper for
(5) so individual sweep scripts shrink to ~50 lines focused on the
parameter they're actually testing.

Public API
----------
- ``SweepInputs`` — the dataclass returned by ``prepare_sweep_inputs``.
- ``prepare_sweep_inputs(...)`` — one-call setup. Replaces the 60+ lines
  of fetch boilerplate previously copy-pasted across every sweep.
- ``summarize_result(label, result)`` — uniform row dict for the
  comparison table.
- ``write_sweep_rows(rows, save_path)`` — JSON writer with parent-dir
  creation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class SweepInputs:
    """Everything a sweep needs to call ``run_backtest`` repeatedly."""

    config: Any
    strategy: dict
    strategy_name: str
    tickers: list[str]
    universe_label: str
    price_data: dict[str, pd.DataFrame]
    fundamentals: dict[str, dict]
    spy_df: Optional[pd.DataFrame]
    vix_df: Optional[pd.DataFrame]
    earnings_dates: dict[str, list]
    earnings_history: dict[str, pd.DataFrame]
    start: pd.Timestamp
    end: pd.Timestamp
    fetch_period: str

    @property
    def universe_size(self) -> int:
        return len(self.tickers)


def _resolve_universe(
    config, universe: str, custom_tickers: Optional[list[str]],
) -> tuple[list[str], str]:
    if custom_tickers:
        tickers = [t.strip().upper() for t in custom_tickers if t.strip()]
        return tickers, f"custom ({len(tickers)} tickers)"
    if universe == "themes":
        tickers = config.get_theme_tickers()
        return tickers, f"themes ({len(tickers)})"
    if universe == "watchlist":
        tickers = config.get_watchlist()
        return tickers, f"watchlist ({len(tickers)})"
    if universe == "portfolio":
        from src.portfolio import Portfolio
        tickers = Portfolio(config).get_tickers()
        return tickers, f"portfolio ({len(tickers)})"
    raise ValueError(f"Unknown universe: {universe!r}")


def prepare_sweep_inputs(
    *,
    config=None,
    strategy_name: str,
    universe: str = "themes",
    custom_tickers: Optional[list[str]] = None,
    years: float = 3.0,
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
    earnings_blackout_days: int = 3,
) -> SweepInputs:
    """One-call setup for a sweep harness.

    Loads universe, fetches prices / fundamentals / SPY / VIX / earnings,
    and packages everything into a ``SweepInputs`` that the sweep loop
    threads through ``run_backtest``.
    """
    from src.backtest.engine import fetch_earnings_history
    from src.config_loader import Config
    from src.data.cache import DataCache
    from src.data.fetcher import DataFetcher
    from src.data.fundamentals import FundamentalsFetcher

    if config is None:
        config = Config()
    strategy = config.get_strategy(strategy_name)

    tickers, universe_label = _resolve_universe(config, universe, custom_tickers)
    if not tickers:
        raise RuntimeError(f"No tickers found for universe {universe!r}")

    end_ts = end if end is not None else pd.Timestamp.now().normalize()
    start_ts = start if start is not None else end_ts - pd.Timedelta(days=int(365.25 * years))
    fetch_period_years = max(years + 2, 5)
    fetch_period = f"{int(fetch_period_years)}y"

    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5,
        ),
        force_fresh=False,
    )
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    logger.info("Fetching price history (period=%s) for %d tickers...",
                fetch_period, len(tickers))
    price_data = fetcher.fetch_batch(tickers, period=fetch_period)
    logger.info("Got price data for %d/%d tickers", len(price_data), len(tickers))

    logger.info("Fetching fundamentals snapshot...")
    fundamentals = fund_fetcher.fetch_batch(tickers)

    logger.info("Fetching SPY + VIX (regime tagging)...")
    bench_map = fetcher.fetch_batch(["SPY", "^VIX"], period=fetch_period)

    logger.info("Fetching earnings history (PEAD + blackout)...")
    earnings_history = fetch_earnings_history(list(price_data.keys()))

    earnings_dates: dict[str, list] = {}
    if earnings_blackout_days > 0:
        for t, df_h in earnings_history.items():
            if df_h is None or df_h.empty:
                earnings_dates[t] = []
            else:
                earnings_dates[t] = sorted(df_h.index.tolist())

    return SweepInputs(
        config=config,
        strategy=strategy,
        strategy_name=strategy_name,
        tickers=tickers,
        universe_label=universe_label,
        price_data=price_data,
        fundamentals=fundamentals,
        spy_df=bench_map.get("SPY"),
        vix_df=bench_map.get("^VIX"),
        earnings_dates=earnings_dates,
        earnings_history=earnings_history,
        start=start_ts,
        end=end_ts,
        fetch_period=fetch_period,
    )


def summarize_result(label: Any, result: dict) -> dict:
    """Canonical comparison row used by every sweep table.

    ``label`` is whatever the sweep is varying (a min_score float, an
    ATR multiplier, a strategy name); it's stored as the first column
    so the table header can rename it per sweep.
    """
    full = result["full"]
    oos = result["out_of_sample"]
    return {
        "label": label,
        "n_trades": full["summary"]["n_trades"],
        "n_oos_trades": oos["summary"]["n_trades"],
        "full_return_pct": full["summary"]["total_return_pct"],
        "oos_return_pct": oos["summary"]["total_return_pct"],
        "full_sharpe": full["equity_stats"]["ann_sharpe"],
        "oos_sharpe": oos["equity_stats"]["ann_sharpe"],
        "max_dd_pct": full["equity_stats"]["max_drawdown_pct"],
        "win_rate_pct": full["summary"]["win_rate_pct"],
    }


def write_sweep_rows(rows: list[dict], save_path: Path | str) -> Path:
    """JSON writer with parent-dir creation. Returns the resolved path."""
    p = Path(save_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    return p
