"""Exercise lightgbm + ridge + legacy trainers on a synthetic matrix.

The trainers share ``run_walk_forward``; covering one variant covers
most of `_base.py`. Each variant adds 30-100 lines so the parametrize
sweep is cheap.

FFN is skipped here — torch makes it slow and it has its own embedding-
test path in `tests/research/`. The architecture is structurally
identical to the others (a thin wrapper over `run_walk_forward`).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.ml.dataset import TrainingMatrix
from src.ml.models._base import (
    FoldMetrics,
    TrainResult,
    _select_features,
    run_walk_forward,
    safe_ic,
    walk_forward_folds,
)


# ─── pure helpers ───────────────────────────────────────────────────────────


class TestSafeIC:
    def test_signal_recovered_when_pred_matches_label(self) -> None:
        rng = np.random.default_rng(0)
        y_true = rng.normal(size=200)
        # y_pred is a noisy version of y_true → IC ~0.9
        y_pred = y_true + rng.normal(scale=0.2, size=200)
        pearson, spearman, hit_rate = safe_ic(y_true, y_pred)
        assert pearson > 0.9
        assert spearman > 0.9
        assert hit_rate > 0.85

    def test_zero_correlation_for_independent_inputs(self) -> None:
        rng = np.random.default_rng(1)
        y_true = rng.normal(size=200)
        y_pred = rng.normal(size=200)
        pearson, spearman, _hit = safe_ic(y_true, y_pred)
        assert abs(pearson) < 0.2
        assert abs(spearman) < 0.2

    def test_returns_zeros_when_too_few_observations(self) -> None:
        assert safe_ic(np.array([1.0]), np.array([2.0])) == (0.0, 0.0, 0.0)
        assert safe_ic(np.array([1.0, 2.0]), np.array([2.0, 3.0])) == (0.0, 0.0, 0.0)

    def test_returns_zeros_for_constant_predictions(self) -> None:
        y_true = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y_pred = np.array([7.0, 7.0, 7.0, 7.0, 7.0])
        assert safe_ic(y_true, y_pred) == (0.0, 0.0, 0.0)


class TestWalkForwardFolds:
    def test_expanding_window_returns_at_least_one_fold(
        self, synthetic_matrix: TrainingMatrix
    ) -> None:
        folds = walk_forward_folds(synthetic_matrix.df)
        # 18-month window with quarterly retrains after 4 initial quarters
        # → first test fold at month 12, then 3-month steps.
        assert len(folds) >= 1
        for ts, te, vs, ve in folds:
            assert ts < te <= vs < ve
            # Training window grows: train_start stays at the matrix start.
            assert ts == folds[0][0]

    def test_empty_dataframe_returns_no_folds(self) -> None:
        empty = pd.DataFrame({"as_of": pd.to_datetime([])})
        assert walk_forward_folds(empty) == []


class TestSelectFeatures:
    def test_z_score_path_picks_z_columns(self, synthetic_matrix: TrainingMatrix) -> None:
        cols = _select_features(synthetic_matrix, use_z_scores=True)
        assert all(c.startswith("z_") for c in cols)
        assert len(cols) > 0

    def test_raw_path_picks_non_z_columns(self, synthetic_matrix: TrainingMatrix) -> None:
        cols = _select_features(synthetic_matrix, use_z_scores=False)
        assert all(not c.startswith("z_") for c in cols)
        assert len(cols) > 0

    def test_empty_feature_set_raises(self) -> None:
        empty = TrainingMatrix(
            df=pd.DataFrame({"as_of": [], "forward_return": []}),
            horizon=5,
            feature_cols=[],
        )
        with pytest.raises(ValueError, match="no feature columns"):
            _select_features(empty, use_z_scores=True)


# ─── trainer integration ────────────────────────────────────────────────────


def _fake_fit_predict(X_train: pd.DataFrame, y_train: pd.Series, X_test: pd.DataFrame):
    """Mean predictor — every test row gets the train-set mean. Lets us
    test ``run_walk_forward`` without pulling in lightgbm/sklearn."""
    mean = float(y_train.mean())
    return np.full(len(X_test), mean)


def _fake_fit_final(X: pd.DataFrame, y: pd.Series) -> dict:
    return {"mean": float(y.mean())}


def test_run_walk_forward_persists_artifact_and_returns_metrics(
    synthetic_matrix: TrainingMatrix, tmp_artifact_dir
) -> None:
    result = run_walk_forward(
        synthetic_matrix,
        model_name="fake_v1",
        fit_predict_fold=_fake_fit_predict,
        fit_final=_fake_fit_final,
        params={"strategy": "mean"},
        use_z_scores=True,
        artifact_dir=tmp_artifact_dir,
    )

    assert isinstance(result, TrainResult)
    assert result.model_name == "fake_v1"
    assert result.fold_metrics, "expected at least one fold"
    assert result.artifact_path is not None and result.artifact_path.exists()
    # Sidecar manifest written next to the joblib.
    manifest = result.artifact_path.with_suffix(".json")
    assert manifest.exists()
    parsed = json.loads(manifest.read_text(encoding="utf-8"))
    assert parsed["model_name"] == "fake_v1"
    assert isinstance(parsed["folds"], list) and len(parsed["folds"]) == len(
        result.fold_metrics
    )

    # Summary metrics are non-empty when there are folds.
    summary = result.summary_metrics
    assert "mean_ic_pearson" in summary
    assert summary["n_folds"] == float(len(result.fold_metrics))

    # Mean-predictor IC should be ~0 since the predictor has no skill.
    assert abs(summary["mean_ic_pearson"]) < 0.2


def test_run_walk_forward_rejects_empty_matrix(tmp_artifact_dir) -> None:
    empty = TrainingMatrix(
        df=pd.DataFrame(),
        horizon=5,
        feature_cols=["z_technical"],
    )
    with pytest.raises(ValueError, match="training matrix is empty"):
        run_walk_forward(
            empty,
            model_name="x",
            fit_predict_fold=_fake_fit_predict,
            fit_final=_fake_fit_final,
            params={},
            artifact_dir=tmp_artifact_dir,
        )


def test_lightgbm_trainer_learns_synthetic_signal(
    synthetic_matrix: TrainingMatrix, tmp_artifact_dir
) -> None:
    """The synthetic label is 2 × z_technical + noise; a real trainer
    should recover positive IC."""
    from src.ml.models.lightgbm_trainer import train_lightgbm

    result = train_lightgbm(
        synthetic_matrix,
        artifact_dir=tmp_artifact_dir,
        model_name="lightgbm_test",
    )
    assert result.fold_metrics
    # Pearson IC against a label with real signal should be solidly positive.
    assert result.summary_metrics["mean_ic_pearson"] > 0.4
    assert result.artifact_path is not None and result.artifact_path.exists()


def test_ridge_trainer_recovers_signal(
    synthetic_matrix: TrainingMatrix, tmp_artifact_dir
) -> None:
    """Ridge against a linear-in-z_technical label should be near perfect."""
    from src.ml.models.ridge_trainer import train_ridge

    result = train_ridge(
        synthetic_matrix,
        artifact_dir=tmp_artifact_dir,
        model_name="ridge_test",
    )
    assert result.summary_metrics["mean_ic_pearson"] > 0.7


def test_ffn_trainer_runs_and_persists(
    synthetic_matrix: TrainingMatrix, tmp_artifact_dir
) -> None:
    """FFN smoke test — synthetic matrix → train → pickle round-trip.

    Slower than the linear/tree trainers because torch warms up, but
    still under 30s with the conservative DEFAULT_PARAMS. Skipped if
    torch isn't importable so the rest of the suite stays green on a
    skinny install.
    """
    pytest.importorskip("torch", reason="FFN trainer needs PyTorch")
    from src.ml.models.ffn_trainer import train_ffn

    # Map every ticker in the synthetic matrix to the same sector so the
    # embedder has a real category but the trainer doesn't waste epochs
    # learning sector-level signal from 6 tickers.
    ticker_sector_map = {t: "Technology" for t in synthetic_matrix.df["ticker"].unique()}

    result = train_ffn(
        synthetic_matrix,
        ticker_sector_map=ticker_sector_map,
        artifact_dir=tmp_artifact_dir,
        model_name="ffn_test",
        # Trim training so the test stays fast.
        params={"epochs": 8, "patience": 3, "batch_size": 32},
    )
    assert result.fold_metrics
    assert result.artifact_path is not None and result.artifact_path.exists()
    # The artifact must carry the indexer payload so the ensemble can
    # reconstruct embedding lookups at inference time.
    import joblib

    artifact = joblib.load(result.artifact_path)
    assert "indexers" in artifact
    assert "ticker_to_idx" in artifact["indexers"]
    assert "sector_to_idx" in artifact["indexers"]


def test_legacy_strategy_evaluates_without_training(
    synthetic_matrix: TrainingMatrix, tmp_artifact_dir, monkeypatch
) -> None:
    """legacy_v1 is the hand-tuned composite — it doesn't ML-train; it
    runs the fixed estimator over each walk-forward fold."""
    from src.ml import legacy_strategy

    # Bypass the Config YAML — give the loader a stable set of weights.
    def _fake_weights(strategy: str):
        return {
            "technical": 0.3,
            "fundamental": 0.2,
            "pattern": 0.1,
            "statistical": 0.2,
            "trend": 0.1,
            "alpha158": 0.1,
        }

    monkeypatch.setattr(legacy_strategy, "_load_strategy_weights", _fake_weights)

    result = legacy_strategy.build_legacy_train_result(
        synthetic_matrix,
        strategy="swing_trading",
        artifact_dir=tmp_artifact_dir,
        model_name="legacy_test",
    )
    assert result.model_name == "legacy_test"
    assert result.fold_metrics
    # Raw sub-scores are random noise (no z-scoring), so IC ~ 0. We just
    # check the pipeline ran end-to-end and persisted an artifact.
    assert result.artifact_path is not None and result.artifact_path.exists()
    # n_train is 0 in legacy folds (no actual training step).
    assert all(f.n_train == 0 for f in result.fold_metrics)
