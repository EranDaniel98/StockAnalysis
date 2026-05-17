"""LightGBM-based composite — opt-in alternative to the hand-tuned weighted sum.

The linear composite (src/scoring/engine.py:calculate_composite_score)
sums analyzer sub-scores with strategy-defined weights. That can't
capture interactions; a LightGBM trained on the same sub-scores can.

This module loads a model file persisted by
``scripts/train_ml_composite.py`` and exposes ``compute_ml_composite``
that maps a sub-scores dict to a single 0-100 score.

The function returns ``None`` when the model file is unavailable or the
required features are missing — callers should fall back to the
linear composite in that case. Never silently swap in a number from
nowhere.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# The trainer (scripts/train_ml_composite.py) hardcodes this order.
# Must match exactly or feature columns will be misaligned at inference.
_FEATURE_COLUMNS: tuple[str, ...] = (
    "technical",
    "fundamental",
    "statistical",
    "pattern",
    "trend",
    "alpha158",
)

# LightGBM Booster is thread-safe for prediction but loading is not.
# Cache at module level + protect the first-load handoff.
_model_cache: dict[str, object] = {}
_cache_lock = threading.Lock()


def _load_model(model_path: str):
    """Load a LightGBM Booster from disk, cached per-path."""
    abs_path = str(Path(model_path).resolve())
    cached = _model_cache.get(abs_path)
    if cached is not None:
        return cached
    with _cache_lock:
        cached = _model_cache.get(abs_path)
        if cached is not None:
            return cached
        # Import LightGBM lazily so the scoring path doesn't pay
        # for it when the ML composite is disabled.
        import lightgbm as lgb

        if not Path(abs_path).exists():
            raise FileNotFoundError(
                f"ML composite model not found at {abs_path}. "
                f"Train one with `uv run python -m scripts.train_ml_composite`."
            )
        booster = lgb.Booster(model_file=abs_path)
        _model_cache[abs_path] = booster
        return booster


def compute_ml_composite(
    sub_scores: dict[str, float],
    *,
    model_path: str = "data/models/ml_composite_v1.lgb",
) -> Optional[float]:
    """Map analyzer sub-scores to a 0-100 ML composite.

    Returns ``None`` when:
      - the model file doesn't exist (training hasn't run yet)
      - the sub-scores dict is missing any required feature
      - prediction raises (caller falls back to linear)

    The raw LightGBM prediction is a forward-return forecast in raw units;
    we map it onto [0, 100] via a cross-sectional rank — but since we
    only have one ticker at a time here, we instead use a per-call
    sigmoid-like rescale anchored to typical training-time prediction
    ranges (set during model fit). The rescale is intentionally coarse:
    the caller treats the score as a ranking signal, not a probability.

    Calibration nuance: this is NOT a probability. The 0-100 value is
    monotonic with predicted forward return, but a 70 here doesn't mean
    "70% chance of going up". Treat it the same way you'd treat the
    linear composite score — purely as a ranking.
    """
    try:
        model = _load_model(model_path)
    except FileNotFoundError as exc:
        logger.debug("ML composite unavailable: %s", exc)
        return None
    except Exception:
        # Defensive: corrupt model file, version mismatch, etc.
        logger.exception("ML composite model load failed")
        return None

    # Build the feature vector in the exact order the trainer used.
    # Missing features → None (caller falls back). We do NOT default
    # missing sub-scores to 50 here — that'd silently make a broken
    # analyzer chain look "neutral" at the ML stage. Real-money
    # constraint.
    feats: list[float] = []
    for col in _FEATURE_COLUMNS:
        v = sub_scores.get(col)
        if v is None:
            logger.debug(
                "ML composite: missing feature %r in sub_scores; "
                "falling back to linear", col,
            )
            return None
        if not isinstance(v, (int, float)) or not np.isfinite(v):
            logger.debug(
                "ML composite: feature %r is %r (non-finite); falling back",
                col, v,
            )
            return None
        feats.append(float(v))

    try:
        raw = float(model.predict(np.array([feats]))[0])
    except Exception:
        logger.exception("ML composite predict failed")
        return None

    # Rescale raw forward-return prediction to 0-100.
    # The trainer fits the model on raw returns (typically in
    # [-0.1, +0.1] for 21-day horizons). Affine-map to [0, 100] using
    # ±10% as the asymmetric tails, then clip. This is a coarse mapping
    # — the caller uses the score as a ranking, not a calibrated prob.
    rescaled = 50.0 + raw * 500.0
    return float(np.clip(rescaled, 0.0, 100.0))


def is_available(model_path: str = "data/models/ml_composite_v1.lgb") -> bool:
    """Return True if the model file exists on disk. Cheap precheck for
    UI / CLI flags that want to know whether to offer the ML option."""
    return Path(model_path).exists()
