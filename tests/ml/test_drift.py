"""Drift detector contract tests.

Doesn't go through the DB — synthesizes the in-memory inputs that
``detect_drift`` needs (a row-like object with a ``metrics`` dict and
a DataFrame of realized predictions vs labels)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from src.ml.drift import (
    DEFAULT_DRIFT_Z_THRESHOLD,
    _training_fold_stats,
    compute_rolling_ic,
    detect_drift,
    spearman_ic,
)


@dataclass
class _StubModelRow:
    """Just enough of the ModelVersion shape for the drift detector."""

    model_name: str
    version: int
    metrics: dict


def _stub_row(fold_ics: list[float]) -> _StubModelRow:
    return _StubModelRow(
        model_name="test_v1",
        version=1,
        metrics={"folds": [{"ic_pearson": x} for x in fold_ics]},
    )


def _realized_df(
    n_recent: int = 20, signal_strength: float = 0.0
) -> pd.DataFrame:
    """Build a (as_of, prediction, forward_return) frame where
    ``signal_strength`` controls how correlated prediction and label are."""
    rng = np.random.default_rng(0)
    dates = pd.date_range("2026-04-01", periods=n_recent, freq="B")
    labels = rng.normal(size=n_recent)
    preds = signal_strength * labels + rng.normal(scale=1.0, size=n_recent)
    return pd.DataFrame(
        {
            "as_of": dates,
            "prediction": preds,
            "forward_return": labels,
        }
    )


class TestTrainingFoldStats:
    def test_returns_zeros_when_no_folds(self) -> None:
        mean, std = _training_fold_stats(_stub_row([]))
        assert mean == 0.0
        assert std == 0.0

    def test_std_is_zero_for_single_fold(self) -> None:
        mean, std = _training_fold_stats(_stub_row([0.05]))
        assert mean == 0.05
        assert std == 0.0

    def test_aggregates_multiple_folds(self) -> None:
        mean, std = _training_fold_stats(_stub_row([0.02, 0.04, 0.06, 0.08]))
        assert abs(mean - 0.05) < 1e-9
        # ddof=1 std of [0.02, 0.04, 0.06, 0.08]
        assert std > 0.02


class TestComputeRollingIC:
    def test_nan_when_dataframe_empty(self) -> None:
        assert np.isnan(compute_rolling_ic(pd.DataFrame()))

    def test_nan_when_missing_required_columns(self) -> None:
        df = pd.DataFrame({"as_of": [pd.Timestamp("2026-04-01")]})
        assert np.isnan(compute_rolling_ic(df))

    def test_nan_when_window_has_too_few_rows(self) -> None:
        df = _realized_df(n_recent=3)  # < 5 rows in window
        assert np.isnan(compute_rolling_ic(df, window_days=30))

    def test_nan_when_predictions_are_constant(self) -> None:
        df = _realized_df(n_recent=20)
        df["prediction"] = 1.0
        assert np.isnan(compute_rolling_ic(df))

    def test_positive_ic_when_pred_correlates_with_label(self) -> None:
        df = _realized_df(n_recent=30, signal_strength=2.0)
        ic = compute_rolling_ic(df, window_days=120)
        assert ic > 0.5


class TestDetectDrift:
    def test_no_drift_when_rolling_ic_matches_training(self) -> None:
        row = _stub_row([0.05, 0.04, 0.06, 0.05])
        # Tight rolling IC ~ training mean → z near 0
        df = _realized_df(n_recent=30, signal_strength=2.0)
        snap = detect_drift(row, df, window_days=120)
        assert not snap.is_drifting
        assert snap.training_ic_mean > 0
        assert snap.window_days == 120

    def test_no_drift_when_training_std_is_zero(self) -> None:
        """Single-fold training → std=0 → drift detector falls back to
        is_drifting=False rather than dividing by zero."""
        row = _stub_row([0.03])
        df = _realized_df(n_recent=30, signal_strength=2.0)
        snap = detect_drift(row, df, window_days=120)
        assert not snap.is_drifting
        assert snap.z_score == 0.0

    def test_drift_fires_when_rolling_drops_well_below_training(self) -> None:
        # Training folds clustered at 0.10 ± 0.01; rolling IC ~ 0 (no signal)
        row = _stub_row([0.10, 0.09, 0.11, 0.10, 0.09])
        df = _realized_df(n_recent=30, signal_strength=0.0)
        snap = detect_drift(row, df, window_days=120)
        assert snap.is_drifting
        assert snap.z_score <= -DEFAULT_DRIFT_Z_THRESHOLD

    def test_nan_rolling_ic_records_as_not_drifting(self) -> None:
        """Insufficient observations → rolling=NaN; detector reports
        zeros instead of treating it as drift."""
        row = _stub_row([0.05, 0.04, 0.06])
        df = _realized_df(n_recent=2)
        snap = detect_drift(row, df, window_days=120)
        assert not snap.is_drifting
        assert snap.rolling_ic == 0.0


class TestSpearmanIC:
    def test_returns_zero_for_too_few_points(self) -> None:
        assert spearman_ic(np.array([1.0, 2.0]), np.array([1.0, 2.0])) == 0.0

    def test_positive_for_correlated_inputs(self) -> None:
        y_true = np.arange(20.0)
        y_pred = np.arange(20.0) + 0.01
        assert spearman_ic(y_true, y_pred) > 0.9
