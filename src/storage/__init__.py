"""Parquet-backed OHLCV storage.

Implements src.contracts.protocols.repositories.PriceRepository.
Replaces the price-data portion of src.data.cache.DataCache (which serialized
DataFrames to JSON inside SQLite). Time-series at scale belongs in columnar
storage; pyarrow + parquet is fast, append-friendly, and pandas-native.
"""

from src.storage.parquet_ohlcv import ParquetPriceRepository
from src.storage.partition import partition_path, year_partitions
from src.storage.snapshot import (
    SnapshotInputs,
    SnapshotManifest,
    list_snapshots,
    load_snapshot,
    write_snapshot,
)

__all__ = [
    "ParquetPriceRepository",
    "partition_path",
    "year_partitions",
    "SnapshotInputs",
    "SnapshotManifest",
    "load_snapshot",
    "write_snapshot",
    "list_snapshots",
]
