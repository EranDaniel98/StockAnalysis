"""Ridge regression baseline.

A linear baseline is the cheapest, hardest-to-beat first model. If
LightGBM doesn't out-IC ridge on this universe, the gradient-boosted
complexity is unjustified — and the linear coefficients give a
direct read on which sub-scores carry signal.

Z-scoring the features upstream means we can use a plain Ridge here
(no extra StandardScaler step), but we keep a guarded ``with_scaler``
flag for the raw-features case.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from src.ml.dataset import TrainingMatrix
from src.ml.models._base import TrainResult, run_walk_forward

logger = logging.getLogger(__name__)


DEFAULT_PARAMS: dict[str, Any] = {
    "alpha": 1.0,
    "fit_intercept": True,
    "random_state": 42,
}


def train_ridge(
    matrix: TrainingMatrix,
    *,
    use_z_scores: bool = True,
    artifact_dir: Path | str = "data/models",
    model_name: str = "ridge_v1",
    params: Optional[dict[str, Any]] = None,
) -> TrainResult:
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    resolved_params = {**DEFAULT_PARAMS, **(params or {})}

    def _make_pipeline() -> Pipeline:
        steps: list[tuple[str, Any]] = []
        if not use_z_scores:
            # Raw sub-scores are 0-100 but on different distributions per
            # analyzer; scale before fitting.
            steps.append(("scaler", StandardScaler()))
        steps.append(("ridge", Ridge(**resolved_params)))
        return Pipeline(steps)

    def fit_predict(X_train: pd.DataFrame, y_train: pd.Series, X_test):
        model = _make_pipeline()
        model.fit(X_train, y_train)
        return model.predict(X_test)

    def fit_final(X: pd.DataFrame, y: pd.Series):
        model = _make_pipeline()
        model.fit(X, y)
        return model

    return run_walk_forward(
        matrix,
        model_name=model_name,
        fit_predict_fold=fit_predict,
        fit_final=fit_final,
        params=resolved_params,
        use_z_scores=use_z_scores,
        artifact_dir=artifact_dir,
    )
