"""Weighted-average ensemble across registered models.

A registered run has metrics. Higher mean IC → higher weight. Negative-IC
models contribute nothing (clamped to zero) — otherwise an actively bad
model would degrade the ensemble.

Inference path:
    rows = await latest_per_name(session)
    ensemble = Ensemble.from_rows(rows)
    preds = ensemble.predict(matrix.df)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.db.models import ModelVersion
from src.ml.registry import LoadedModel, load_artifact

logger = logging.getLogger(__name__)


@dataclass
class MemberPrediction:
    model_name: str
    version: int
    weight: float
    preds: np.ndarray


@dataclass
class EnsembleResult:
    preds: np.ndarray
    """Final blended predictions, aligned to the input row order."""

    members: list[MemberPrediction]
    """Per-model predictions + weights so the UI can show contribution."""


class Ensemble:
    """Holds loaded artifacts + their weights. Construction is async-free
    (cheap) so the API layer can rebuild it per request without paying
    for joblib loads twice in a row."""

    def __init__(self, members: list[tuple[LoadedModel, float]]):
        if not members:
            raise ValueError("ensemble needs at least one member")
        total = sum(w for _, w in members)
        if total <= 0:
            # All members had non-positive IC. Fall back to equal weights —
            # better than a divide-by-zero, but the API surfaces the warning.
            logger.warning("ensemble fell back to equal weights (no positive-IC members)")
            n = len(members)
            self.members = [(m, 1.0 / n) for m, _ in members]
        else:
            self.members = [(m, w / total) for m, w in members]

    @classmethod
    def from_rows(
        cls, rows: list[ModelVersion], *, weight_floor: float = 0.0
    ) -> "Ensemble":
        members: list[tuple[LoadedModel, float]] = []
        for row in rows:
            try:
                loaded = load_artifact(row)
            except FileNotFoundError as e:
                logger.warning("skipping %s v%d — %s", row.model_name, row.version, e)
                continue
            ic = float(
                ((row.metrics or {}).get("summary") or {}).get("mean_ic_pearson", 0.0)
            )
            weight = max(ic, weight_floor)
            members.append((loaded, weight))
        if not members:
            raise RuntimeError("no loadable members for ensemble")
        return cls(members)

    def predict(self, df: pd.DataFrame) -> EnsembleResult:
        """Each member predicts on whatever ``feature_cols`` it was trained
        on; we average the per-row predictions weighted by IC."""
        per_member: list[MemberPrediction] = []
        accum = np.zeros(len(df), dtype=np.float64)
        for loaded, weight in self.members:
            cols = loaded.artifact["feature_cols"]
            preds = _predict_one(loaded, df, cols)
            accum += weight * preds
            per_member.append(
                MemberPrediction(
                    model_name=loaded.row.model_name,
                    version=loaded.row.version,
                    weight=float(weight),
                    preds=preds,
                )
            )
        return EnsembleResult(preds=accum, members=per_member)


def _predict_one(
    loaded: LoadedModel, df: pd.DataFrame, feature_cols: list[str]
) -> np.ndarray:
    """Dispatch on artifact shape — FFN needs ticker + sector lookups,
    everything else (sklearn / lightgbm) just takes the feature matrix."""
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise KeyError(
            f"{loaded.row.model_name} v{loaded.row.version}: input is missing columns {missing}"
        )
    X = df[feature_cols]

    artifact = loaded.artifact
    if "indexers" in artifact:
        return _predict_torch(loaded, df, X)
    model = artifact["model"]
    return np.asarray(model.predict(X), dtype=np.float64)


def _predict_torch(loaded: LoadedModel, df: pd.DataFrame, X: pd.DataFrame) -> np.ndarray:
    import torch

    artifact = loaded.artifact
    indexers = artifact["indexers"]
    ticker_to_idx: dict[str, int] = indexers["ticker_to_idx"]
    sector_to_idx: dict[str, int] = indexers["sector_to_idx"]
    ticker_sector_map: dict[str, str] = indexers["ticker_sector_map"]

    model = artifact["model"]
    model.eval()
    tickers = df["ticker"]
    x_num = torch.tensor(X.to_numpy(dtype=np.float32))
    x_tk = torch.tensor(
        tickers.map(lambda t: ticker_to_idx.get(t, 0)).to_numpy(dtype=np.int64)
    )
    x_sc = torch.tensor(
        tickers.map(
            lambda t: sector_to_idx.get(ticker_sector_map.get(t, "Unknown"), 0)
        ).to_numpy(dtype=np.int64)
    )
    with torch.no_grad():
        preds = model(x_num, x_tk, x_sc).cpu().numpy()
    return np.asarray(preds, dtype=np.float64)
