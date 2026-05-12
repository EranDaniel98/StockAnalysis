"""Register the hand-tuned composite as a ``legacy_v1`` model.

The existing scoring engine produces a weighted composite from raw
sub-scores using ``config/strategies.yaml`` weights. Wrapping that as
a registered model gives us three things at once:

1. The ensemble can include the hand-tuned strategy as one voice.
2. The drift detector can monitor whether the hand-tuned weights are
   still earning their keep against realized forward returns.
3. The calibration tracker / /ml page treats every model uniformly.

There's no walk-forward "training" here — weights are fixed in YAML.
We synthesize fold-style metrics from a backfill of (snapshot, forward
return) pairs so the registry row carries comparable summary IC numbers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from src.ml.dataset import FACTOR_COLUMNS, TrainingMatrix
from src.ml.models._base import FoldMetrics, TrainResult, safe_ic, walk_forward_folds

logger = logging.getLogger(__name__)


DEFAULT_MODEL_NAME = "legacy_v1"


class LegacyCompositeEstimator:
    """Pure-Python "model" that scores a row as the weighted sum of its
    raw sub-scores. Mirrors ``src.scoring.engine.calculate_composite_score``
    at the linear-combination level — bonuses and consensus scaling aren't
    re-implemented (those are recommendation-layer overlays, not signal)."""

    def __init__(self, weights: dict[str, float]):
        # Normalize so weights always sum to 1 — yaml lets users write 0.20 +
        # 0.35 + 0.05 + 0.30 + 0.10 = 1.0, but trusting that is brittle.
        total = sum(weights.values()) or 1.0
        self.weights = {k: float(v) / total for k, v in weights.items()}
        self.feature_cols = [c for c in FACTOR_COLUMNS if c in self.weights]

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predictions are the weighted composite (0-100 scale). The
        ensemble re-normalizes its members against each other anyway, so
        the absolute scale doesn't matter — only the cross-sectional
        ranking does."""
        accum = np.zeros(len(X), dtype=np.float64)
        for col, w in self.weights.items():
            if col not in X.columns:
                continue
            accum += w * X[col].to_numpy(dtype=np.float64)
        return accum


def _load_strategy_weights(strategy: str) -> dict[str, float]:
    """Read weights from ``config/strategies.yaml`` via the existing
    Config loader. Falls back to equal weights when the strategy lacks
    a sub-score for any analyzer (lets us still register a usable model)."""
    from src.config_loader import Config

    cfg = Config()
    strategies = cfg.get("strategies") or {}
    strat = strategies.get(strategy) or {}
    weights = strat.get("weights") or {}
    out: dict[str, float] = {}
    for col in FACTOR_COLUMNS:
        out[col] = float(weights.get(col, 0.0))
    if not any(out.values()):
        out = {col: 1.0 / len(FACTOR_COLUMNS) for col in FACTOR_COLUMNS}
    return out


def build_legacy_train_result(
    matrix: TrainingMatrix,
    *,
    strategy: str,
    artifact_dir: Path | str = "data/models",
    model_name: str = DEFAULT_MODEL_NAME,
) -> TrainResult:
    """Synthesize a ``TrainResult`` for the hand-tuned composite.

    We don't "train" — we evaluate the fixed estimator over the same
    walk-forward folds the ML trainers use, so the registry row's IC
    numbers are comparable. Comparable, not identical: ML models may
    have peeked at extra signal in z-score columns that the hand-tuned
    composite ignores.
    """
    if matrix.df.empty:
        raise ValueError("training matrix is empty; cannot build legacy registration")

    weights = _load_strategy_weights(strategy)
    estimator = LegacyCompositeEstimator(weights)

    df = matrix.df.copy().dropna(subset=estimator.feature_cols + [matrix.label_col])
    if df.empty:
        raise ValueError("no rows left after dropping NaN feature/label values")

    folds = walk_forward_folds(df)
    fold_metrics: list[FoldMetrics] = []
    for i, (ts, te, vs, ve) in enumerate(folds):
        test = df[(df["as_of"] >= vs) & (df["as_of"] < ve)]
        if test.empty:
            continue
        preds = estimator.predict(test[estimator.feature_cols])
        pearson, spearman, hit = safe_ic(
            test[matrix.label_col].to_numpy(), preds
        )
        fold_metrics.append(
            FoldMetrics(
                fold=i + 1,
                train_start=str(ts.date()),
                train_end=str(te.date()),
                test_start=str(vs.date()),
                test_end=str(ve.date()),
                n_train=0,
                n_test=len(test),
                ic_pearson=pearson,
                ic_spearman=spearman,
                hit_rate=hit,
            )
        )
        logger.info(
            "legacy fold %d: test=%d ic=%.3f rank_ic=%.3f hit=%.3f",
            i + 1, len(test), pearson, spearman, hit,
        )

    artifact_dir_path = Path(artifact_dir)
    artifact_dir_path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_path = artifact_dir_path / f"{model_name}_{stamp}.joblib"
    joblib.dump(
        {
            "model": estimator,
            "feature_cols": estimator.feature_cols,
            "horizon_days": matrix.horizon,
            "params": {"strategy": strategy, "weights": estimator.weights},
            "model_name": model_name,
        },
        artifact_path,
    )

    return TrainResult(
        model_name=model_name,
        horizon_days=matrix.horizon,
        feature_cols=estimator.feature_cols,
        params={"strategy": strategy, "weights": estimator.weights},
        fold_metrics=fold_metrics,
        train_window_start=str(df["as_of"].min().date()),
        train_window_end=str(df["as_of"].max().date()),
        final_n_rows=len(df),
        artifact_path=artifact_path,
    )
