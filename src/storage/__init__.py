"""Parquet-backed OHLCV storage.

Implements src.contracts.protocols.repositories.PriceRepository.
Replaces the price-data portion of src.data.cache.DataCache (which serialized
DataFrames to JSON inside SQLite). Time-series at scale belongs in columnar
storage; pyarrow + parquet is fast, append-friendly, and pandas-native.
"""

from src.storage.parquet_ohlcv import ParquetPriceRepository
from src.storage.partition import partition_path, year_partitions

__all__ = [
    "ParquetPriceRepository",
    "partition_path",
    "year_partitions",
]
