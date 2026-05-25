"""Polygon bar dicts -> canonical OHLCV frame.

Output contract matches src.storage.parquet_ohlcv._normalize_df: columns
[Open, High, Low, Close, Volume], DatetimeIndex named 'Date', **naive-UTC**
(storage convention; also what factors.momentum's naive ``as_of`` comparison
requires). Daily bars are floored to the session date.
"""

from __future__ import annotations

import pandas as pd

_OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def bars_to_frame(bars: list[dict], *, daily: bool) -> pd.DataFrame:
    """Convert Polygon aggregate bars (o/h/l/c/v/t-ms) to the OHLCV contract.

    ``daily=True`` normalizes the index to midnight (one row per session);
    ``daily=False`` keeps minute/hour resolution.
    """
    if not bars:
        return pd.DataFrame(columns=_OHLCV, index=pd.DatetimeIndex([], name="Date"))
    df = pd.DataFrame(bars)
    # Polygon t is Unix ms. Convert UTC-aware -> naive-UTC (wall clock preserved).
    idx = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_localize(None)
    if daily:
        idx = idx.dt.normalize()
    out = pd.DataFrame(
        {"Open": df["o"], "High": df["h"], "Low": df["l"], "Close": df["c"], "Volume": df["v"]}
    )
    out.index = pd.DatetimeIndex(idx, name="Date")
    return out.sort_index()
