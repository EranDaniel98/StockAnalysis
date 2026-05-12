"""LightGBM walk-forward trainer.

Thin wrapper over ``src.ml.models._base.run_walk_forward``. Tuning lives
here (``DEFAULT_PARAMS``); orchestration lives in the base module so
ridge/ffn share the same plumbing.
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


def train_lightgbm(
    matrix: TrainingMatrix,
    *,
    use_z_scores: bool = True,
    artifact_dir: Path | str = "data/models",
    model_name: str = "lightgbm_v1",
    params: Optional[dict[str, Any]] = None,
) -> TrainResult:
    import lightgbm as lgb  # local import keeps non-ML callers fast

    resolved_params = {**DEFAULT_PARAMS, **(params or {})}

    def fit_predict(X_train: pd.DataFrame, y_train: pd.Series, X_test):
        model = lgb.LGBMRegressor(**resolved_params)
        model.fit(X_train, y_train)
        return model.predict(X_test)

    def fit_final(X: pd.DataFrame, y: pd.Series):
        model = lgb.LGBMRegressor(**resolved_params)
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
