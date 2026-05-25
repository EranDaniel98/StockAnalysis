"""Daily-snapshot persistence for the 30-day paper-validation phase.

Single SQLite file at ``data/validation.db``. The schema is intentionally
thin — one row per (strategy, snapshot_date) — so the comparison script
can read everything in a single query and the operator can eyeball the
table directly when debugging.

What we capture per day:
  * Total account equity from Alpaca (authoritative).
  * Cash, long market value (sanity-check vs equity).
  * Open-position count + tickers (audit trail).
  * Realized + unrealized P&L delta vs starting equity for the phase.
  * Counts of refused submissions (orphan, score_valid, safety_gate) so
    a sudden spike in refusals is visible in the daily diff.
  * Optional free-form ``notes`` for operator annotations.

What we deliberately don't capture:
  * Per-tick equity. Daily granularity is enough; finer adds noise.
  * Per-trade pnl. PaperDB already tracks closed trades. Cross-table
    join at report time is cleaner than denormalizing.

A snapshot is keyed (strategy, snapshot_date). Inserting twice on the
same day for the same strategy UPDATES instead of duplicating —
reruns of validation_daily within one trading day are idempotent.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

_DEFAULT_DB_FILENAME = "validation.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,          -- ISO YYYY-MM-DD
    captured_at TEXT NOT NULL,            -- ISO datetime UTC
    account_equity REAL NOT NULL,
    account_cash REAL,
    long_market_value REAL,
    n_positions INTEGER NOT NULL DEFAULT 0,
    open_tickers_json TEXT,               -- JSON array of position tickers
    cum_pnl_pct REAL,                     -- (equity - starting_equity) / starting_equity * 100
    day_pnl_pct REAL,                     -- (equity - previous_day_equity) / previous_day_equity * 100
    refusals_orphan INTEGER NOT NULL DEFAULT 0,
    refusals_safety_gate INTEGER NOT NULL DEFAULT 0,
    refusals_score_valid INTEGER NOT NULL DEFAULT 0,
    submitted_today INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshots_strategy_date
    ON daily_snapshots(strategy, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON daily_snapshots(snapshot_date);
"""


@dataclass
class DailySnapshot:
    """One day's observation of the paper account state.

    ``cum_pnl_pct`` and ``day_pnl_pct`` are computed by the store at
    insert time so the caller doesn't have to track the phase-start
    equity manually."""

    strategy: str
    snapshot_date: str             # YYYY-MM-DD
    account_equity: float
    account_cash: float | None = None
    long_market_value: float | None = None
    n_positions: int = 0
    open_tickers: list[str] = field(default_factory=list)
    refusals_orphan: int = 0
    refusals_safety_gate: int = 0
    refusals_score_valid: int = 0
    submitted_today: int = 0
    notes: str | None = None


class ValidationStore:
    """Thin sqlite wrapper. Same shape as PaperDB so the patterns are
    consistent across the codebase. Context-manager friendly."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            project_root = Path(__file__).parent.parent.parent
            data_dir = project_root / "data"
            data_dir.mkdir(exist_ok=True)
            db_path = data_dir / _DEFAULT_DB_FILENAME
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ValidationStore":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # -- Snapshots ------------------------------------------------------

    def get_starting_equity(self, strategy: str) -> float | None:
        """Earliest captured equity for the strategy — used as the
        phase-start anchor for cumulative P&L. Returns None when the
        store has no rows for this strategy yet."""
        row = self._conn.execute(
            """
            SELECT account_equity FROM daily_snapshots
            WHERE strategy = ?
            ORDER BY snapshot_date ASC
            LIMIT 1
            """,
            (strategy,),
        ).fetchone()
        return float(row["account_equity"]) if row else None

    def get_previous_snapshot(
        self, strategy: str, snapshot_date: str,
    ) -> dict | None:
        """Most recent snapshot strictly before ``snapshot_date`` for
        the strategy. Used to compute day-over-day P&L."""
        row = self._conn.execute(
            """
            SELECT * FROM daily_snapshots
            WHERE strategy = ? AND snapshot_date < ?
            ORDER BY snapshot_date DESC
            LIMIT 1
            """,
            (strategy, snapshot_date),
        ).fetchone()
        return dict(row) if row else None

    def upsert_snapshot(self, snap: DailySnapshot) -> int:
        """Insert (or replace) today's snapshot. Computes cum_pnl_pct
        and day_pnl_pct from the existing rows so the caller only has
        to pass the raw Alpaca read."""
        starting = self.get_starting_equity(snap.strategy)
        prior = self.get_previous_snapshot(snap.strategy, snap.snapshot_date)

        if starting is not None and starting > 0:
            cum_pnl_pct = (snap.account_equity - starting) / starting * 100.0
        else:
            cum_pnl_pct = 0.0

        if prior is not None and prior["account_equity"] > 0:
            day_pnl_pct = (
                (snap.account_equity - prior["account_equity"])
                / prior["account_equity"] * 100.0
            )
        else:
            day_pnl_pct = 0.0

        captured_at = datetime.now(timezone.utc).isoformat()

        # INSERT OR REPLACE keyed by (strategy, snapshot_date) — same-day
        # reruns overwrite cleanly. The UNIQUE index on those two columns
        # is what makes this safe.
        self._conn.execute(
            """
            INSERT INTO daily_snapshots (
                strategy, snapshot_date, captured_at, account_equity,
                account_cash, long_market_value, n_positions,
                open_tickers_json, cum_pnl_pct, day_pnl_pct,
                refusals_orphan, refusals_safety_gate, refusals_score_valid,
                submitted_today, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(strategy, snapshot_date) DO UPDATE SET
                captured_at = excluded.captured_at,
                account_equity = excluded.account_equity,
                account_cash = excluded.account_cash,
                long_market_value = excluded.long_market_value,
                n_positions = excluded.n_positions,
                open_tickers_json = excluded.open_tickers_json,
                cum_pnl_pct = excluded.cum_pnl_pct,
                day_pnl_pct = excluded.day_pnl_pct,
                refusals_orphan = excluded.refusals_orphan,
                refusals_safety_gate = excluded.refusals_safety_gate,
                refusals_score_valid = excluded.refusals_score_valid,
                submitted_today = excluded.submitted_today,
                notes = excluded.notes
            """,
            (
                snap.strategy, snap.snapshot_date, captured_at,
                snap.account_equity, snap.account_cash,
                snap.long_market_value, snap.n_positions,
                json.dumps(sorted(snap.open_tickers)),
                cum_pnl_pct, day_pnl_pct,
                snap.refusals_orphan, snap.refusals_safety_gate,
                snap.refusals_score_valid, snap.submitted_today,
                snap.notes,
            ),
        )
        self._conn.commit()
        # SQLite's RETURNING isn't always reliable across versions; pull
        # the id back via last_insert_rowid + the lookup keys for clarity.
        row = self._conn.execute(
            "SELECT id FROM daily_snapshots WHERE strategy = ? AND snapshot_date = ?",
            (snap.strategy, snap.snapshot_date),
        ).fetchone()
        return int(row["id"])

    def list_snapshots(self, strategy: str) -> list[dict]:
        """All snapshots for the strategy, chronological."""
        rows = self._conn.execute(
            """
            SELECT * FROM daily_snapshots
            WHERE strategy = ?
            ORDER BY snapshot_date ASC
            """,
            (strategy,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_snapshot(
        self, strategy: str, snapshot_date: str,
    ) -> dict | None:
        row = self._conn.execute(
            """
            SELECT * FROM daily_snapshots
            WHERE strategy = ? AND snapshot_date = ?
            """,
            (strategy, snapshot_date),
        ).fetchone()
        return dict(row) if row else None

    def list_strategies(self) -> list[str]:
        """Distinct strategies the store has snapshots for. Useful for
        the report generator to enumerate without operator input."""
        rows = self._conn.execute(
            "SELECT DISTINCT strategy FROM daily_snapshots ORDER BY strategy"
        ).fetchall()
        return [r["strategy"] for r in rows]
