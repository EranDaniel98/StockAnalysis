"""Train an ML model on the feature store + register the run.

Usage:
    # LightGBM, 5-day horizon, using cross-sectional z-scores
    uv run python -m scripts.train_model --horizon 5

    # Same but on raw sub-scores (not z-scores)
    uv run python -m scripts.train_model --horizon 5 --no-zscores
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from src.db.session import dispose_engine, get_sessionmaker
from src.ml.dataset import build_training_matrix
from src.ml.feature_store import DEFAULT_FACTOR_SET
from src.ml.models.lightgbm_trainer import train_lightgbm
from src.ml.registry import register_run

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train_model")


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

    result = train_lightgbm(
        matrix,
        use_z_scores=not args.no_zscores,
        model_name=args.model_name,
    )
    summary = result.summary_metrics
    logger.info("training complete; folds=%d", int(summary.get("n_folds", 0)))
    logger.info(
        "  mean IC (pearson)  = %.4f",
        summary.get("mean_ic_pearson", 0.0),
    )
    logger.info(
        "  mean IC (spearman) = %.4f",
        summary.get("mean_ic_spearman", 0.0),
    )
    logger.info(
        "  mean hit rate      = %.4f",
        summary.get("mean_hit_rate", 0.0),
    )

    async with SessionLocal() as session:
        row = await register_run(
            session, result, factor_set=args.factor_set, notes=args.notes
        )
    logger.info("registered as %s v%d (id=%d)", row.model_name, row.version, row.id)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horizon", type=int, default=5,
                        help="Forward-return horizon in trading days. Default 5.")
    parser.add_argument("--factor-set", default=DEFAULT_FACTOR_SET)
    parser.add_argument("--model-name", default="lightgbm_v1")
    parser.add_argument("--no-zscores", action="store_true",
                        help="Train on raw sub-scores instead of cross-sectional z-scores.")
    parser.add_argument("--notes", default=None,
                        help="Free-form text persisted in model_versions.notes.")
    args = parser.parse_args()

    async def _go() -> int:
        try:
            return await _run(args)
        finally:
            await dispose_engine()

    sys.exit(asyncio.run(_go()))


if __name__ == "__main__":
    main()
