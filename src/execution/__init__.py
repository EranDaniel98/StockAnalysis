"""Execution bounded context.

Houses the live-trading + paper-trading orchestration. The factor
pipeline drives live trades through ``scripts.paper_trade_factor_picks``;
the legacy 5-engine ``paper_trade_service`` / ``paper_evaluate_service``
were deleted 2026-05-23.

Submodules:
  alpaca                  — Alpaca REST client
  paper_db                — local SQLite persistence for paper trades
  pre_trade_gates         — drift / sanity / kill-switch gates
  kill_switch             — live-α gate state + evaluation
  sync_service            — pull Alpaca positions into portfolio.yaml
  bootstrap_service       — recreate portfolio.yaml holdings as Alpaca orders
  safety_gates            — global trading-disabled gate
  risk_sizing             — bracket / ATR sizing helpers
"""

from src.execution.alpaca import AlpacaClient, AlpacaClientError
from src.execution.paper_db import PaperDB

__all__ = [
    "AlpacaClient",
    "AlpacaClientError",
    "PaperDB",
]
