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

# Device selection. Order of precedence:
#   1. ``STOCKNEW_EMBEDDING_DEVICE`` env var if set ("cuda", "cpu", "mps", ...).
#   2. CUDA if a CUDA-enabled torch build + reachable GPU is present.
#   3. Apple Silicon MPS if available.
#   4. CPU.
# A small wrapper (not just a string) so callers and tests can probe what
# was actually chosen without re-running the detection.
EMBEDDING_DEVICE_OVERRIDE = os.environ.get("STOCKNEW_EMBEDDING_DEVICE")

_model_lock = threading.Lock()
_model = None  # type: ignore[assignment]
_selected_device: str | None = None


def _resolve_device() -> str:
    """Return the best available torch device string ("cuda", "mps", or
    "cpu"). Honors the ``STOCKNEW_EMBEDDING_DEVICE`` override.

    Defensive: an environment that has the cu128 wheel installed but no
    CUDA-capable GPU will still report ``torch.cuda.is_available()``
    correctly as False (it probes the driver, not just the build), so
    we don't need to second-guess it here.
    """
    if EMBEDDING_DEVICE_OVERRIDE:
        return EMBEDDING_DEVICE_OVERRIDE
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        # `torch.backends.mps` is the entry point on Apple Silicon. The
        # attribute can be missing on older builds — guard accordingly.
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def get_embedding_device() -> str:
    """Public accessor for the device string the embedder actually
    loaded onto. Returns ``None``-equivalent ``"cpu"`` until the model
    is first lazy-loaded — call ``_get_model()`` (or any embed function)
    first if you need the post-load value."""
    return _selected_device or _resolve_device()


def _get_model():
    """Lazy-load the model once per process. Thread-safe."""
    global _model, _selected_device
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        # Local import — sentence-transformers pulls torch + transformers
        # at import time, which we don't want to pay in non-RAG callers.
        from sentence_transformers import SentenceTransformer

        device = _resolve_device()
        logger.info("loading embedding model %s on device=%s", EMBEDDING_MODEL, device)
        _model = SentenceTransformer(EMBEDDING_MODEL, device=device)
        _selected_device = device
        return _model


def embed_texts(texts: list[str], *, batch_size: int = 32) -> np.ndarray:
    """Return (n, dim) float32 embeddings, cosine-normalized.

    ``normalize_embeddings=True`` so the pgvector cosine index can use
    inner product equivalently — saves a sqrt in the hot path.

    Tier-2 #16: dimension validation. ``EMBEDDING_DIM=384`` is
    hardcoded and must match both the pgvector column declaration
    (``Vector(384)`` in src/db/models.py) AND the actual model
    output. Pre-fix swapping ``STOCKNEW_EMBEDDING_MODEL`` to a
    768-dim model (e.g. bge-base) would silently produce 768-d
    vectors → insert fails at the DB layer with a cryptic dimension
    error per-chunk. The startup assert below catches the mismatch
    at the first embed call instead.
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
    if vecs.ndim != 2 or vecs.shape[1] != EMBEDDING_DIM:
        raise RuntimeError(
            f"Embedding model {EMBEDDING_MODEL!r} produced shape {vecs.shape} "
            f"but EMBEDDING_DIM is {EMBEDDING_DIM}. The pgvector column is "
            f"declared as Vector({EMBEDDING_DIM}); mixing dims will corrupt "
            f"search results. To swap embedding models, update both "
            f"EMBEDDING_DIM and the Alembic migration for filings_corpus, "
            f"then re-embed every chunk."
        )
    return vecs.astype(np.float32, copy=False)


def embed_one(text: str) -> np.ndarray:
    """Convenience for single-text queries (the search_filings tool)."""
    return embed_texts([text])[0]
