"""Tier-2 audit #16: embedding dimension + model fingerprint validation.

Two defects:

1. ``EMBEDDING_DIM=384`` is hardcoded and the pgvector column is
   declared ``Vector(384)``. Swapping ``STOCKNEW_EMBEDDING_MODEL`` to a
   768-d model used to produce 768-d vectors that failed at insert with
   a cryptic per-chunk error. After fix, ``embed_texts`` validates the
   produced shape and raises RuntimeError with operator-readable guidance.

2. ``search_filings`` did NOT filter ``WHERE embedding_model = :model``.
   If two models' chunks ever co-existed in ``filings_corpus``, cosine
   distances between vectors from different embedding spaces would
   return nonsense. After fix the WHERE clause always includes the
   model filter.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from src.research_agent.rag.embedder import EMBEDDING_DIM, embed_texts


def test_embed_texts_raises_on_wrong_dim():
    """Simulate a model swap that produces 768-d vectors. ``embed_texts``
    must raise loudly rather than letting the DB insert fail cryptically
    per-chunk."""
    class _FakeModel:
        def encode(self, texts, **kwargs):
            # 768-d output (e.g. bge-base / mpnet) — does NOT match
            # EMBEDDING_DIM=384.
            return np.random.rand(len(texts), 768).astype(np.float32)

    with patch("src.research_agent.rag.embedder._get_model", return_value=_FakeModel()):
        with pytest.raises(RuntimeError, match="EMBEDDING_DIM"):
            embed_texts(["hello world"])


def test_embed_texts_raises_on_wrong_ndim():
    """If a buggy model returns a 1-D array (one big vector instead of
    per-text), the validation also catches it."""
    class _FakeBuggyModel:
        def encode(self, texts, **kwargs):
            return np.random.rand(384).astype(np.float32)  # 1-D, not 2-D

    with patch("src.research_agent.rag.embedder._get_model", return_value=_FakeBuggyModel()):
        with pytest.raises(RuntimeError):
            embed_texts(["hello world"])


def test_embed_texts_passes_through_correct_dim():
    """Sanity: a model that does produce 384-d returns the vectors
    untouched (after the float32 cast)."""
    class _FakeGoodModel:
        def encode(self, texts, **kwargs):
            return np.random.rand(len(texts), EMBEDDING_DIM).astype(np.float32)

    with patch("src.research_agent.rag.embedder._get_model", return_value=_FakeGoodModel()):
        out = embed_texts(["hello", "world"])
        assert out.shape == (2, EMBEDDING_DIM)
        assert out.dtype == np.float32


def test_search_filings_filters_by_embedding_model():
    """The search query must include WHERE embedding_model = :model.
    We don't need a live DB — just inspect the SQL text built by the
    function. This catches the audit ticket's failure mode: a corpus
    that drifted to mixed-model chunks no longer returns cross-space
    junk."""
    # Read the source to confirm the WHERE clause includes embedding_model.
    # This is a static check rather than a dynamic one because the actual
    # query needs a live pgvector DB, which the unit test suite doesn't run.
    from pathlib import Path

    search_py = Path("src/research_agent/rag/search.py").read_text(encoding="utf-8")
    # The model filter must be in the WHERE clause and ALWAYS applied,
    # not gated behind an optional caller flag.
    assert 'embedding_model = :model' in search_py, (
        "search_filings must always filter by embedding_model — Tier-2 #16. "
        "Without this filter, cross-model corpus contamination returns "
        "nonsense distances."
    )
    # And the EMBEDDING_MODEL import is present so the filter has a
    # value to bind.
    assert 'EMBEDDING_MODEL' in search_py
