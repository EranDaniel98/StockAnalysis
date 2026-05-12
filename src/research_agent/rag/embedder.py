"""Local sentence-transformers embedder.

The model is loaded lazily once per process and cached at module scope —
sentence-transformers' SentenceTransformer.__init__ is slow (~1-3s)
because it downloads + memory-maps the weights. Subsequent
``embed_texts`` calls are cheap.

Default model: ``sentence-transformers/all-MiniLM-L6-v2``
  - 384-dim output (matches alembic 0005)
  - ~80MB on disk
  - ~5-15ms per chunk on CPU
  - cosine-similarity-friendly (already L2-normalized by the model)

Upgrade path: bge-large-en-v1.5 (1024-dim, ~430MB, better quality).
Bump alembic vector dim if you swap.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


EMBEDDING_MODEL = os.environ.get(
    "STOCKNEW_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
EMBEDDING_DIM = 384

_model_lock = threading.Lock()
_model = None  # type: ignore[assignment]


def _get_model():
    """Lazy-load the model once per process. Thread-safe."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        # Local import — sentence-transformers pulls torch + transformers
        # at import time, which we don't want to pay in non-RAG callers.
        from sentence_transformers import SentenceTransformer

        logger.info("loading embedding model %s", EMBEDDING_MODEL)
        _model = SentenceTransformer(EMBEDDING_MODEL)
        return _model


def embed_texts(texts: list[str], *, batch_size: int = 32) -> np.ndarray:
    """Return (n, dim) float32 embeddings, cosine-normalized.

    ``normalize_embeddings=True`` so the pgvector cosine index can use
    inner product equivalently — saves a sqrt in the hot path.
    """
    if not texts:
        return np.empty((0, EMBEDDING_DIM), dtype=np.float32)
    model = _get_model()
    vecs = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return vecs.astype(np.float32, copy=False)


def embed_one(text: str) -> np.ndarray:
    """Convenience for single-text queries (the search_filings tool)."""
    return embed_texts([text])[0]
