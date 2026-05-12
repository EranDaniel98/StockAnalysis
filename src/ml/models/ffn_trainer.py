"""Small feed-forward net with stock + sector embeddings.

Numeric factors → linear projection. Ticker + sector → small learned
embeddings. Concatenated, two hidden layers, scalar regression head.

The model is deliberately tiny — at the current universe sizes (tens
of tickers, ~1k rows per fold) anything bigger overfits instantly.
Embeddings dominate parameter count, so this is roughly:
  ticker_embed(N, 4) + sector_embed(K, 3) + ~1k weights
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import torch
from torch import nn

from src.ml.dataset import TrainingMatrix
from src.ml.models._base import TrainResult, run_walk_forward

logger = logging.getLogger(__name__)


DEFAULT_PARAMS: dict[str, Any] = {
    "ticker_embed_dim": 4,
    "sector_embed_dim": 3,
    "hidden_dim": 16,
    "dropout": 0.10,
    "lr": 1e-3,
    "weight_decay": 1e-4,
    "epochs": 60,
    "batch_size": 64,
    "patience": 8,
    "random_state": 42,
}


class FFN(nn.Module):
    """Module-scope so joblib can pickle the final fitted model. Constructor
    takes the dimensions explicitly — keeps the trainer pure and lets a
    future caller reconstruct the architecture from the artifact alone."""

    def __init__(
        self,
        *,
        n_features: int,
        n_tickers: int,
        n_sectors: int,
        ticker_embed_dim: int,
        sector_embed_dim: int,
        hidden_dim: int,
        dropout: float,
    ) -> None:
        super().__init__()
        self.ticker_emb = nn.Embedding(n_tickers, ticker_embed_dim)
        self.sector_emb = nn.Embedding(n_sectors, sector_embed_dim)
        self.body = nn.Sequential(
            nn.Linear(n_features + ticker_embed_dim + sector_embed_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, x_num, x_ticker, x_sector):
        te = self.ticker_emb(x_ticker)
        se = self.sector_emb(x_sector)
        x = torch.cat([x_num, te, se], dim=1)
        return self.body(x).squeeze(-1)


@dataclass
class _Indexers:
    """Maps from ticker/sector string → integer index used by Embedding.

    Unknown tickers at inference time map to a reserved 0 index. Same
    for unknown sectors (e.g. when fundamentals miss a value for a
    new ticker).
    """

    ticker_to_idx: dict[str, int]
    sector_to_idx: dict[str, int]
    ticker_sector_map: dict[str, str]

    @property
    def n_tickers(self) -> int:
        return len(self.ticker_to_idx) + 1  # +1 for the unknown slot

    @property
    def n_sectors(self) -> int:
        return len(self.sector_to_idx) + 1

    def encode_tickers(self, tickers: pd.Series) -> np.ndarray:
        return tickers.map(lambda t: self.ticker_to_idx.get(t, 0)).to_numpy(
            dtype=np.int64
        )

    def encode_sectors(self, tickers: pd.Series) -> np.ndarray:
        return tickers.map(
            lambda t: self.sector_to_idx.get(
                self.ticker_sector_map.get(t, "Unknown"), 0
            )
        ).to_numpy(dtype=np.int64)


def _build_indexers(
    df: pd.DataFrame, ticker_sector_map: dict[str, str]
) -> _Indexers:
    tickers = sorted(df["ticker"].unique())
    sectors = sorted(set(ticker_sector_map.values()) | {"Unknown"})
    return _Indexers(
        ticker_to_idx={t: i + 1 for i, t in enumerate(tickers)},  # 0 = unknown
        sector_to_idx={s: i + 1 for i, s in enumerate(sectors)},
        ticker_sector_map=dict(ticker_sector_map),
    )


def train_ffn(
    matrix: TrainingMatrix,
    *,
    ticker_sector_map: dict[str, str],
    use_z_scores: bool = True,
    artifact_dir: Path | str = "data/models",
    model_name: str = "ffn_v1",
    params: Optional[dict[str, Any]] = None,
) -> TrainResult:
    """Train the FFN. ``ticker_sector_map`` is required so the sector
    embedding has stable cardinality across folds — pass the union from
    the full universe at the call site."""
    resolved_params = {**DEFAULT_PARAMS, **(params or {})}
    torch.manual_seed(int(resolved_params["random_state"]))

    # Indexers must be derived from the *full* training matrix, not per
    # fold, so embedding weights line up across folds and inference.
    indexers = _build_indexers(matrix.df, ticker_sector_map)
    n_features = len(
        [c for c in matrix.feature_cols if c.startswith("z_")]
        if use_z_scores
        else [c for c in matrix.feature_cols if not c.startswith("z_")]
    )

    def _new_model() -> FFN:
        return FFN(
            n_features=n_features,
            n_tickers=indexers.n_tickers,
            n_sectors=indexers.n_sectors,
            ticker_embed_dim=int(resolved_params["ticker_embed_dim"]),
            sector_embed_dim=int(resolved_params["sector_embed_dim"]),
            hidden_dim=int(resolved_params["hidden_dim"]),
            dropout=float(resolved_params["dropout"]),
        )

    def _make_loader(
        X: pd.DataFrame,
        y: pd.Series,
        tickers: pd.Series,
        *,
        shuffle: bool,
    ):
        x_num = torch.tensor(X.to_numpy(dtype=np.float32))
        x_tk = torch.tensor(indexers.encode_tickers(tickers))
        x_sc = torch.tensor(indexers.encode_sectors(tickers))
        y_t = torch.tensor(y.to_numpy(dtype=np.float32))
        ds = torch.utils.data.TensorDataset(x_num, x_tk, x_sc, y_t)
        return torch.utils.data.DataLoader(
            ds,
            batch_size=int(resolved_params["batch_size"]),
            shuffle=shuffle,
        )

    def _fit(
        X_train: pd.DataFrame,
        y_train: pd.Series,
        tickers_train: pd.Series,
    ) -> FFN:
        model = _new_model()
        opt = torch.optim.AdamW(
            model.parameters(),
            lr=float(resolved_params["lr"]),
            weight_decay=float(resolved_params["weight_decay"]),
        )
        loss_fn = nn.MSELoss()
        loader = _make_loader(X_train, y_train, tickers_train, shuffle=True)
        best_loss = float("inf")
        bad_epochs = 0
        for epoch in range(int(resolved_params["epochs"])):
            model.train()
            epoch_loss = 0.0
            n_batches = 0
            for x_num, x_tk, x_sc, y in loader:
                opt.zero_grad()
                pred = model(x_num, x_tk, x_sc)
                loss = loss_fn(pred, y)
                loss.backward()
                opt.step()
                epoch_loss += float(loss.item())
                n_batches += 1
            avg = epoch_loss / max(n_batches, 1)
            # Cheap early stopping on training loss — there's no held-out
            # split inside the fold itself; the walk-forward test set
            # already serves as the honest evaluator.
            if avg < best_loss - 1e-4:
                best_loss = avg
                bad_epochs = 0
            else:
                bad_epochs += 1
                if bad_epochs >= int(resolved_params["patience"]):
                    break
        return model

    def _predict(model: "FFN", X: pd.DataFrame, tickers: pd.Series) -> np.ndarray:
        model.eval()
        with torch.no_grad():
            x_num = torch.tensor(X.to_numpy(dtype=np.float32))
            x_tk = torch.tensor(indexers.encode_tickers(tickers))
            x_sc = torch.tensor(indexers.encode_sectors(tickers))
            preds = model(x_num, x_tk, x_sc).cpu().numpy()
        return preds

    # The fit_predict signature in _base hands us the features sub-frame,
    # but it doesn't propagate the ticker column. Closure over `matrix.df`
    # lets us index back into the original to recover tickers — keyed by
    # the feature-frame's index, which run_walk_forward preserves.
    full_df = matrix.df

    def fit_predict_fold(X_train, y_train, X_test):
        tickers_train = full_df.loc[X_train.index, "ticker"]
        tickers_test = full_df.loc[X_test.index, "ticker"]
        model = _fit(X_train, y_train, tickers_train)
        return _predict(model, X_test, tickers_test)

    def fit_final(X, y):
        tickers = full_df.loc[X.index, "ticker"]
        return _fit(X, y, tickers)

    return run_walk_forward(
        matrix,
        model_name=model_name,
        fit_predict_fold=fit_predict_fold,
        fit_final=fit_final,
        params=resolved_params,
        use_z_scores=use_z_scores,
        artifact_dir=artifact_dir,
        extra_artifact_payload={
            "indexers": {
                "ticker_to_idx": indexers.ticker_to_idx,
                "sector_to_idx": indexers.sector_to_idx,
                "ticker_sector_map": indexers.ticker_sector_map,
            },
        },
    )
