"""Universe + price loading helpers.

Single source of truth for "pull the current PIT S&P 500 + fetch OHLCV
with the configured cache and tz-normalize the results." Previously
duplicated across ``scripts/daily_factor_picks.py``,
``scripts/analyze_ticker.py``, and ``scripts/comprehensive_analysis.py``.

Why centralize:
- Three call sites means three opportunities to forget the tz-normalize
  step. The factor code (``src/factors/*.py``) does ``df.index <= as_of``
  comparisons that break on tz-aware indices, so any path that skips
  normalization silently returns 0 names.
- Cache TTL config-keys are easy to typo. One place to read them.
- A snapshot-id branch needs to live somewhere — putting it next to the
  live-fetch branch makes the deterministic-vs-live tradeoff explicit.

Public API
----------
- ``load_prices(tickers, ...)`` — fetch + tz-normalize for a given list.
- ``load_pit_sp500_with_prices(as_of, ...)`` — PIT S&P 500 + prices.
- ``load_from_snapshot(snapshot_id)`` — load a frozen snapshot.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _normalize_tz(df: pd.DataFrame) -> pd.DataFrame:
    """Strip tz from a price frame's DatetimeIndex. No-op if already
    naive or if the index isn't datetime."""
    if df is None or df.empty:
        return df
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    return df


def _build_cache(config) -> "DataCache":  # noqa: F821 (forward ref to lazy import)
    from src.data.cache import DataCache

    return DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5,
        ),
    )


def load_prices(
    tickers: list[str],
    *,
    config=None,
) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV for ``tickers`` via the configured cache + fetcher.

    Returns a dict ``{ticker: tz-naive OHLCV DataFrame}``. Tickers
    without price data are dropped (legacy contract).
    """
    from src.config_loader import Config
    from src.data.fetcher_factory import get_data_fetcher

    if config is None:
        config = Config()
    cache = _build_cache(config)
    fetcher = get_data_fetcher(config, cache)
    raw = fetcher.fetch_batch(tickers)
    out: dict[str, pd.DataFrame] = {}
    for t, df in raw.items():
        d = _normalize_tz(df)
        if d is None or d.empty:
            continue
        out[t] = d
    return out


def load_pit_sp500_with_prices(
    as_of: pd.Timestamp,
    *,
    extra_tickers: Iterable[str] = (),
    config=None,
) -> tuple[list[str], dict[str, pd.DataFrame]]:
    """Return ``(universe_tickers, prices)`` for the PIT S&P 500.

    ``extra_tickers`` are added to the universe if not already present
    (useful for ad-hoc per-ticker analysis when the subject isn't an
    index constituent). The returned universe is the union; prices are
    only included for tickers that yfinance/DataFetcher returned data
    for.
    """
    from src.config_loader import Config

    if config is None:
        config = Config()
    universe: list[str] = list(config.get_sp500_pit_tickers(as_of))
    if not universe:
        raise RuntimeError(
            "PIT S&P 500 universe is empty — run "
            "`uv run python -m scripts.fetch_sp500_membership` first."
        )
    seen = set(universe)
    for t in extra_tickers:
        if t not in seen:
            universe.append(t)
            seen.add(t)

    prices = load_prices(universe, config=config)
    logger.info(
        "Loaded %d/%d tickers with prices (PIT S&P 500 + %d extras)",
        len(prices), len(universe), max(0, len(universe) - len(seen) + len(list(extra_tickers))),
    )
    return universe, prices


def load_from_snapshot(snapshot_id: str) -> tuple[list[str], dict[str, pd.DataFrame]]:
    """Return ``(sorted_tickers, prices)`` from a frozen snapshot.

    Snapshots are deterministic — every call returns the same prices.
    Use these for backtests and for reproducing exact picks across
    machines.
    """
    from src.storage.snapshot import load_snapshot

    snap = load_snapshot(snapshot_id)
    tickers = sorted(snap.price_data.keys())
    return tickers, snap.price_data
