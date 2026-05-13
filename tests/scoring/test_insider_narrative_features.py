"""Tests for src.scoring.insider_narrative_features.compute_features.

Pure function over a numpy array of chunk embeddings — no DB, no
embedder calls (we manufacture synthetic vectors that exercise the
math directly).

The embedder model only loads when ``embed_anchors`` is called; we
let that happen once at module-import time (cached in
``catalyst_anchors._embedding_cache``) and reuse it across tests.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.scoring.catalyst_anchors import (
    ANCHORS,
    anchors_by_polarity,
    embed_anchors,
)
from src.scoring.insider_narrative_features import (
    NarrativeFeatures,
    compute_features,
)


@pytest.fixture(scope="module")
def anchor_matrix() -> np.ndarray:
    """Cached anchor embeddings — loaded once per test module."""
    return embed_anchors()


class TestEmptyInput:
    def test_no_chunks_returns_zero_sims_and_none_aggregates(self) -> None:
        result = compute_features(np.zeros((0, 384), dtype=np.float32))
        # Per-anchor sims are 0.0 (so we can still write them to NOT NULL
        # columns if we choose), but aggregates are None to distinguish
        # "no filing" from "filing with low similarity to every anchor".
        assert all(v == 0.0 for v in result.similarities.values())
        assert result.top_bullish_anchor is None
        assert result.top_bullish_sim is None
        assert result.top_bearish_anchor is None
        assert result.top_bearish_sim is None
        assert result.narrative_skew is None


class TestShapeValidation:
    def test_wrong_dim_raises(self) -> None:
        with pytest.raises(ValueError, match="384"):
            compute_features(np.zeros((3, 100), dtype=np.float32))

    def test_one_dim_raises(self) -> None:
        with pytest.raises(ValueError):
            compute_features(np.zeros(384, dtype=np.float32))


class TestAnchorSelfMatch:
    """If we feed the anchor's own embedding back in, that anchor
    should win with similarity ~1.0."""

    def test_buyback_anchor_self_match(self, anchor_matrix: np.ndarray) -> None:
        # Find the anchor index for buyback_authorization
        keys = [a.key for a in ANCHORS]
        idx = keys.index("buyback_authorization")
        chunk_emb = anchor_matrix[idx:idx + 1]  # (1, 384)
        result = compute_features(chunk_emb)
        # Self-cosine should be ~1.0 (anchors are L2-normalized)
        assert result.similarities["buyback_authorization"] == pytest.approx(1.0, abs=1e-5)
        assert result.top_bullish_anchor == "buyback_authorization"
        assert result.top_bullish_sim == pytest.approx(1.0, abs=1e-5)

    def test_executive_departure_anchor_self_match(self, anchor_matrix: np.ndarray) -> None:
        keys = [a.key for a in ANCHORS]
        idx = keys.index("executive_departure")
        result = compute_features(anchor_matrix[idx:idx + 1])
        assert result.similarities["executive_departure"] == pytest.approx(1.0, abs=1e-5)
        assert result.top_bearish_anchor == "executive_departure"
        # narrative_skew = bull - bear. When the chunk IS the bearish
        # anchor, bear ~1.0 → skew should be negative.
        assert result.narrative_skew is not None
        assert result.narrative_skew < 0


class TestMaxAggregation:
    """The aggregation across chunks is max — boilerplate chunks
    shouldn't pull down high-similarity chunks."""

    def test_max_across_chunks_picks_strongest(self, anchor_matrix: np.ndarray) -> None:
        # Chunk 0: zero vector (low similarity to all anchors)
        # Chunk 1: exactly the buyback anchor (similarity 1.0 to it)
        # Chunk 2: zero vector
        keys = [a.key for a in ANCHORS]
        idx = keys.index("buyback_authorization")
        chunks = np.stack(
            [
                np.zeros(384, dtype=np.float32),
                anchor_matrix[idx],
                np.zeros(384, dtype=np.float32),
            ]
        )
        result = compute_features(chunks)
        # The max picks up chunk 1's perfect match — boilerplate chunks
        # don't dilute it.
        assert result.similarities["buyback_authorization"] == pytest.approx(1.0, abs=1e-5)

    def test_max_does_not_double_count(self, anchor_matrix: np.ndarray) -> None:
        """Two identical chunks shouldn't push similarity above 1.0
        — that's just a max-aggregation safety check."""
        keys = [a.key for a in ANCHORS]
        idx = keys.index("guidance_raised")
        chunks = np.stack([anchor_matrix[idx], anchor_matrix[idx]])
        result = compute_features(chunks)
        assert result.similarities["guidance_raised"] <= 1.0 + 1e-5


class TestPolaritySegmentation:
    """top_bullish vs top_bearish split correctly."""

    def test_polarity_picks_correct_subset(self, anchor_matrix: np.ndarray) -> None:
        # Build a chunk that's the average of two same-polarity anchors:
        # buyback (bullish) + guidance_raised (bullish). Both bullish
        # anchors should rank high, no bearish anchor should win bullish.
        keys = [a.key for a in ANCHORS]
        i_b = keys.index("buyback_authorization")
        i_g = keys.index("guidance_raised")
        avg = (anchor_matrix[i_b] + anchor_matrix[i_g]) / 2
        avg = avg / np.linalg.norm(avg)  # re-normalize
        result = compute_features(avg[None, :])

        bullish_keys = {a.key for a in anchors_by_polarity("bullish")}
        bearish_keys = {a.key for a in anchors_by_polarity("bearish")}
        assert result.top_bullish_anchor in bullish_keys
        assert result.top_bearish_anchor in bearish_keys

    def test_narrative_skew_sign_matches_polarity(self, anchor_matrix: np.ndarray) -> None:
        # Chunk = bullish anchor → skew should be positive
        keys = [a.key for a in ANCHORS]
        i_pos = keys.index("buyback_authorization")
        pos = compute_features(anchor_matrix[i_pos][None, :])
        assert pos.narrative_skew is not None
        assert pos.narrative_skew > 0

        # Chunk = bearish anchor → skew should be negative
        i_neg = keys.index("going_concern")
        neg = compute_features(anchor_matrix[i_neg][None, :])
        assert neg.narrative_skew is not None
        assert neg.narrative_skew < 0


class TestSimilaritiesContainAllAnchors:
    def test_all_anchor_keys_present(self) -> None:
        """Every anchor in the library shows up in the similarities
        dict — feature-store columns line up with the library
        regardless of input."""
        result = compute_features(np.zeros((1, 384), dtype=np.float32))
        for anchor in ANCHORS:
            assert anchor.key in result.similarities


class TestReturnType:
    def test_returns_dataclass(self) -> None:
        result = compute_features(np.zeros((1, 384), dtype=np.float32))
        assert isinstance(result, NarrativeFeatures)
