"""
Carver-style forecast diversification.

When multiple sub-scores agree on a direction, the composite is genuinely
high-conviction. When they disagree, the composite is the average of
contradicting signals — usually weaker evidence than the headline number
suggests. Carver's "Instrument Diversification Multiplier" formalizes this
for correlated signals; a tractable single-ticker analogue is to scale the
composite's distance from neutral (50) by the *consensus* of the sub-scores.

Two-stage scaling:
1. Consensus confidence = 1 - normalized std of sub-scores
   - All sub-scores cluster (low std) → confidence ~ 1 → composite unchanged
   - Sub-scores disagree (high std) → confidence < 1 → composite pulled toward 50
2. Optional explicit Carver IDM via precomputed correlation matrix (deferred
   until we have multi-ticker historical sub-score panel).
"""

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Empirical reference: sub-scores have std up to ~25 across the 5 engines
# when one signal is at 80 and another at 30. We treat std=20 as "max
# disagreement" → confidence 0; std=0 as full consensus → confidence 1.
MAX_STD_REFERENCE = 20.0


def apply_consensus_scaling(
    composite: float,
    sub_scores: dict[str, float],
    floor: float = 0.4,
    max_std_reference: float = MAX_STD_REFERENCE,
) -> tuple[float, dict]:
    """
    Scale `composite` toward 50 (neutral) by sub-score consensus.

    Args:
        composite: weighted-average composite in [0, 100]
        sub_scores: dict of sub-score values
        floor: minimum confidence multiplier (so even total disagreement keeps
            some signal); default 0.4 = composite never moves more than 60%
            of the way back to neutral
        max_std_reference: std value mapped to confidence=floor (max disagreement)

    Returns:
        (scaled_composite, diagnostics) where diagnostics contains the
        confidence multiplier and the sub-score dispersion.
    """
    if not sub_scores:
        return composite, {"confidence": 1.0, "sub_score_std": 0.0}
    values = np.array([v for v in sub_scores.values() if v is not None], dtype=float)
    if len(values) < 2:
        return composite, {"confidence": 1.0, "sub_score_std": 0.0}

    std = float(values.std(ddof=0))
    # Normalize std to [0, 1]; cap at 1
    normalized_disagreement = min(std / max_std_reference, 1.0)
    confidence = max(floor, 1.0 - normalized_disagreement)

    scaled = 50.0 + (composite - 50.0) * confidence
    return float(scaled), {
        "confidence": round(confidence, 3),
        "sub_score_std": round(std, 2),
    }


def carver_idm(
    sub_score_correlation_matrix: np.ndarray,
    weights: np.ndarray,
) -> float:
    """
    Carver's Instrument Diversification Multiplier:
      IDM = 1 / sqrt(w^T C w)
    where w is normalized weights and C is the sub-score correlation matrix.
    IDM = 1 when signals are perfectly correlated (no diversification),
    > 1 when signals are uncorrelated (signal-strength bonus).

    Use the *inverse* to scale toward neutral if you want diversification to
    REDUCE confidence on correlated signals. (Carver's original applies it to
    *increase* position size on diversified forecasts.)
    """
    w = weights / weights.sum() if weights.sum() > 0 else weights
    quadratic = float(w @ sub_score_correlation_matrix @ w)
    if quadratic <= 0:
        return 1.0
    return 1.0 / np.sqrt(quadratic)
