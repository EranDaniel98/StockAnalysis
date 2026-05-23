"""Shared yfinance earnings-history loader with per-ticker parquet cache.

Single source of truth for sites that previously called
``yfinance.Ticker(t).get_earnings_dates(...)`` independently — the
backtest engine, the PEAD factor pipeline, the per-stock analyzer
fallback, the comprehensive-analysis report, and the exit-analysis
script.

Why a single module
-------------------
- The parquet write/read round-trip needs DatetimeIndex restoration
  (``reset_index()`` flattens the index to an ``earnings_ts`` column).
  Without restoring it on read, the analyzer sees a RangeIndex, the
  date column is treated as ints, and PEAD silently returns neutral
  for every ticker. This bug shipped once already (2026-05-16) — one
  fix in one place.
- yfinance is patchy: it returns tz-aware OR tz-naive frames depending
  on the ticker, sometimes emits duplicate-timestamped rows, and has
  no native timeout. Centralizing means every caller gets the same
  canonical shape with the same timeout protection.
- 24 h TTL is right for daily picks; backtests that want hot results
  can pass a longer TTL.

Public API
----------
- ``load_earnings_history(ticker, ...)`` — one ticker, full history.
- ``load_earnings_histories(tickers, ...)`` — batch, in parallel.
- ``load_next_earnings_dates(tickers, ...)`` — next event per ticker.
- ``load_earnings_date_lists(tickers, ...)`` — all events per ticker
  (replaces the backtest engine's ``fetch_earnings_dates``).
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/earnings_history")
DEFAULT_LIMIT = 40
DEFAULT_MAX_AGE_HOURS = 24
DEFAULT_FETCH_TIMEOUT_S = 30.0
DEFAULT_WORKERS = 8


def _normalize(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Strip tz from index; return None if empty."""
    if df is None or df.empty:
        return None
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    return df


def _read_cached(cache_path: Path, max_age_hours: int) -> Optional[pd.DataFrame]:
    """Read a per-ticker parquet if fresh; otherwise None."""
    if not cache_path.exists():
        return None
    age_h = (time.time() - cache_path.stat().st_mtime) / 3600.0
    if age_h > max_age_hours:
        return None
    try:
        df = pd.read_parquet(cache_path)
    except Exception as e:  # corrupt parquet → treat as miss
        logger.debug("earnings cache read failed for %s: %s", cache_path.name, e)
        return None
    if df.empty:
        return None
    # Restore the DatetimeIndex that was flattened on write. Without
    # this, the analyzer sees a RangeIndex and treats every row as a
    # stale Unix-epoch date.
    if "earnings_ts" in df.columns:
        df = df.set_index(pd.to_datetime(df["earnings_ts"])).drop(
            columns=["earnings_ts"]
        )
        df.index.name = None
    return _normalize(df)


def _write_cache(cache_path: Path, df: pd.DataFrame) -> None:
    try:
        df_out = df.reset_index().rename(
            columns={df.index.name or "index": "earnings_ts"}
        )
        df_out.to_parquet(cache_path, index=False)
    except Exception as e:
        logger.debug("earnings cache write failed for %s: %s", cache_path.name, e)


def _fetch_one(
    ticker: str, *, limit: int, timeout_s: float,
) -> Optional[pd.DataFrame]:
    """Call yfinance with timeout. Returns the canonical-shape frame
    or None on any failure / empty result."""
    import yfinance as yf

    from src.data.fetch_outcome import call_with_timeout

    df, err = call_with_timeout(
        lambda: yf.Ticker(ticker).get_earnings_dates(limit=limit),
        timeout_seconds=timeout_s,
        name=f"yf.get_earnings_dates({ticker})",
    )
    if err is not None:
        logger.debug("earnings fetch failed for %s: %s", ticker, err)
        return None
    return _normalize(df)


def load_earnings_history(
    ticker: str,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
    *,
    limit: int = DEFAULT_LIMIT,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    timeout_s: float = DEFAULT_FETCH_TIMEOUT_S,
) -> Optional[pd.DataFrame]:
    """Load one ticker's earnings history. None if unavailable.

    The returned DataFrame has a tz-naive DatetimeIndex and whatever
    columns yfinance emits (typically ``Surprise(%)``, ``Reported EPS``,
    ``EPS Estimate``). The shape matches ``yfinance.get_earnings_dates``
    exactly so existing analyzer code that consumes it doesn't change.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{ticker}.parquet"

    cached = _read_cached(cache_path, max_age_hours)
    if cached is not None:
        return cached

    df = _fetch_one(ticker, limit=limit, timeout_s=timeout_s)
    df = _normalize(df)
    if df is None:
        return None
    _write_cache(cache_path, df)
    return df


def load_earnings_histories(
    tickers: Iterable[str],
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
    *,
    limit: int = DEFAULT_LIMIT,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    timeout_s: float = DEFAULT_FETCH_TIMEOUT_S,
    workers: int = DEFAULT_WORKERS,
) -> dict[str, pd.DataFrame]:
    """Batch version. Missing tickers are omitted from the result.

    Parallelizes the network fetch step; cache reads are fast enough
    that we don't bother. Pass ``workers=1`` for deterministic order
    in tests.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    tickers = list(tickers)

    out: dict[str, pd.DataFrame] = {}
    to_fetch: list[str] = []
    n_cached = 0
    for t in tickers:
        cached = _read_cached(cache_dir / f"{t}.parquet", max_age_hours)
        if cached is not None:
            out[t] = cached
            n_cached += 1
        else:
            to_fetch.append(t)

    n_fetched = 0
    n_missing = 0
    if to_fetch:
        workers = max(1, min(workers, len(to_fetch)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {
                ex.submit(_fetch_one, t, limit=limit, timeout_s=timeout_s): t
                for t in to_fetch
            }
            for fut in as_completed(futures):
                t = futures[fut]
                try:
                    df = fut.result()
                except Exception as e:
                    logger.debug("earnings worker raised for %s: %s", t, e)
                    n_missing += 1
                    continue
                df = _normalize(df)
                if df is None:
                    n_missing += 1
                    continue
                _write_cache(cache_dir / f"{t}.parquet", df)
                out[t] = df
                n_fetched += 1

    logger.info(
        "Earnings histories: %d cached + %d fetched + %d missing (of %d)",
        n_cached, n_fetched, n_missing, len(tickers),
    )
    return out


def load_next_earnings_dates(
    tickers: Iterable[str],
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
    *,
    as_of: Optional[pd.Timestamp] = None,
    limit: int = 4,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    timeout_s: float = DEFAULT_FETCH_TIMEOUT_S,
    workers: int = DEFAULT_WORKERS,
) -> dict[str, pd.Timestamp]:
    """Earliest future earnings event per ticker, tz-naive.

    Returns only tickers that have a known future event. Defaults to
    ``limit=4`` since callers only need the next event.
    """
    if as_of is None:
        as_of = pd.Timestamp.utcnow().tz_localize(None)
    histories = load_earnings_histories(
        tickers, cache_dir,
        limit=limit, max_age_hours=max_age_hours,
        timeout_s=timeout_s, workers=workers,
    )
    out: dict[str, pd.Timestamp] = {}
    for t, df in histories.items():
        future = sorted([d for d in df.index if d >= as_of])
        if future:
            out[t] = future[0]
    return out


def load_earnings_date_lists(
    tickers: Iterable[str],
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
    *,
    limit: int = DEFAULT_LIMIT,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    timeout_s: float = DEFAULT_FETCH_TIMEOUT_S,
    workers: int = DEFAULT_WORKERS,
) -> dict[str, list[pd.Timestamp]]:
    """All earnings events per ticker, sorted ascending, tz-naive.

    Used by the backtest engine's earnings-blackout filter.
    """
    histories = load_earnings_histories(
        tickers, cache_dir,
        limit=limit, max_age_hours=max_age_hours,
        timeout_s=timeout_s, workers=workers,
    )
    return {
        t: sorted(pd.to_datetime(df.index).tolist())
        for t, df in histories.items()
    }
