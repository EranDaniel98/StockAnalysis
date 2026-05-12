"""LightGBM walk-forward trainer.

Trains a gradient-boosted regressor on the (factors → forward return) matrix
emitted by ``src.ml.dataset.build_training_matrix``. Walk-forward folds
(default: quarterly retrain on an expanding window) keep us honest — every
prediction the model makes uses only data strictly before the trade date.

Metrics per fold:
  - Pearson IC      (signed correlation, the headline number)
  - Spearman IC     (rank correlation; robust to outliers)
  - hit rate        (% predictions in the correct direction)
  - n_train         (rows the fold trained on)
  - n_test          (rows the fold scored)

Final model: retrain on the full window, save to disk, return an in-memory
artifact handle.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from src.ml.dataset import TrainingMatrix

logger = logging.getLogger(__name__)


DEFAULT_PARAMS: dict[str, Any] = {
    "objective": "regression",
    "metric": "rmse",
    "n_estimators": 400,
    "learning_rate": 0.03,
    "num_leaves": 31,
    "max_depth": -1,
    "min_data_in_leaf": 20,
    "feature_fraction": 0.85,
    "bagging_fraction": 0.85,
    "bagging_freq": 5,
    "lambda_l2": 1.0,
    "verbosity": -1,
    "random_state": 42,
}


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
    artifact_path: Path | None = None

    @property
    def summary_metrics(self) -> dict[str, float]:
        """Aggregates over the walk-forward folds — the headline numbers
        a model registry row pins."""
        if not self.fold_metrics:
            return {}
        return {
            "mean_ic_pearson": float(np.mean([f.ic_pearson for f in self.fold_metrics])),
            "mean_ic_spearman": float(
                np.mean([f.ic_spearman for f in self.fold_metrics])
            ),
            "mean_hit_rate": float(np.mean([f.hit_rate for f in self.fold_metrics])),
            "n_folds": float(len(self.fold_metrics)),
            "total_test_rows": float(
                sum(f.n_test for f in self.fold_metrics)
            ),
        }


def _safe_ic(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float, float]:
    """Compute pearson + spearman + hit rate. Returns zeros when the fold
    is degenerate (constant y_pred kills correlation)."""
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
    """Build (train_start, train_end, test_start, test_end) tuples.

    Expanding-window walk-forward — every retrain sees more data than
    the previous one. Test window = one quarter; trains every quarter.
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
        # Expanding window: train_start stays put.
        train_end = test_end
    return folds


def train_lightgbm(
    matrix: TrainingMatrix,
    *,
    use_z_scores: bool = True,
    artifact_dir: Path | str = "data/models",
    model_name: str = "lightgbm_v1",
    params: dict[str, Any] | None = None,
) -> TrainResult:
    """Walk-forward train, then retrain on the full window and persist.

    ``use_z_scores`` swaps the raw sub-score columns for the cross-sectional
    z-score columns — usually the right call for ranking models. Raw values
    are still snapshotted, so a future trainer can choose either.
    """
    import lightgbm as lgb  # local import keeps non-ML callers fast

    if matrix.df.empty:
        raise ValueError("training matrix is empty; snapshot the feature store first")

    df = matrix.df.copy()
    feature_cols = [c for c in matrix.feature_cols if c.startswith("z_")] if use_z_scores else [c for c in matrix.feature_cols if not c.startswith("z_")]
    label_col = matrix.label_col
    df = df.dropna(subset=feature_cols + [label_col])

    if df.empty:
        raise ValueError("no rows left after dropping NaN — check the snapshot/forward-return join")

    params = {**DEFAULT_PARAMS, **(params or {})}
    folds = walk_forward_folds(df)

    fold_metrics: list[FoldMetrics] = []
    for i, (ts, te, vs, ve) in enumerate(folds):
        train_mask = (df["as_of"] >= ts) & (df["as_of"] < te)
        test_mask = (df["as_of"] >= vs) & (df["as_of"] < ve)
        train = df[train_mask]
        test = df[test_mask]
        if train.empty or test.empty:
            continue

        model = lgb.LGBMRegressor(**params)
        model.fit(train[feature_cols], train[label_col])
        preds = model.predict(test[feature_cols])
        pearson, spearman, hit_rate = _safe_ic(
            test[label_col].to_numpy(), np.asarray(preds)
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
            i + 1,
            len(train),
            len(test),
            pearson,
            spearman,
            hit_rate,
        )

    # Final retrain on the full window.
    final_model = lgb.LGBMRegressor(**params)
    final_model.fit(df[feature_cols], df[label_col])

    artifact_dir_path = Path(artifact_dir)
    artifact_dir_path.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_path = artifact_dir_path / f"{model_name}_{ts}.joblib"
    joblib.dump(
        {
            "model": final_model,
            "feature_cols": feature_cols,
            "horizon_days": matrix.horizon,
            "params": params,
        },
        artifact_path,
    )
    logger.info("wrote artifact: %s", artifact_path)

    # Sidecar manifest for human inspection.
    manifest_path = artifact_path.with_suffix(".json")
    manifest_path.write_text(
        json.dumps(
            {
                "model_name": model_name,
                "horizon_days": matrix.horizon,
                "feature_cols": feature_cols,
                "params": params,
                "summary_metrics": {
                    k: v for k, v in {
                        "mean_ic_pearson": (
                            float(np.mean([f.ic_pearson for f in fold_metrics]))
                            if fold_metrics
                            else None
                        ),
                    }.items() if v is not None
                },
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
