"""Phase 5.2 RAG corpus for the research agent.

Pulls 10-K / 10-Q / 8-K filings from EDGAR, strips HTML, chunks,
embeds locally via sentence-transformers, and stores in
``filings_corpus`` for k-NN search.

Local embeddings on purpose: the project is local-only and Anthropic
has no embedding API. ``all-MiniLM-L6-v2`` is 384-dim, ~80MB, fast
enough on CPU for the small universe sizes we care about.
"""

from src.research_agent.rag.embedder import EMBEDDING_MODEL, embed_texts

__all__ = ["EMBEDDING_MODEL", "embed_texts"]
