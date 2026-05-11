"""Compatibility shim — src.paper.* moved to src.execution.* in Stream B.

Mapping:
  src.paper.trader      → src.execution.paper_trade_service
  src.paper.evaluator   → src.execution.paper_evaluate_service
  src.paper.sync        → src.execution.sync_service
  src.paper.bootstrap   → src.execution.bootstrap_service
  src.paper.db          → src.execution.paper_db

Removed in Phase 1 once all callers (currently src/main.py) import from
src.execution directly.
"""

import sys as _sys
import warnings as _warnings

from src.execution import (
    paper_trade_service as trader,
    paper_evaluate_service as evaluator,
    sync_service as sync,
    bootstrap_service as bootstrap,
    paper_db as db,
)

# Register the legacy dotted names so `from src.paper.trader import X` etc.
# resolve. Same pattern as src/analysis/__init__.py (Stream B slice 1).
for _legacy_name, _new_module in (
    ("src.paper.trader", trader),
    ("src.paper.evaluator", evaluator),
    ("src.paper.sync", sync),
    ("src.paper.bootstrap", bootstrap),
    ("src.paper.db", db),
):
    _sys.modules[_legacy_name] = _new_module

_warnings.warn(
    "src.paper is a Phase-0 compatibility shim; import from "
    "src.execution instead. Will be removed in Phase 1.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["trader", "evaluator", "sync", "bootstrap", "db"]
