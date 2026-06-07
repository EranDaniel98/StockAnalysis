"""Tests for the corporate-action price-artifact guard.

Deterministic synthetic-data tests — no network. They pin the two
artifact signatures (impossible single-day move; multi-month internal
gap) and the per-as_of drop-on-hit boundary.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.price_quality import (
    MAX_DAILY_MOVE,
    drop_price_artifacts,
    has_price_artifact,
)


def _clean(start: str = "2021-01-01", days: int = 400) -> pd.DataFrame:
    idx = pd.bdate_range(start=start, periods=days)
    closes = 100.0 * np.exp(np.cumsum(np.full(days, 0.0005)))
    return pd.DataFrame({"Close": closes}, index=idx)


def test_clean_series_is_not_flagged() -> None:
    assert not has_price_artifact(_clean(), pd.Timestamp("2022-06-01"))


def test_impossible_jump_is_flagged() -> None:
    """A META-style ticker-reuse stitch: $12 -> $184 in one row (+1400%)."""
    df = _clean(days=300)
    df.iloc[150, df.columns.get_loc("Close")] = df["Close"].iloc[149] * (1 + MAX_DAILY_MOVE + 5)
    as_of = df.index[-1]
    assert has_price_artifact(df, as_of)
    prices, dropped = drop_price_artifacts({"META": df, "AAA": _clean()}, as_of)
    assert dropped == ["META"]
    assert "META" not in prices and "AAA" in prices


def test_multi_month_gap_is_flagged() -> None:
    """A delisting / stitched series with a 4-month hole."""
    a = _clean(start="2021-01-01", days=120)
    b = _clean(start="2021-11-01", days=120)
    df = pd.concat([a, b])
    assert has_price_artifact(df, df.index[-1])


def test_drop_on_hit_is_per_as_of() -> None:
    """The artifact only drops the ticker once the jump enters the lookback
    window — before that the (clean) series is kept."""
    df = _clean(start="2021-01-01", days=500)
    jump_pos = 400  # ~2022-07
    df.iloc[jump_pos, df.columns.get_loc("Close")] = df["Close"].iloc[jump_pos - 1] * 20
    before = df.index[jump_pos - 320]   # jump well outside the 280-row lookback
    after = df.index[-1]                # jump inside the lookback
    assert not has_price_artifact(df, before)
    assert has_price_artifact(df, after)
