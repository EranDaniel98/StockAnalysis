"""IC drift detection.

When a model's live IC drifts below its training IC by more than 1.5σ
of the training-fold spread, we treat that as a regime shift and flag it.
The threshold is intentionally permissive — false positives are cheap
(an extra notification), false negatives are expensive (trading a stale
edge).

Rolling 30-day windows are evaluated on (forward_return, ensemble_pred)
joined from realized factor_snapshots + close prices. Caller supplies the
``df`` so we stay agnostic about how predictions were generated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from src.db.models import ModelVersion

logger = logging.getLogger(__name__)


# How much rolling IC must drop vs the *training* fold mean before we call
# it drift. Expressed as multiples of the training-fold std.
DEFAULT_DRIFT_Z_THRESHOLD = 1.5


@dataclass
class DriftSnapshot:
    model_name: str
    version: int
    training_ic_mean: float
    training_ic_std: float
    rolling_ic: float
    z_score: float
    is_drifting: bool
    window_days: int
    n_observations: int


def _training_fold_stats(row: ModelVersion) -> tuple[float, float]:
    """Pull (mean, std) of fold pearson ICs from the registry row's metrics
    column. Std uses ddof=1 to match training-time numbers."""
    metrics = row.metrics or {}
    folds = metrics.get("folds") or []
    if not folds:
        return 0.0, 0.0
    ics = np.array([float(f.get("ic_pearson", 0.0)) for f in folds])
    if len(ics) < 2:
        return float(ics.mean()), 0.0
    return float(ics.mean()), float(ics.std(ddof=1))


def compute_rolling_ic(
    df: pd.DataFrame,
    *,
    pred_col: str = "prediction",
    label_col: str = "forward_return",
    window_days: int = 30,
) -> float:
    """Pearson IC over the last ``window_days`` of (prediction, label) pairs.

    Returns NaN when the window is too small or degenerate. Caller decides
    whether NaN means "skip" or "alert".
    """
    if df.empty or pred_col not in df.columns or label_col not in df.columns:
        return float("nan")
    df = df.dropna(subset=[pred_col, label_col]).copy()
    if df.empty:
        return float("nan")
    df["as_of"] = pd.to_datetime(df["as_of"])
    cutoff = df["as_of"].max() - pd.Timedelta(days=window_days)
    recent = df[df["as_of"] >= cutoff]
    if len(recent) < 5:
        return float("nan")
    if recent[pred_col].std() == 0 or recent[label_col].std() == 0:
        return float("nan")
    return float(np.corrcoef(recent[pred_col], recent[label_col])[0, 1])


def detect_drift(
    row: ModelVersion,
    realized: pd.DataFrame,
    *,
    pred_col: str = "prediction",
    label_col: str = "forward_return",
    window_days: int = 30,
    z_threshold: float = DEFAULT_DRIFT_Z_THRESHOLD,
) -> DriftSnapshot:
    """One snapshot per model. ``realized`` must contain ``as_of``,
    ``ticker``, ``prediction``, and ``forward_return``."""
    training_mean, training_std = _training_fold_stats(row)
    rolling = compute_rolling_ic(
        realized, pred_col=pred_col, label_col=label_col, window_days=window_days
    )

    if np.isnan(rolling) or training_std == 0:
        z = 0.0
        drifting = False
    else:
        # Negative z = worse than training. Positive z = better than training.
        # We only alert on negative drift.
        z = (rolling - training_mean) / training_std
        drifting = z <= -abs(z_threshold)

    return DriftSnapshot(
        model_name=row.model_name,
        version=row.version,
        training_ic_mean=training_mean,
        training_ic_std=training_std,
        rolling_ic=float(rolling) if not np.isnan(rolling) else 0.0,
        z_score=float(z),
        is_drifting=bool(drifting),
        window_days=window_days,
        n_observations=int(len(realized.dropna(subset=[pred_col, label_col]))),
    )


def spearman_ic(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Convenience wrapper; the UI sometimes wants rank-IC alongside the
    Pearson number that drives the drift gate."""
    if len(y_true) < 3:
        return 0.0
    corr, _ = spearmanr(y_true, y_pred)
    return float(corr) if not np.isnan(corr) else 0.0
