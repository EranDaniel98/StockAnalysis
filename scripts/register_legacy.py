"""Register the hand-tuned composite as a ``legacy_v1`` model.

The strategy's YAML weights become the "trained" estimator; walk-forward
folds get evaluated against realized returns so the registry IC numbers
are directly comparable to lightgbm/ridge/ffn rows.

Usage:
    uv run python -m scripts.register_legacy --strategy swing_trading --horizon 5
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from src.db.session import dispose_engine, get_sessionmaker
from src.ml.dataset import build_training_matrix
from src.ml.feature_store import DEFAULT_FACTOR_SET
from src.ml.legacy_strategy import DEFAULT_MODEL_NAME, build_legacy_train_result
from src.ml.registry import register_run

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("register_legacy")


async def _run(args: argparse.Namespace) -> int:
    SessionLocal = get_sessionmaker()
    async with SessionLocal() as session:
        matrix = await build_training_matrix(
            session, horizon=args.horizon, factor_set=args.factor_set
        )

    if matrix.df.empty:
        logger.error("training matrix is empty; snapshot the feature store first")
        return 2

    result = build_legacy_train_result(
        matrix, strategy=args.strategy, model_name=args.model_name
    )
    summary = result.summary_metrics
    logger.info(
        "legacy strategy=%s: mean_ic=%.4f rank_ic=%.4f hit=%.4f folds=%d",
        args.strategy,
        summary.get("mean_ic_pearson", 0.0),
        summary.get("mean_ic_spearman", 0.0),
        summary.get("mean_hit_rate", 0.0),
        int(summary.get("n_folds", 0)),
    )

    async with SessionLocal() as session:
        row = await register_run(
            session,
            result,
            factor_set=args.factor_set,
            notes=args.notes or f"hand-tuned composite for strategy={args.strategy}",
        )
    logger.info("registered as %s v%d (id=%d)", row.model_name, row.version, row.id)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", default="swing_trading")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--factor-set", default=DEFAULT_FACTOR_SET)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--notes", default=None)
    args = parser.parse_args()

    async def _go() -> int:
        try:
            return await _run(args)
        finally:
            await dispose_engine()

    sys.exit(asyncio.run(_go()))


if __name__ == "__main__":
    main()
