"""Paper-validation snapshot store.

Persists daily Alpaca account snapshots to ``data/validation.db`` for
later comparison against any chosen backtest baseline. The analyzer-era
Phase-2 capital-safety gate (``scripts/validation_report.py``) was
retired alongside ``minimal_baseline`` in 2026-05-24; this package now
provides only the snapshot/comparison primitives for future callers.
"""

from src.validation.store import (
    DailySnapshot,
    ValidationStore,
)

__all__ = ["DailySnapshot", "ValidationStore"]
