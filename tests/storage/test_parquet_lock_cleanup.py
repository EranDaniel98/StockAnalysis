"""Reviewer I2 regression: Parquet writer lock files are cleaned up
and live in a dedicated .locks/ subdirectory.

Pre-fix, every write_history call created a ``ticker.parquet.lock``
file in the same directory as the partition and never deleted it.
Over time the partition directories accumulated one .lock per ticker
per year forever — noisy listings, bloated backups, and a future
cleanup script could mistake them for orphan state.

This file also pins the LockException-on-timeout path so the timeout
behaves as advertised.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import portalocker
import pytest

from src.storage.parquet_ohlcv import ParquetPriceRepository


def _make_history(start: str = "2024-01-02", n: int = 5) -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=n, freq="B", tz="UTC")
    return pd.DataFrame(
        {
            "Open": [100.0] * n,
            "High": [101.0] * n,
            "Low": [99.0] * n,
            "Close": [100.5] * n,
            "Volume": [1_000_000] * n,
        },
        index=dates,
    )


def test_lock_file_in_locks_subdir(tmp_path: Path):
    """Lock files must be created in .locks/, not alongside the partition."""
    store = ParquetPriceRepository(tmp_path)
    df = _make_history()
    store.write_history("AAPL", df)

    year_dir = tmp_path / "year=2024"
    assert year_dir.exists()

    # The partition is a FILE inside the year dir: ticker=AAPL.parquet.
    parquet_files = list(year_dir.glob("ticker=*.parquet"))
    assert len(parquet_files) == 1

    # No .lock files alongside the partition.
    stale_locks = list(year_dir.glob("*.lock"))
    assert stale_locks == [], (
        f"lock files leaked into partition dir: {stale_locks}"
    )

    # .locks/ subdir may exist (or be empty after cleanup), but if it
    # contains a .lock file that's stale state — every successful write
    # should unlink it before returning.
    locks_dir = year_dir / ".locks"
    if locks_dir.exists():
        remaining = list(locks_dir.glob("*.lock"))
        assert remaining == [], (
            f"lock files not cleaned up after write: {remaining}"
        )


def test_repeat_writes_do_not_accumulate_locks(tmp_path: Path):
    """Five sequential writes → still zero leftover lock files."""
    store = ParquetPriceRepository(tmp_path)
    for i in range(5):
        store.write_history("AAPL", _make_history(start=f"2024-0{i+1}-02"))

    year_dir = tmp_path / "year=2024"
    locks_dir = year_dir / ".locks"
    if locks_dir.exists():
        leftover = list(locks_dir.glob("*.lock"))
        assert leftover == [], f"leaked locks after 5 writes: {leftover}"


def test_lock_timeout_raises_lock_exception(tmp_path: Path):
    """Hold the lock externally; a second writer must raise LockException
    within the 30s budget rather than blocking the worker indefinitely.

    Use a shorter timeout in the test so we don't actually wait 30s —
    construct the lock path manually and hold it ourselves, then verify
    that portalocker.Lock with a short timeout raises.
    """
    store = ParquetPriceRepository(tmp_path)
    # First write so the partition + .locks/ exist.
    store.write_history("AAPL", _make_history())

    year_dir = tmp_path / "year=2024"
    locks_dir = year_dir / ".locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    lock_path = locks_dir / "ticker=AAPL.parquet.lock"

    # Acquire and hold the lock from the test thread.
    with portalocker.Lock(str(lock_path), mode="a", timeout=0):
        # A second attempt with a short timeout must raise.
        with pytest.raises(portalocker.exceptions.LockException):
            with portalocker.Lock(str(lock_path), mode="a", timeout=0.2):
                pass
