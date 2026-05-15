"""Tier-2 audit #15: Parquet writer must convert to UTC before stripping tz.

Pre-fix: ``_normalize_df`` called ``df.index.tz_localize(None)`` directly,
which kept the wall-clock hour and discarded the offset. NY 09:30 EDT
and UTC 13:30 — the SAME moment — became different naive timestamps
(09:30 vs 13:30), so:
  * Concurrent yfinance pulls from different tz contexts produced
    rows that ``_merge_with_existing`` saw as distinct → 2 rows per bar.
  * OR worse, two bars genuinely 4 hours apart in wall-clock time
    collided when one was UTC and one was NY local, silently dropping
    the older one.

After: convert to UTC first, then strip. Naive-UTC is the storage
convention for the OHLCV partitions.
"""

from __future__ import annotations

import pandas as pd

from src.storage.parquet_ohlcv import _normalize_df


def _ohlcv_frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0] * len(index),
            "High": [101.0] * len(index),
            "Low": [99.0] * len(index),
            "Close": [100.5] * len(index),
            "Volume": [1_000_000] * len(index),
        },
        index=index,
    )


def test_naive_input_passes_through_unchanged():
    """Naive index in → naive index out (no conversion happens)."""
    idx = pd.date_range("2024-01-02 13:30:00", periods=3, freq="D")
    df = _ohlcv_frame(idx)
    out = _normalize_df(df)
    assert out.index.tz is None
    # Same timestamps as input.
    assert (out.index == idx).all()


def test_utc_input_strips_to_same_naive_timestamps():
    """UTC index in → naive UTC out (timestamp values unchanged)."""
    idx = pd.date_range("2024-01-02 13:30:00", periods=3, freq="D", tz="UTC")
    df = _ohlcv_frame(idx)
    out = _normalize_df(df)
    assert out.index.tz is None
    expected = pd.DatetimeIndex(["2024-01-02 13:30", "2024-01-03 13:30", "2024-01-04 13:30"])
    assert (out.index == expected).all()


def test_ny_input_converts_to_utc_before_strip():
    """The keystone: NY 09:30 EDT must land as naive 13:30 (UTC offset
    applied) — pre-fix it landed as naive 09:30 (wall-clock preserved)."""
    # 2024-07-02 is summer → America/New_York = UTC-04:00 (EDT).
    idx = pd.DatetimeIndex(
        ["2024-07-02 09:30:00", "2024-07-03 09:30:00", "2024-07-05 09:30:00"]
    ).tz_localize("America/New_York")
    df = _ohlcv_frame(idx)
    out = _normalize_df(df)
    assert out.index.tz is None
    # 09:30 EDT = 13:30 UTC. After the fix the naive index reads 13:30.
    expected_naive_hours = [13, 13, 13]
    assert list(out.index.hour) == expected_naive_hours


def test_ny_and_utc_same_moment_produce_same_naive_timestamp():
    """Real-world reproducer: two DataFrames covering the same moment
    in different tz contexts must collapse to the SAME naive timestamp
    after normalization, so a subsequent merge dedupes them as one bar."""
    # Same moment in UTC and NY (winter, so EST = UTC-05:00).
    utc_idx = pd.DatetimeIndex(["2024-01-02 14:30:00"]).tz_localize("UTC")
    ny_idx = pd.DatetimeIndex(["2024-01-02 09:30:00"]).tz_localize("America/New_York")

    df_utc = _normalize_df(_ohlcv_frame(utc_idx))
    df_ny = _normalize_df(_ohlcv_frame(ny_idx))

    # Both must produce the same naive timestamp post-normalization.
    assert df_utc.index[0] == df_ny.index[0]
    # And specifically the UTC-canonical 14:30, NOT NY local 09:30.
    assert df_utc.index[0] == pd.Timestamp("2024-01-02 14:30:00")


def test_pre_fix_bug_no_longer_reproduces():
    """Pre-fix: NY 09:30 EDT and UTC 13:30 became naive 09:30 and 13:30
    respectively — different rows under dedup. After fix: both become
    naive 13:30 → one row after merge. We assert the pair shares an
    index value (the bug's failure surface)."""
    same_moment_ny = pd.DatetimeIndex(
        ["2024-07-02 09:30:00"]
    ).tz_localize("America/New_York")
    same_moment_utc = pd.DatetimeIndex(
        ["2024-07-02 13:30:00"]
    ).tz_localize("UTC")

    out_ny = _normalize_df(_ohlcv_frame(same_moment_ny))
    out_utc = _normalize_df(_ohlcv_frame(same_moment_utc))
    assert out_ny.index[0] == out_utc.index[0]
