"""30-day paper-validation harness.

Built around one boring loop: snapshot the Alpaca account daily, persist
to ``data/validation.db``, then at day 30+ diff cumulative live-paper
performance against the minimal_baseline backtest. The diff is the gate
that decides whether real capital advances to Phase 2 of the safety
ladder.

This package owns the snapshot persistence + comparison math. The
scheduling is operator-driven (Windows Task Scheduler / cron / manual);
see scripts/validation_daily.py for the daily entrypoint.
"""

from src.validation.store import (
    DailySnapshot,
    ValidationStore,
)

__all__ = ["DailySnapshot", "ValidationStore"]
