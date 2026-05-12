"""Shared synthetic fixtures for ml/ tests.

A real TrainingMatrix needs ~6 quarters of weekly snapshots × multiple
tickers so walk-forward CV has at least one fold to evaluate. We
synthesize one with a deterministic seed so every test sees the same
data and the trainers produce reproducible numbers.

The label has a real (but small) correlation with one feature so the
trainers' IC is non-zero — otherwise the tests can't distinguish a
working trainer from a broken one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ml.dataset import FACTOR_COLUMNS, Z_FACTOR_COLUMNS, TrainingMatrix


@pytest.fixture(scope="session")
def synthetic_matrix() -> TrainingMatrix:
    """6 quarters × weekly × 6 tickers ≈ 470 rows.

    Label = 2 × z_technical + small noise. That gives the trainers
    something to learn — Pearson IC vs z_technical should land around
    0.7+ if the trainer's correctly hooked up.
    """
    rng = np.random.default_rng(seed=42)
    tickers = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    dates = pd.date_range("2024-01-01", "2025-06-30", freq="W-MON")
    n_rows = len(dates) * len(tickers)

    raw = rng.normal(loc=55.0, scale=10.0, size=(n_rows, len(FACTOR_COLUMNS)))
    df = pd.DataFrame(raw, columns=FACTOR_COLUMNS)
    df["ticker"] = np.tile(tickers, len(dates))
    df["as_of"] = np.repeat(dates, len(tickers))

    # Cross-sectional z-score per as_of (matches feature_store semantics).
    for col in FACTOR_COLUMNS:
        z_col = f"z_{col}"
        df[z_col] = (
            df.groupby("as_of")[col]
            .transform(lambda s: (s - s.mean()) / (s.std(ddof=1) or 1.0))
            .fillna(0.0)
        )

    # Label has a real signal in z_technical so IC > 0 if trainer works.
    df["forward_return"] = (
        2.0 * df["z_technical"] + rng.normal(scale=1.0, size=n_rows)
    )
    df["forward_horizon_days"] = 5
    df = df.sort_values(["as_of", "ticker"]).reset_index(drop=True)

    return TrainingMatrix(
        df=df,
        horizon=5,
        feature_cols=FACTOR_COLUMNS + Z_FACTOR_COLUMNS,
    )


@pytest.fixture
def tmp_artifact_dir(tmp_path):
    """Per-test artifact dir so trainers don't pollute data/models/."""
    return tmp_path / "models"
