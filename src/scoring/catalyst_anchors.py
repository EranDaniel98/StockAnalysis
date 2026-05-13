"""Catalyst anchor library for narrative similarity scoring.

This module defines the seed library of catalyst phrases used to
represent a filing's narrative as a fixed-length feature vector
(cosine similarity to each anchor). Combined with the insider-cluster
detector, the resulting features become candidates for the ML
ensemble (Phase 4).

The polarity labels (``bullish`` / ``bearish``) are **descriptive**,
not **prescriptive** — they describe the event polarity (e.g., a
guidance raise is a bullish event), not its causal effect on returns.
The downstream model is free to learn that "insider buy + bearish
catalyst" is actually a contrarian-conviction signal, etc.

Design choices:
  * Phrases are kept short and dense — these are SEMANTIC anchors, not
    keyword filters. A short noun-phrase rich in canonical terminology
    embeds tighter than a verbose sentence.
  * The model is pinned to ``sentence-transformers/all-MiniLM-L6-v2``
    — the same model used to embed ``filings_corpus`` chunks, so the
    cosine similarities are directly comparable.
  * Five-and-five split is a starting point. Day-1 eyeball test will
    show whether any phrases are too similar to each other (cluster
    redundancy) or fail to hit obvious examples (coverage gaps).

The library is intentionally code-as-data rather than YAML for day 1.
Migration to ``config/catalyst_anchors.yaml`` is a decision-point at
the end of the eyeball test — see task #136.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np


CatalystPolarity = Literal["bullish", "bearish"]


@dataclass(frozen=True)
class CatalystAnchor:
    """A single named catalyst phrase used for narrative-similarity
    features. ``key`` is the snake_case identifier used as a column
    name in the downstream feature store; ``phrase`` is what we
    actually embed."""

    key: str
    phrase: str
    polarity: CatalystPolarity


# Seed library — 5 bullish + 5 bearish. Order is stable so column
# indices in the feature vector are reproducible across runs.
ANCHORS: tuple[CatalystAnchor, ...] = (
    # ───────────── bullish events ─────────────
    CatalystAnchor(
        key="buyback_authorization",
        phrase=(
            "stock buyback share repurchase program authorization "
            "common stock repurchases announced"
        ),
        polarity="bullish",
    ),
    CatalystAnchor(
        key="guidance_raised",
        phrase=(
            "raised fiscal year guidance revenue outlook upgraded "
            "earnings per share guidance increase"
        ),
        polarity="bullish",
    ),
    CatalystAnchor(
        key="product_approval",
        phrase=(
            "FDA approval product launch clearance regulatory "
            "milestone new product commercialization"
        ),
        polarity="bullish",
    ),
    CatalystAnchor(
        key="acquisition_announced",
        phrase=(
            "strategic acquisition definitive agreement merger "
            "consolidation transaction closing announced"
        ),
        polarity="bullish",
    ),
    CatalystAnchor(
        key="major_contract_win",
        phrase=(
            "multi-year contract partnership agreement major "
            "customer commercial expansion strategic alliance"
        ),
        polarity="bullish",
    ),
    # ───────────── bearish events ─────────────
    CatalystAnchor(
        key="going_concern",
        phrase=(
            "going concern doubt material weakness liquidity "
            "debt covenant violation financial distress"
        ),
        polarity="bearish",
    ),
    CatalystAnchor(
        key="executive_departure",
        phrase=(
            "departure resignation chief executive officer chief "
            "financial officer separation termination immediate"
        ),
        polarity="bearish",
    ),
    CatalystAnchor(
        key="litigation_settlement",
        phrase=(
            "lawsuit settlement class action litigation regulatory "
            "investigation SEC enforcement subpoena"
        ),
        polarity="bearish",
    ),
    CatalystAnchor(
        key="guidance_lowered",
        phrase=(
            "lowered fiscal year guidance revenue outlook reduced "
            "earnings per share guidance withdrawn fiscal year"
        ),
        polarity="bearish",
    ),
    CatalystAnchor(
        key="restructuring_layoffs",
        phrase=(
            "restructuring workforce reduction layoffs impairment "
            "charge facility closure cost reduction plan"
        ),
        polarity="bearish",
    ),
)


def anchor_keys() -> tuple[str, ...]:
    """Stable order of feature columns. ``sim_<key>`` is the column
    name in the feature store."""
    return tuple(a.key for a in ANCHORS)


def anchors_by_polarity(polarity: CatalystPolarity) -> tuple[CatalystAnchor, ...]:
    return tuple(a for a in ANCHORS if a.polarity == polarity)


_embedding_cache: np.ndarray | None = None


def embed_anchors() -> np.ndarray:
    """Embed all anchor phrases with the same sentence-transformers
    model used by ``filings_corpus``. Returns an (n_anchors, 384)
    L2-normalized float32 array — cosine similarity against an
    embedded chunk is just a dot product.

    Cached at module scope; calling this repeatedly is free after the
    first call. The model load itself is cached by
    ``src.research_agent.rag.embedder``.
    """
    global _embedding_cache
    if _embedding_cache is not None:
        return _embedding_cache
    from src.research_agent.rag.embedder import embed_texts

    phrases = [a.phrase for a in ANCHORS]
    _embedding_cache = embed_texts(phrases)
    return _embedding_cache


def similarities_to_anchors(chunk_embedding: np.ndarray) -> dict[str, float]:
    """Given a single L2-normalized chunk embedding (384-dim), return
    ``{anchor_key: cosine_similarity}`` for all anchors. Inputs are
    expected to be already normalized — that's the contract of
    ``embed_texts`` (``normalize_embeddings=True``)."""
    if chunk_embedding.ndim != 1 or chunk_embedding.shape[0] != 384:
        raise ValueError(
            f"expected 1-D 384-dim vector, got shape {chunk_embedding.shape}"
        )
    anchors_matrix = embed_anchors()
    sims = anchors_matrix @ chunk_embedding.astype(np.float32)
    return {a.key: float(s) for a, s in zip(ANCHORS, sims)}
