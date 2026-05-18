"""VIX-percentile regime gate tests.

The 2026-05-18 IC regime report showed fundamental's IC degrades 3.5x
in high_vix; this gate ships the implementation, the tests fix the
contract.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from src.factors.vix_regime import (
    DEFAULT_CUTOFF,
    DEFAULT_WINDOW,
    is_calm,
    vix_percentile_series,
)


def _vix_series(values: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    """Synthetic VIX DataFrame indexed by consecutive business days."""
    start_ts = pd.Timestamp(start)
    idx = pd.bdate_range(start=start_ts, periods=len(values))
    return pd.DataFrame({"Close": values}, index=idx)


def test_vix_percentile_returns_unit_interval() -> None:
    values = list(range(1, 261))  # 260 distinct ascending values
    df = _vix_series(values)
    pct = vix_percentile_series(df, window=252)
    valid = pct.dropna()
    assert not valid.empty
    assert valid.min() >= 0.0
    assert valid.max() <= 1.0


def test_vix_percentile_first_window_minus_one_is_nan() -> None:
    df = _vix_series([10.0] * 260)
    pct = vix_percentile_series(df, window=252)
    assert pct.iloc[:251].isna().all()
    assert pct.iloc[251:].notna().all()


def test_is_calm_blocks_when_vix_in_top_quintile() -> None:
    # First 250 calm (VIX ~12), then a spike to 35 on day 251.
    values = [12.0] * 250 + [35.0] * 10
    df = _vix_series(values)
    spike_date = df.index[-1]
    assert is_calm(df, spike_date, cutoff=0.80) is False


def test_is_calm_returns_true_for_low_vol_days() -> None:
    # Last 10 days are the LOWEST values in the window so percentile rank
    # is near zero — clearly below the 0.80 cutoff.
    values = list(range(260, 0, -1))  # 260 down to 1; latest = 1 (lowest)
    values = [float(v) for v in values]
    df = _vix_series(values)
    last_date = df.index[-1]
    assert is_calm(df, last_date, cutoff=0.80) is True


def test_is_calm_defaults_calm_when_no_history() -> None:
    df = _vix_series([12.0] * 50)
    # Window is 252 but only 50 bars exist — series has NaN at the end.
    last_date = df.index[-1]
    assert is_calm(df, last_date, window=252) is True


def test_is_calm_accepts_series_input() -> None:
    series = pd.Series(
        [12.0] * 250 + [40.0] * 5,
        index=pd.bdate_range("2024-01-01", periods=255),
        name="Close",
    )
    spike_date = series.index[-1]
    assert is_calm(series, spike_date) is False


def test_default_constants_match_doc() -> None:
    # The defaults are documented; pin them so a future change to one
    # without a doc update is caught in CI rather than in production.
    assert DEFAULT_WINDOW == 252
    assert DEFAULT_CUTOFF == 0.80


def test_vix_percentile_empty_input() -> None:
    df = _vix_series([])
    pct = vix_percentile_series(df)
    assert pct.empty
