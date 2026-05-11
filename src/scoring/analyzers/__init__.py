"""Analysis engines moved from src/analysis/ in the Stream B carve.

Each analyzer exposes an `analyze(df, config)` (or analyzer-specific signature)
returning a result dict. Phase 0 leaves the dict return shape unchanged for
parity; ScoringService.batch_analyze wraps the call to lift the dict into
the typed CompositeScore.
"""

from src.scoring.analyzers import (
    alpha158,
    fundamental,
    patterns,
    pead,
    statistical,
    technical,
    trend_detector,
)

__all__ = [
    "alpha158",
    "fundamental",
    "patterns",
    "pead",
    "statistical",
    "technical",
    "trend_detector",
]
