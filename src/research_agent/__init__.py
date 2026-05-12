"""Phase 5 — autonomous research agent.

Layout:
  llm_client.py     thin Anthropic SDK wrapper with timeouts / retries / cost accounting
  budget.py         per-run token + dollar caps
  tools.py          in-process tool registry the agent can call
  orchestrator.py   the agent loop — Anthropic tool-use until done / capped

External users talk to ``orchestrator.run_research(question, session=...)``
which returns a ``ResearchRun`` row populated with the full transcript.
"""
