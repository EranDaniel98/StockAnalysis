"""Shared scaffolding for ML trainers.

Every trainer (lightgbm, ridge, ffn, …) shares the same orchestration:
walk-forward folds, IC + hit-rate metrics, joblib artifact + sidecar JSON
manifest, and a typed ``TrainResult``. Only the inner ``fit_predict``
step differs.

To plug in a new model: implement a callable matching ``FitPredictFn``
and pass it to ``run_walk_forward``. See ``ridge_trainer.py`` for the
minimal example.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from src.ml.dataset import TrainingMatrix

logger = logging.getLogger(__name__)


@dataclass
class FoldMetrics:
    fold: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    n_train: int
    n_test: int
    ic_pearson: float
    ic_spearman: float
    hit_rate: float


@dataclass
class TrainResult:
    """Everything a caller needs to persist + benchmark a run."""

    model_name: str
    horizon_days: int
    feature_cols: list[str]
    params: dict[str, Any]
    fold_metrics: list[FoldMetrics] = field(default_factory=list)
    train_window_start: str = ""
    train_window_end: str = ""
    final_n_rows: int = 0
    artifact_path: Optional[Path] = None

    @property
    def summary_metrics(self) -> dict[str, float]:
        if not self.fold_metrics:
            return {}
        return {
            "mean_ic_pearson": float(np.mean([f.ic_pearson for f in self.fold_metrics])),
            "mean_ic_spearman": float(
                np.mean([f.ic_spearman for f in self.fold_metrics])
            ),
            "mean_hit_rate": float(np.mean([f.hit_rate for f in self.fold_metrics])),
            "n_folds": float(len(self.fold_metrics)),
            "total_test_rows": float(sum(f.n_test for f in self.fold_metrics)),
        }


def safe_ic(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float, float]:
    """Pearson + Spearman + hit rate. Zeros when degenerate."""
    if len(y_true) < 3:
        return 0.0, 0.0, 0.0
    if np.std(y_pred) == 0 or np.std(y_true) == 0:
        return 0.0, 0.0, 0.0
    pearson = float(np.corrcoef(y_true, y_pred)[0, 1])
    spearman_corr, _ = spearmanr(y_true, y_pred)
    spearman = float(spearman_corr) if not np.isnan(spearman_corr) else 0.0
    hit_rate = float(np.mean(np.sign(y_pred) == np.sign(y_true)))
    return pearson, spearman, hit_rate


def walk_forward_folds(
    df: pd.DataFrame,
    *,
    initial_train_quarters: int = 4,
    train_step_quarters: int = 1,
) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """Expanding-window walk-forward folds.

    Returns (train_start, train_end, test_start, test_end) tuples — test
    windows are one quarter, training set grows by one quarter each step.
    """
    as_of = pd.to_datetime(df["as_of"])
    if as_of.empty:
        return []
    start = as_of.min()
    end = as_of.max()

    folds: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []
    train_start = start
    train_end = train_start + pd.DateOffset(months=3 * initial_train_quarters)
    while train_end < end:
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=3 * train_step_quarters)
        folds.append((train_start, train_end, test_start, min(test_end, end)))
        train_end = test_end
    return folds


class FitPredictFn(Protocol):
    """Each trainer plugs in a function that fits on (X_train, y_train) and
    returns predictions on X_test. The function may close over hyperparams.

    For the *final* retrain on the full window, the same callable is passed
    ``X_test=None``; it must then return its fitted estimator as predictions
    (the orchestrator catches this case and stores the model instead).
    """

    def __call__(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_test: Optional[pd.DataFrame],
    ) -> Any: ...


def _select_features(matrix: TrainingMatrix, *, use_z_scores: bool) -> list[str]:
    """Pick the z-score columns or the raw sub-score columns — never both,
    because they're collinear by construction.

    Narrative features (``sim_*``, ``narrative_skew``, ``has_recent_*``,
    ``narrative_age_days``, ``days_to_filing``) are NEUTRAL with respect
    to the z-vs-raw split — they don't have z-mirrors. Include them in
    both modes."""
    # Narrative columns live in src/ml/dataset.NARRATIVE_FEATURE_COLUMNS;
    # imported lazily to avoid a circular dep at module load.
    from src.ml.dataset import NARRATIVE_FEATURE_COLUMNS

    narrative_set = set(NARRATIVE_FEATURE_COLUMNS)

    if use_z_scores:
        cols = [
            c for c in matrix.feature_cols
            if c.startswith("z_") or c in narrative_set
        ]
    else:
        cols = [
            c for c in matrix.feature_cols
            if (not c.startswith("z_")) or c in narrative_set
        ]
    if not cols:
        raise ValueError("no feature columns selected — check use_z_scores vs matrix")
    return cols


def run_walk_forward(
    matrix: TrainingMatrix,
    *,
    model_name: str,
    fit_predict_fold: FitPredictFn,
    fit_final: Callable[[pd.DataFrame, pd.Series], Any],
    params: dict[str, Any],
    use_z_scores: bool = True,
    artifact_dir: Path | str = "data/models",
    extra_artifact_payload: Optional[dict[str, Any]] = None,
) -> TrainResult:
    """Run walk-forward CV, retrain on full window, persist artifact.

    ``fit_predict_fold`` runs per fold and returns predictions only.
    ``fit_final`` runs once on the full window and returns the estimator
    (or any joblib-serializable handle) that the artifact stores.
    """
    if matrix.df.empty:
        raise ValueError("training matrix is empty; snapshot the feature store first")

    df = matrix.df.copy()
    feature_cols = _select_features(matrix, use_z_scores=use_z_scores)
    label_col = matrix.label_col
    df = df.dropna(subset=feature_cols + [label_col])
    if df.empty:
        raise ValueError(
            "no rows left after dropping NaN — check the snapshot/forward-return join"
        )

    folds = walk_forward_folds(df)
    fold_metrics: list[FoldMetrics] = []
    for i, (ts, te, vs, ve) in enumerate(folds):
        train = df[(df["as_of"] >= ts) & (df["as_of"] < te)]
        test = df[(df["as_of"] >= vs) & (df["as_of"] < ve)]
        if train.empty or test.empty:
            continue
        preds = fit_predict_fold(
            train[feature_cols], train[label_col], test[feature_cols]
        )
        preds_arr = np.asarray(preds, dtype=float)
        pearson, spearman, hit_rate = safe_ic(
            test[label_col].to_numpy(), preds_arr
        )
        fold_metrics.append(
            FoldMetrics(
                fold=i + 1,
                train_start=str(ts.date()),
                train_end=str(te.date()),
                test_start=str(vs.date()),
                test_end=str(ve.date()),
                n_train=len(train),
                n_test=len(test),
                ic_pearson=pearson,
                ic_spearman=spearman,
                hit_rate=hit_rate,
            )
        )
        logger.info(
            "fold %d: train=%d test=%d ic=%.3f rank_ic=%.3f hit=%.3f",
            i + 1, len(train), len(test), pearson, spearman, hit_rate,
        )

    final_estimator = fit_final(df[feature_cols], df[label_col])

    artifact_dir_path = Path(artifact_dir)
    artifact_dir_path.mkdir(parents=True, exist_ok=True)
    ts_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_path = artifact_dir_path / f"{model_name}_{ts_stamp}.joblib"
    payload: dict[str, Any] = {
        "model": final_estimator,
        "feature_cols": feature_cols,
        "horizon_days": matrix.horizon,
        "params": params,
        "model_name": model_name,
    }
    if extra_artifact_payload:
        payload.update(extra_artifact_payload)
    joblib.dump(payload, artifact_path)
    logger.info("wrote artifact: %s", artifact_path)

    # Sidecar JSON manifest for eyeballing without joblib.
    manifest_path = artifact_path.with_suffix(".json")
    manifest_path.write_text(
        json.dumps(
            {
                "model_name": model_name,
                "horizon_days": matrix.horizon,
                "feature_cols": feature_cols,
                "params": _jsonable_params(params),
                "summary_metrics_pearson_ic_mean": (
                    float(np.mean([f.ic_pearson for f in fold_metrics]))
                    if fold_metrics
                    else None
                ),
                "folds": [vars(f) for f in fold_metrics],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return TrainResult(
        model_name=model_name,
        horizon_days=matrix.horizon,
        feature_cols=feature_cols,
        params=params,
        fold_metrics=fold_metrics,
        train_window_start=str(df["as_of"].min().date()),
        train_window_end=str(df["as_of"].max().date()),
        final_n_rows=len(df),
        artifact_path=artifact_path,
    )


def _jsonable_params(params: dict[str, Any]) -> dict[str, Any]:
    """Some params (numpy scalars, paths) trip json.dumps. Coerce."""
    out: dict[str, Any] = {}
    for k, v in params.items():
        if isinstance(v, (int, float, str, bool)) or v is None:
            out[k] = v
        elif isinstance(v, (list, tuple)):
            out[k] = list(v)
        else:
            out[k] = str(v)
    return out
