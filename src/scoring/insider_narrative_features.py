"""Compute proactive catalyst-narrative features for an insider cluster.

Given:
  * A list of chunks (rows from filings_corpus) for the nearest
    filing — their text and embedding vectors.
  * The catalyst anchor library (src/scoring/catalyst_anchors.py).

Produce:
  * Per-anchor max-cosine-similarity (one float per anchor).
  * Top bullish + top bearish anchor + sim.
  * Narrative skew = top_bullish_sim - top_bearish_sim.

The "max across chunks" aggregation is deliberate. A typical 8-K has
a cover page (mostly boilerplate, near-zero similarity to any
catalyst phrase), an item header chunk ("Item 5.02 — Departure of
Officers"), and one or more content chunks with the actual disclosure.
Taking the max picks up the most-aligned chunk; mean would dilute it
toward the boilerplate.

This module is pure — no DB, no embedder, no SQLAlchemy. Inputs are
numpy arrays + the anchor library. The backfill script glues it to
filings_corpus and inserts rows into insider_narrative_snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from src.scoring.catalyst_anchors import (
    ANCHORS,
    CatalystAnchor,
    embed_anchors,
)


@dataclass(frozen=True)
class NarrativeFeatures:
    """Output of the feature computation. Maps directly onto the
    insider_narrative_snapshots columns (minus cluster metadata + IDs
    which the caller adds)."""

    similarities: dict[str, float]  # anchor_key -> max cosine
    top_bullish_anchor: Optional[str]
    top_bullish_sim: Optional[float]
    top_bearish_anchor: Optional[str]
    top_bearish_sim: Optional[float]
    narrative_skew: Optional[float]
    """top_bullish_sim - top_bearish_sim; None if no chunks given."""


def compute_features(chunk_embeddings: np.ndarray) -> NarrativeFeatures:
    """Compute anchor-similarity features from a stack of chunk
    embeddings.

    ``chunk_embeddings`` is (n_chunks, 384) L2-normalized float32 —
    same shape sentence-transformers produces with
    ``normalize_embeddings=True``. Empty (n_chunks=0) is allowed and
    returns a zero-similarity / None-aggregate result (caller writes
    those as NULL aggregates in the DB).
    """
    if chunk_embeddings.size == 0:
        empty = {a.key: 0.0 for a in ANCHORS}
        return NarrativeFeatures(
            similarities=empty,
            top_bullish_anchor=None,
            top_bullish_sim=None,
            top_bearish_anchor=None,
            top_bearish_sim=None,
            narrative_skew=None,
        )
    if chunk_embeddings.ndim != 2 or chunk_embeddings.shape[1] != 384:
        raise ValueError(
            f"expected (n, 384) chunk embeddings, got {chunk_embeddings.shape}"
        )

    anchors_matrix = embed_anchors()  # (10, 384) normalized
    # (n_chunks, 384) @ (384, 10) → (n_chunks, 10) cosine similarities
    sims_per_chunk = chunk_embeddings.astype(np.float32) @ anchors_matrix.T
    # Max across chunks: the most-aligned chunk represents the filing's
    # signal for each anchor. Boilerplate chunks score low for every
    # anchor and don't affect the max.
    max_sims = sims_per_chunk.max(axis=0)
    similarities = {a.key: float(s) for a, s in zip(ANCHORS, max_sims)}

    # Polarity-segmented top anchors.
    bullish = [a for a in ANCHORS if a.polarity == "bullish"]
    bearish = [a for a in ANCHORS if a.polarity == "bearish"]
    top_b = _top_anchor(bullish, similarities)
    top_r = _top_anchor(bearish, similarities)
    skew = (
        top_b[1] - top_r[1]
        if (top_b is not None and top_r is not None)
        else None
    )
    return NarrativeFeatures(
        similarities=similarities,
        top_bullish_anchor=top_b[0] if top_b else None,
        top_bullish_sim=top_b[1] if top_b else None,
        top_bearish_anchor=top_r[0] if top_r else None,
        top_bearish_sim=top_r[1] if top_r else None,
        narrative_skew=skew,
    )


def _top_anchor(
    anchors: Sequence[CatalystAnchor],
    sims: dict[str, float],
) -> Optional[tuple[str, float]]:
    """Pick the (key, sim) with the highest similarity from
    ``anchors``. None when the input list is empty."""
    if not anchors:
        return None
    best = max(anchors, key=lambda a: sims[a.key])
    return (best.key, sims[best.key])
