"""Unit tests for src/factors/exposure_scaling.py."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from src.factors.exposure_scaling import (
    DEFAULT_FLOOR,
    DEFAULT_HIGH_THRESHOLD,
    DEFAULT_LOW_THRESHOLD,
    DEFAULT_SMOOTHING_WINDOW,
    exposure_at,
    exposure_from_vix,
    exposure_series,
)


def test_below_low_returns_full_exposure():
    assert exposure_from_vix(15.0) == 1.0
    assert exposure_from_vix(DEFAULT_LOW_THRESHOLD) == 1.0


def test_above_high_returns_floor():
    assert exposure_from_vix(40.0) == DEFAULT_FLOOR
    assert exposure_from_vix(DEFAULT_HIGH_THRESHOLD) == DEFAULT_FLOOR


def test_midpoint_returns_halfway_between_floor_and_one():
    mid = (DEFAULT_LOW_THRESHOLD + DEFAULT_HIGH_THRESHOLD) / 2
    expected = 1.0 - 0.5 * (1.0 - DEFAULT_FLOOR)
    assert math.isclose(exposure_from_vix(mid), expected, abs_tol=1e-9)


def test_linear_ramp_is_monotonic_decreasing():
    values = [15, 18, 20, 22, 25, 28, 30, 35]
    expos = [exposure_from_vix(v) for v in values]
    for a, b in zip(expos, expos[1:]):
        assert a >= b, f"non-monotonic: {a} -> {b}"


def test_invalid_thresholds_raise():
    with pytest.raises(ValueError):
        exposure_from_vix(25, low_threshold=30, high_threshold=20)
    with pytest.raises(ValueError):
        exposure_from_vix(25, floor=1.5)
    with pytest.raises(ValueError):
        exposure_from_vix(25, floor=-0.1)


def test_series_smooths_then_maps():
    # Build a VIX series that ramps from 15 to 35 over 30 days.
    dates = pd.date_range("2024-01-01", periods=30, freq="B")
    vix = pd.Series([15 + (35 - 15) * i / 29 for i in range(30)], index=dates)
    out = exposure_series(vix, smoothing_window=5)
    # First 4 should be NaN.
    assert out.iloc[:4].isna().all()
    # After smoothing kicks in, values should be in [floor, 1].
    valid = out.dropna()
    assert (valid >= DEFAULT_FLOOR - 1e-9).all()
    assert (valid <= 1.0 + 1e-9).all()
    # Trend is non-increasing (smoothed VIX is rising).
    assert valid.is_monotonic_decreasing


def test_exposure_at_defaults_to_full_with_no_data():
    empty = pd.Series([], dtype=float, index=pd.DatetimeIndex([]))
    # No data on or before as_of -> permissive default 1.0.
    assert exposure_at(empty, "2024-01-15") == 1.0


def test_exposure_at_uses_latest_eligible():
    dates = pd.date_range("2024-01-01", periods=30, freq="B")
    # Constant high VIX above smoothing window.
    vix = pd.Series([35.0] * 30, index=dates)
    # as_of well past the smoothing window
    exp = exposure_at(vix, dates[-1], smoothing_window=5)
    assert exp == DEFAULT_FLOOR


def test_custom_thresholds_propagate_through_series():
    dates = pd.date_range("2024-01-01", periods=40, freq="B")
    vix = pd.Series([20.0] * 40, index=dates)
    # Move the low threshold to 25 -- VIX=20 is now WELL below low,
    # should still produce full exposure.
    out = exposure_series(
        vix, smoothing_window=5,
        low_threshold=25.0, high_threshold=40.0, floor=0.1,
    )
    valid = out.dropna()
    assert (valid == 1.0).all()
