"""LLM-backed sanity check + RAG corpus.

Layout:
  llm_client.py        Anthropic SDK wrapper (timeouts, retries, cost accounting)
  sanity_check.py      Pre-trade LLM verdict (REJECT / CAUTION / OK)
  sanity_gate.py       Batch wrapper for the sanity check — used by paper trade
  sanity_evidence.py   Builds the evidence packet the sanity check reasons over
  rag/                 EDGAR filing embeddings + similarity search (used by
                       src/scoring/catalyst_anchors.py)

The Phase-5 research agent (orchestrator / tools / budget / event_monitor)
was removed in the 2026-05-18 refactor — the agent UI proved low-value vs
CLI for the way the system is actually driven.
"""
