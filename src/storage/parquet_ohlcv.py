"""Parquet-backed OHLCV PriceRepository.

Storage layout (see src/storage/partition.py):
    data/ohlcv/year=YYYY/ticker=TICKER.parquet

Reads use pyarrow.dataset for partition pruning. Writes use whole-file
replacement (read existing → merge new bars → atomic rename) because
parquet appends are tricky and Phase 0 has a single writer process.

DataFrame contract (preserves the legacy yfinance shape):
- columns: ['Open', 'High', 'Low', 'Close', 'Volume']
- DatetimeIndex (tz-naive, UTC-equivalent)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from src.contracts.errors import DataError
from src.storage.partition import DEFAULT_ROOT, partition_path, year_partitions

logger = logging.getLogger(__name__)

OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def get_ohlcv_root() -> Path:
    """Resolve the Parquet store root. Override via STOCKNEW_OHLCV_ROOT."""
    raw = os.environ.get("STOCKNEW_OHLCV_ROOT")
    return Path(raw) if raw else DEFAULT_ROOT


class ParquetPriceRepository:
    """Implements src.contracts.protocols.repositories.PriceRepository.

    latest_price_fetcher is an injectable strategy for the get_latest_price
    method (which intentionally bypasses the store — realtime quotes don't
    live in Parquet). Default delegates to yfinance with a short timeout.
    """

    def __init__(
        self,
        root: Optional[Path] = None,
        latest_price_fetcher: Optional[Callable[[str], Optional[float]]] = None,
    ) -> None:
        self._root = Path(root) if root else get_ohlcv_root()
        self._root.mkdir(parents=True, exist_ok=True)
        self._latest_price_fetcher = latest_price_fetcher or _default_latest_price

    # ---- writes -------------------------------------------------------

    def write_history(self, ticker: str, df: pd.DataFrame) -> int:
        """Persist a DataFrame to the per-year partitions for this ticker.

        Per-year-and-ticker file is rewritten atomically: existing bars are
        merged with the new ones (new wins on conflict), sorted by index,
        and written to a temp file then renamed. Returns total bars written
        across all year partitions.

        Sync method — Parquet I/O is CPU-bound, not async-friendly. Callers
        from async contexts should wrap in asyncio.to_thread().
        """
        if df is None or df.empty:
            return 0
        df = _normalize_df(df)
        total = 0
        # Group by year on the index
        for year, year_slice in df.groupby(df.index.year):
            path = partition_path(self._root, ticker, int(year))
            path.parent.mkdir(parents=True, exist_ok=True)
            merged = _merge_with_existing(path, year_slice)
            tmp = path.with_suffix(".parquet.tmp")
            table = pa.Table.from_pandas(merged, preserve_index=True)
            pq.write_table(table, tmp, compression="snappy")
            tmp.replace(path)  # atomic on POSIX; near-atomic on Windows NTFS
            total += len(merged)
        return total

    # ---- async reads (Protocol surface) -------------------------------

    async def get_history(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Read OHLCV slice for one ticker. Returns empty DataFrame on
        no-data — caller diffs to find missing tickers."""
        if interval != "1d":
            raise NotImplementedError(
                f"Phase 0 only supports interval='1d'; got {interval!r}"
            )
        return self._read_sync(ticker, start, end)

    async def get_batch(
        self,
        tickers: list[str],
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        """Batch read. Skipping pyarrow's row-group parallelism for now —
        loading per ticker keeps the API symmetrical with get_history and
        is fast enough at <100 tickers."""
        out: dict[str, pd.DataFrame] = {}
        for t in tickers:
            try:
                df = await self.get_history(t, start, end, interval)
                if not df.empty:
                    out[t] = df
            except DataError:
                continue
        return out

    async def get_latest_price(self, ticker: str) -> float | None:
        """Realtime — not cached, not stored. Delegates to the injected
        fetcher (default: yfinance with a short timeout)."""
        return self._latest_price_fetcher(ticker)

    # ---- internals ----------------------------------------------------

    def _read_sync(self, ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
        years = year_partitions(start, end)
        candidate_paths = [
            partition_path(self._root, ticker, y) for y in years
        ]
        present = [p for p in candidate_paths if p.exists()]
        if not present:
            return pd.DataFrame(columns=OHLCV_COLUMNS)

        # Read each existing per-year file and concat. pq.read_table on a
        # path with `year=YYYY/ticker=TICKER.parquet` triggers PyArrow's
        # Hive partition inference and synthesizes `year`/`ticker` columns
        # in the result — drop them so callers see only the canonical OHLCV
        # columns.
        frames: list[pd.DataFrame] = []
        for path in present:
            try:
                table = pq.read_table(path)
                pdf = table.to_pandas()
                pdf = pdf.drop(columns=["year", "ticker"], errors="ignore")
                frames.append(pdf)
            except Exception as e:
                logger.warning("Failed reading %s: %s", path, e)
        if not frames:
            return pd.DataFrame(columns=OHLCV_COLUMNS)
        df = pd.concat(frames).sort_index()
        # Index may carry tz; clip on the same tz-form to avoid issues
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        if df.index.tz is not None:
            if start_ts.tz is None:
                start_ts = start_ts.tz_localize("UTC")
            if end_ts.tz is None:
                end_ts = end_ts.tz_localize("UTC")
        return df.loc[start_ts:end_ts]


# ---- helpers ----------------------------------------------------------


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure DataFrame conforms to the OHLCV contract."""
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index.name = "Date"
    # Only keep canonical columns (yfinance sometimes adds 'Adj Close', 'Dividends', etc.)
    keep = [c for c in OHLCV_COLUMNS if c in df.columns]
    if not keep:
        raise DataError(f"DataFrame missing all OHLCV columns. Has: {list(df.columns)}")
    return df[keep].sort_index()


def _merge_with_existing(path: Path, new_df: pd.DataFrame) -> pd.DataFrame:
    """Read existing partition (if any), concat new bars, drop duplicates
    by index (new bars win), sort."""
    if not path.exists():
        return new_df
    try:
        existing = pq.read_table(path).to_pandas()
        # Strip Hive-inferred partition columns (see _read_sync for context)
        existing = existing.drop(columns=["year", "ticker"], errors="ignore")
    except Exception as e:
        logger.warning("Could not read existing %s, overwriting: %s", path, e)
        return new_df
    combined = pd.concat([existing, new_df])
    # Keep last on duplicates so the new write wins for same-index bars
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


def _default_latest_price(ticker: str) -> float | None:
    """Fallback realtime fetcher — calls yfinance with a 2-second timeout.

    Realtime quotes aren't a storage concern; the FastAPI layer (Phase 1)
    will inject an Alpaca-backed fetcher for live trading. This default
    preserves current CLI behavior for the parity test."""
    try:
        import yfinance as yf  # local import — yfinance is heavy

        info = yf.Ticker(ticker).fast_info
        price = getattr(info, "last_price", None)
        return float(price) if price else None
    except Exception as e:
        logger.debug("Latest price fetch failed for %s: %s", ticker, e)
        return None
