"""Parquet partition protection contract.

Covers Tier-1 audit #7 (X#21 + X#20 + D#8): the writer used to swallow
a read exception during merge and overwrite the existing partition with
whatever the new write happened to carry, silently destroying up to a
year of OHLCV history. After the fix:

  * read failure -> rename the bad file to .corrupt-{ts}.bak and raise
    CorruptPartitionError so the operator notices BEFORE the next
    backtest runs against truncated data
  * read-merge-write runs under a portalocker per-partition lock so a
    second writer can't race the near-atomic tmp.replace(path) on
    Windows NTFS
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.storage.parquet_ohlcv import (
    CorruptPartitionError,
    ParquetPriceRepository,
    _merge_with_existing,
)
from src.storage.partition import partition_path


def _ohlcv(year: int, n: int = 5, start_price: float = 100.0) -> pd.DataFrame:
    """Build a tiny OHLCV frame with bars in `year`."""
    idx = pd.date_range(f"{year}-01-01", periods=n, freq="B")
    base = np.linspace(start_price, start_price + n - 1, n)
    return pd.DataFrame(
        {
            "Open": base,
            "High": base * 1.01,
            "Low": base * 0.99,
            "Close": base,
            "Volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


# --- corrupt-partition handling -------------------------------------------


def test_corrupt_partition_is_backed_up_and_raises(tmp_path: Path) -> None:
    """Keystone assertion: write a garbage file at the partition path so
    pyarrow's read raises, then assert _merge_with_existing renames it to
    .corrupt-{ts}.bak and raises CorruptPartitionError — NOT silently
    returning new_df (the old destructive behavior)."""
    partition = tmp_path / "year=2024" / "ticker=AAPL.parquet"
    partition.parent.mkdir(parents=True)
    partition.write_bytes(b"not a parquet file")

    new_df = _ohlcv(2024, n=3, start_price=101.0)
    with pytest.raises(CorruptPartitionError):
        _merge_with_existing(partition, new_df)

    # The bad file MUST have been preserved with a corrupt-* suffix.
    backups = list(partition.parent.glob("ticker=AAPL.parquet.corrupt-*.bak"))
    assert len(backups) == 1, f"expected one backup, got {backups}"
    assert backups[0].read_bytes() == b"not a parquet file"


def test_clean_partition_merges_normally(tmp_path: Path) -> None:
    repo = ParquetPriceRepository(root=tmp_path)
    repo.write_history("AAPL", _ohlcv(2024, n=3, start_price=100.0))
    # Second write extends the partition.
    repo.write_history("AAPL", _ohlcv(2024, n=5, start_price=200.0))

    df = repo._read_sync("AAPL", datetime(2024, 1, 1), datetime(2024, 12, 31))
    # Second write was 5 bars on the same calendar dates as the first 3 +
    # 2 fresh dates. Total unique bars in the partition: 5. The last-wins
    # dedup uses the SECOND write's values where the dates overlap.
    assert len(df) == 5
    assert df["Close"].iloc[0] == pytest.approx(200.0)


def test_writer_does_not_destroy_on_corrupt_existing(tmp_path: Path) -> None:
    """End-to-end safety: a write into a partition that already has a
    corrupt file at the same path must raise BEFORE any successful
    overwrite happens. The original bytes survive in the .bak."""
    repo = ParquetPriceRepository(root=tmp_path)
    partition = partition_path(tmp_path, "AAPL", 2024)
    partition.parent.mkdir(parents=True, exist_ok=True)
    partition.write_bytes(b"corrupt original bytes")

    with pytest.raises(CorruptPartitionError):
        repo.write_history("AAPL", _ohlcv(2024, n=3, start_price=999.0))

    # The corrupt file was moved aside, not destroyed.
    backups = list(partition.parent.glob("ticker=AAPL.parquet.corrupt-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"corrupt original bytes"


# --- portalocker file lock ------------------------------------------------


def test_writes_are_serialized_by_file_lock(tmp_path: Path) -> None:
    """Two threads writing to the same partition under the per-partition
    lock must each complete without observing a half-written tmp file.
    Final state must contain bars from both writes (last-wins dedup)."""
    repo = ParquetPriceRepository(root=tmp_path)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def writer(start_price: float) -> None:
        try:
            barrier.wait()
            repo.write_history("AAPL", _ohlcv(2024, n=5, start_price=start_price))
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    t1 = threading.Thread(target=writer, args=(100.0,))
    t2 = threading.Thread(target=writer, args=(500.0,))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert not errors, f"thread error: {errors}"
    assert not t1.is_alive() and not t2.is_alive()

    # Final partition is well-formed and readable.
    df = repo._read_sync("AAPL", datetime(2024, 1, 1), datetime(2024, 12, 31))
    assert len(df) == 5
    # Last writer wins on duplicates; either 100.0 or 500.0 should appear
    # depending on scheduling, but the frame must be internally consistent.
    assert df["Close"].iloc[0] in (pytest.approx(100.0), pytest.approx(500.0))
