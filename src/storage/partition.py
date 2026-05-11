"""Partition layout helpers for the OHLCV Parquet store.

Layout:
    data/ohlcv/year=YYYY/ticker=TICKER.parquet

Rationale (per the Phase 0 plan): "read-by-date-range-for-one-ticker is the
dominant query (every scan, every backtest entry/exit). Cross-ticker reads
(alphalens) hit ~30 files per year — acceptable with pyarrow.dataset
partition pruning."
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

# Project-root-relative default. Override via STOCKNEW_OHLCV_ROOT env var if
# you want to point at a different location (e.g. an external SSD).
DEFAULT_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "ohlcv"


def partition_path(root: Path, ticker: str, year: int) -> Path:
    """Return the canonical file path for one (ticker, year) partition.

    The path encodes the partition keys in hive format
    (year=YYYY/ticker=TICKER.parquet) so pyarrow.dataset can scan the
    directory and infer partitioning without an explicit schema."""
    return root / f"year={year}" / f"ticker={ticker}.parquet"


def year_partitions(start: datetime, end: datetime) -> list[int]:
    """Return the list of year values whose partitions could overlap
    [start, end]. Inclusive on both ends."""
    return list(range(start.year, end.year + 1))
