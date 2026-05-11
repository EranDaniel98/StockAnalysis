"""Execution bounded context.

Houses the live-trading + paper-trading orchestration that was previously
spread across src/broker/ and src/paper/ before the Stream B carve.

Submodules:
  alpaca                  — Alpaca REST client (moved from src/broker/alpaca_client.py)
  paper_db                — local SQLite persistence for paper trades (moved from src/paper/db.py)
  paper_trade_service     — submit bracket orders for top scan recs
  paper_evaluate_service  — reconcile closed Alpaca trades, calibrate scores
  sync_service            — pull Alpaca positions into portfolio.yaml
  bootstrap_service       — recreate portfolio.yaml holdings as Alpaca orders
"""

from src.execution.alpaca import AlpacaClient, AlpacaClientError
from src.execution.paper_db import PaperDB

__all__ = [
    "AlpacaClient",
    "AlpacaClientError",
    "PaperDB",
]
