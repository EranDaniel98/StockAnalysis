"""Tests for the shared earnings-history cache.

The cache must:
1. Round-trip a DatetimeIndex through parquet (the silent-50 PEAD bug
   was this exact round-trip dropping the index).
2. Respect TTL — fresh files reused, stale files refetched.
3. Honor tz: yfinance is tz-aware on some tickers, tz-naive on others;
   the cache must normalize to tz-naive.
4. Return None / skip silently when the network call fails or the
   result is empty (matches the legacy contract of the call sites).
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pandas as pd
import pytest

from src.factors import earnings_cache


def _sample_history(*, with_tz: bool = False) -> pd.DataFrame:
    idx = pd.DatetimeIndex(
        [pd.Timestamp("2026-05-01"), pd.Timestamp("2026-02-01")]
    )
    if with_tz:
        idx = idx.tz_localize("UTC")
    return pd.DataFrame(
        {"Surprise(%)": [12.0, -3.0], "Reported EPS": [1.5, 1.2]},
        index=idx,
    )


def test_round_trip_preserves_datetime_index(tmp_path) -> None:
    df = _sample_history()
    with patch.object(earnings_cache, "_fetch_one", return_value=df):
        first = earnings_cache.load_earnings_history("AAPL", cache_dir=tmp_path)
    assert first is not None
    assert isinstance(first.index, pd.DatetimeIndex)

    # Second call should hit the cache; index must still be Datetime.
    # If we mistakenly returned the parquet-flattened shape, the index
    # would be a RangeIndex and the analyzer would see Unix epoch dates.
    with patch.object(
        earnings_cache, "_fetch_one",
        side_effect=AssertionError("should not refetch"),
    ):
        second = earnings_cache.load_earnings_history("AAPL", cache_dir=tmp_path)
    assert second is not None
    assert isinstance(second.index, pd.DatetimeIndex)
    assert list(second.index) == list(first.index)


def test_tz_aware_input_is_normalized(tmp_path) -> None:
    df = _sample_history(with_tz=True)
    with patch.object(earnings_cache, "_fetch_one", return_value=df):
        out = earnings_cache.load_earnings_history("AAPL", cache_dir=tmp_path)
    assert out is not None
    assert out.index.tz is None


def test_ttl_refetches_when_stale(tmp_path) -> None:
    df = _sample_history()
    with patch.object(earnings_cache, "_fetch_one", return_value=df):
        earnings_cache.load_earnings_history("AAPL", cache_dir=tmp_path)

    cache_path = tmp_path / "AAPL.parquet"
    # Backdate the cache to 48h ago.
    stale_mtime = time.time() - 48 * 3600
    import os
    os.utime(cache_path, (stale_mtime, stale_mtime))

    refreshed = _sample_history()
    refreshed.iloc[0, 0] = 99.0  # marker
    with patch.object(earnings_cache, "_fetch_one", return_value=refreshed) as mock:
        out = earnings_cache.load_earnings_history(
            "AAPL", cache_dir=tmp_path, max_age_hours=24,
        )
    assert mock.called, "stale cache should trigger a refetch"
    assert out is not None
    assert out.iloc[0, 0] == 99.0


def test_none_on_fetch_failure(tmp_path) -> None:
    with patch.object(earnings_cache, "_fetch_one", return_value=None):
        out = earnings_cache.load_earnings_history("XYZQ", cache_dir=tmp_path)
    assert out is None
    # Cache should not have been written for a failed fetch.
    assert not (tmp_path / "XYZQ.parquet").exists()


def test_batch_load_skips_missing(tmp_path) -> None:
    df_good = _sample_history()

    def side_effect(ticker, *, limit, timeout_s):
        return df_good if ticker == "AAPL" else None

    with patch.object(earnings_cache, "_fetch_one", side_effect=side_effect):
        out = earnings_cache.load_earnings_histories(
            ["AAPL", "MISS"], cache_dir=tmp_path, workers=1,
        )
    assert "AAPL" in out
    assert "MISS" not in out


def test_next_earnings_filters_future_only(tmp_path) -> None:
    # Cache an AAPL history with one future, one past event.
    df = pd.DataFrame(
        {"Surprise(%)": [0.0, 0.0]},
        index=pd.DatetimeIndex(
            [pd.Timestamp("2025-01-01"), pd.Timestamp("2099-06-01")]
        ),
    )
    with patch.object(earnings_cache, "_fetch_one", return_value=df):
        out = earnings_cache.load_next_earnings_dates(
            ["AAPL"], cache_dir=tmp_path,
            as_of=pd.Timestamp("2026-05-17"), workers=1,
        )
    assert out == {"AAPL": pd.Timestamp("2099-06-01")}


def test_corrupt_cache_triggers_refetch(tmp_path) -> None:
    cache_path = tmp_path / "AAPL.parquet"
    cache_path.write_bytes(b"not a real parquet file")

    df = _sample_history()
    with patch.object(earnings_cache, "_fetch_one", return_value=df) as mock:
        out = earnings_cache.load_earnings_history(
            "AAPL", cache_dir=tmp_path,
        )
    assert mock.called
    assert out is not None
    assert isinstance(out.index, pd.DatetimeIndex)
