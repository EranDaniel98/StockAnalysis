"""Train an ML model on the feature store + register the run.

Usage:
    # LightGBM (default), 5-day horizon
    uv run python -m scripts.train_model --model lightgbm --horizon 5

    # Ridge baseline
    uv run python -m scripts.train_model --model ridge --horizon 5

    # FFN with stock + sector embeddings (needs torch + fundamentals fetch)
    uv run python -m scripts.train_model --model ffn --horizon 5
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any

from src.db.session import dispose_engine, get_sessionmaker
from src.ml.dataset import build_training_matrix
from src.ml.feature_store import DEFAULT_FACTOR_SET
from src.ml.models.lightgbm_trainer import train_lightgbm
from src.ml.models.ridge_trainer import train_ridge
from src.ml.registry import register_run

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train_model")


async def _build_ticker_sector_map(tickers: list[str]) -> dict[str, str]:
    """FFN needs ``ticker → sector`` to build the sector embedding. Reuse
    the existing fundamentals fetcher so we share its cache + rate limiting."""
    from src.config_loader import Config
    from src.data.cache import DataCache
    from src.data.fundamentals import FundamentalsFetcher

    cfg = Config()
    cache = DataCache(
        expiry_hours=cfg.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=cfg.get(
            "data", "market_hours_cache_minutes", default=5
        ),
    )
    fetcher = FundamentalsFetcher(cfg, cache)
    funds = fetcher.fetch_batch(tickers)
    return {t: (f.get("sector") or "Unknown") for t, f in funds.items()}


async def _run(args: argparse.Namespace) -> int:
    SessionLocal = get_sessionmaker()
    async with SessionLocal() as session:
        logger.info("assembling training matrix (horizon=%dd)", args.horizon)
        matrix = await build_training_matrix(
            session, horizon=args.horizon, factor_set=args.factor_set
        )

    if matrix.df.empty:
        logger.error(
            "training matrix is empty — backfill factor_snapshots first via "
            "`python -m scripts.snapshot_features`"
        )
        return 2

    logger.info("training matrix: %d rows", len(matrix.df))

    kwargs: dict[str, Any] = {
        "use_z_scores": not args.no_zscores,
        "model_name": args.model_name,
    }
    if args.model == "lightgbm":
        result = train_lightgbm(matrix, **kwargs)
    elif args.model == "ridge":
        result = train_ridge(matrix, **kwargs)
    elif args.model == "ffn":
        from src.ml.models.ffn_trainer import train_ffn

        tickers = sorted(matrix.df["ticker"].unique().tolist())
        ticker_sector_map = await _build_ticker_sector_map(tickers)
        result = train_ffn(matrix, ticker_sector_map=ticker_sector_map, **kwargs)
    else:
        logger.error("unknown model: %s", args.model)
        return 2

    summary = result.summary_metrics
    logger.info("training complete; folds=%d", int(summary.get("n_folds", 0)))
    logger.info("  mean IC (pearson)  = %.4f", summary.get("mean_ic_pearson", 0.0))
    logger.info("  mean IC (spearman) = %.4f", summary.get("mean_ic_spearman", 0.0))
    logger.info("  mean hit rate      = %.4f", summary.get("mean_hit_rate", 0.0))

    async with SessionLocal() as session:
        row = await register_run(
            session, result, factor_set=args.factor_set, notes=args.notes
        )
    logger.info("registered as %s v%d (id=%d)", row.model_name, row.version, row.id)
    return 0


_DEFAULT_MODEL_NAMES = {
    "lightgbm": "lightgbm_v1",
    "ridge": "ridge_v1",
    "ffn": "ffn_v1",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="lightgbm",
                        choices=["lightgbm", "ridge", "ffn"],
                        help="Which trainer to run. Default lightgbm.")
    parser.add_argument("--horizon", type=int, default=5,
                        help="Forward-return horizon in trading days. Default 5.")
    parser.add_argument("--factor-set", default=DEFAULT_FACTOR_SET)
    parser.add_argument("--model-name", default=None,
                        help="Override the registry's model_name. Defaults to "
                             "lightgbm_v1 / ridge_v1 / ffn_v1.")
    parser.add_argument("--no-zscores", action="store_true",
                        help="Train on raw sub-scores instead of cross-sectional z-scores.")
    parser.add_argument("--notes", default=None,
                        help="Free-form text persisted in model_versions.notes.")
    args = parser.parse_args()
    if args.model_name is None:
        args.model_name = _DEFAULT_MODEL_NAMES[args.model]

    async def _go() -> int:
        try:
            return await _run(args)
        finally:
            await dispose_engine()

    sys.exit(asyncio.run(_go()))


if __name__ == "__main__":
    main()
