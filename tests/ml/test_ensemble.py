"""Ensemble blending unit tests.

The DB-backed loader path (``from_rows``) needs Postgres; covered in
integration tests. Here we exercise the in-memory construction logic
and the weighted prediction blend with stub estimators."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from src.ml.ensemble import Ensemble, EnsembleResult
from src.ml.registry import LoadedModel


@dataclass
class _StubRow:
    model_name: str
    version: int


class _StubEstimator:
    """Constant predictor — every input row gets ``value``. Lets us
    verify the weighted average exactly."""

    def __init__(self, value: float) -> None:
        self._value = value

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.full(len(X), self._value, dtype=np.float64)


def _make_member(name: str, value: float, weight: float) -> tuple[LoadedModel, float]:
    """Build a (LoadedModel, weight) pair for Ensemble construction."""
    artifact = {
        "model": _StubEstimator(value),
        "feature_cols": ["z_technical", "z_fundamental"],
        "horizon_days": 5,
        "params": {},
        "model_name": name,
    }
    return (
        LoadedModel(row=_StubRow(model_name=name, version=1), artifact=artifact),
        weight,
    )


def _input_df(n_rows: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "ticker": [f"T{i}" for i in range(n_rows)],
            "z_technical": rng.normal(size=n_rows),
            "z_fundamental": rng.normal(size=n_rows),
        }
    )


class TestEnsembleConstruction:
    def test_rejects_empty_member_list(self) -> None:
        with pytest.raises(ValueError, match="at least one member"):
            Ensemble([])

    def test_normalizes_positive_weights_to_unit_sum(self) -> None:
        members = [
            _make_member("a", 1.0, 0.10),
            _make_member("b", 1.0, 0.30),
        ]
        ens = Ensemble(members)
        weights = [w for _, w in ens.members]
        assert sum(weights) == pytest.approx(1.0)
        # Relative weights preserved: 0.10:0.30 → 0.25:0.75
        assert weights[0] == pytest.approx(0.25)
        assert weights[1] == pytest.approx(0.75)

    def test_falls_back_to_equal_weights_when_total_nonpositive(self) -> None:
        """If every member's IC was zero or negative, we'd otherwise hit
        a divide-by-zero. The fallback gives every member 1/N."""
        members = [
            _make_member("a", 1.0, 0.0),
            _make_member("b", 1.0, -0.05),
            _make_member("c", 1.0, 0.0),
        ]
        ens = Ensemble(members)
        weights = [w for _, w in ens.members]
        assert all(w == pytest.approx(1.0 / 3) for w in weights)


class TestEnsemblePredict:
    def test_weighted_average_of_constant_members(self) -> None:
        # Member A predicts 1.0 with weight 0.25; member B predicts 5.0
        # with weight 0.75. Expected blend = 0.25*1 + 0.75*5 = 4.0.
        members = [
            _make_member("a", 1.0, 0.10),
            _make_member("b", 5.0, 0.30),
        ]
        ens = Ensemble(members)
        df = _input_df(n_rows=4)
        result = ens.predict(df)

        assert isinstance(result, EnsembleResult)
        assert result.preds.shape == (4,)
        assert np.allclose(result.preds, 4.0)

        # Per-member predictions are surfaced verbatim so the UI can
        # show contribution.
        names = [m.model_name for m in result.members]
        assert names == ["a", "b"]
        assert np.allclose(result.members[0].preds, 1.0)
        assert np.allclose(result.members[1].preds, 5.0)

    def test_raises_when_input_is_missing_required_columns(self) -> None:
        members = [_make_member("a", 1.0, 0.5)]
        ens = Ensemble(members)
        # Member trained on z_technical + z_fundamental; input is missing both.
        bad = pd.DataFrame({"ticker": ["X"], "z_technical": [0.0]})
        with pytest.raises(KeyError, match="missing columns"):
            ens.predict(bad)
