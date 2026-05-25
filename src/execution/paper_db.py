"""
Persistence for paper-trading validation.

Three tables:
  recommendations  -- snapshot of every gated recommendation at scan time
  paper_orders     -- Alpaca order(s) submitted for a recommendation
  paper_trades     -- closed-out positions with realized P&L

The DB is intentionally separate from data/cache.db so wiping the analysis
cache never touches the validation history.
"""

import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DB_FILENAME = "paper_trading.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    scan_timestamp TEXT NOT NULL,
    strategy TEXT NOT NULL,
    composite_score REAL NOT NULL,
    action TEXT NOT NULL,
    sub_scores_json TEXT,
    entry_price REAL,
    stop_loss REAL,
    take_profit REAL,
    sector TEXT,
    earnings_in_days INTEGER,
    submitted INTEGER NOT NULL DEFAULT 0,
    skip_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_rec_ticker ON recommendations(ticker);
CREATE INDEX IF NOT EXISTS idx_rec_timestamp ON recommendations(scan_timestamp);

CREATE TABLE IF NOT EXISTS paper_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_id INTEGER NOT NULL,
    alpaca_order_id TEXT NOT NULL UNIQUE,
    client_order_id TEXT,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    submitted_at TEXT NOT NULL,
    status TEXT NOT NULL,
    filled_qty REAL DEFAULT 0,
    filled_price REAL,
    filled_at TEXT,
    take_profit REAL,
    stop_loss REAL,
    FOREIGN KEY (recommendation_id) REFERENCES recommendations(id)
);
CREATE INDEX IF NOT EXISTS idx_orders_rec ON paper_orders(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_orders_alpaca ON paper_orders(alpaca_order_id);
-- Idempotency: same (strategy, ticker, date) -> same client_order_id; uniqueness
-- enforced at DB level so a retry that bypasses Alpaca's check still can't
-- double-write the orders table. Partial index skips legacy NULLs from rows
-- inserted before the client_order_id contract was tightened.
CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_coid
    ON paper_orders(client_order_id)
    WHERE client_order_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_id INTEGER,
    ticker TEXT NOT NULL,
    qty REAL NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    entry_at TEXT NOT NULL,
    exit_at TEXT NOT NULL,
    hold_days INTEGER,
    pnl REAL NOT NULL,
    pnl_pct REAL NOT NULL,
    exit_reason TEXT,
    composite_score REAL,
    FOREIGN KEY (recommendation_id) REFERENCES recommendations(id)
);
CREATE INDEX IF NOT EXISTS idx_trades_ticker ON paper_trades(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_score ON paper_trades(composite_score);

-- review M2: orphan fills. paper_evaluate finds an Alpaca order that
-- our DB doesn't know about (entry submitted somewhere we don't track,
-- or a crash between Alpaca-ack and local INSERT). Pre-fix we silently
-- continue; the position is unrecorded P&L. Post-fix we insert an
-- orphan row, WARN-log, and paper_trade refuses new entries on the
-- same ticker until the orphan is manually resolved.
CREATE TABLE IF NOT EXISTS orphan_fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alpaca_order_id TEXT NOT NULL UNIQUE,
    client_order_id TEXT,
    ticker TEXT NOT NULL,
    side TEXT,
    qty REAL,
    filled_qty REAL,
    filled_price REAL,
    filled_at TEXT,
    status TEXT,
    detected_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_orphans_ticker ON orphan_fills(ticker);
CREATE INDEX IF NOT EXISTS idx_orphans_unresolved
    ON orphan_fills(ticker)
    WHERE resolved_at IS NULL;
"""


class PaperDB:
    def __init__(self, db_path=None):
        if db_path is None:
            project_root = Path(__file__).parent.parent.parent
            data_dir = project_root / "data"
            data_dir.mkdir(exist_ok=True)
            db_path = data_dir / DB_FILENAME
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # -- Recommendations -------------------------------------------------

    def insert_recommendation(self, ticker, strategy, composite_score, action,
                              sub_scores, entry_price, stop_loss, take_profit,
                              sector, earnings_in_days=None,
                              submitted=False, skip_reason=None):
        cur = self._conn.execute(
            """
            INSERT INTO recommendations (
                ticker, scan_timestamp, strategy, composite_score, action,
                sub_scores_json, entry_price, stop_loss, take_profit,
                sector, earnings_in_days, submitted, skip_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticker,
                datetime.now(timezone.utc).isoformat(),
                strategy,
                composite_score,
                action,
                json.dumps(sub_scores or {}),
                entry_price,
                stop_loss,
                take_profit,
                sector,
                earnings_in_days,
                1 if submitted else 0,
                skip_reason,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def mark_recommendation_submitted(self, recommendation_id):
        self._conn.execute(
            "UPDATE recommendations SET submitted = 1, skip_reason = NULL WHERE id = ?",
            (recommendation_id,),
        )
        self._conn.commit()

    # -- Orders ----------------------------------------------------------

    # -- Idempotency: pending → submitted lifecycle (review M1) ---------
    #
    # The bulletproof variant. Pre-fix the only protection against a
    # crash between Alpaca-ack and the local INSERT was Alpaca's 24h
    # duplicate-id check on retry. That works for the simple "process
    # died right before INSERT" case but doesn't tell us WHETHER the
    # original submission actually landed at Alpaca. Now:
    #   1. Before calling Alpaca, insert a PENDING row keyed by COID
    #      (sentinel alpaca_order_id="PENDING:<coid>" preserves the
    #      NOT NULL UNIQUE constraints).
    #   2. Call Alpaca. On success, finalize_pending_order swaps the
    #      sentinel for the real alpaca_order_id.
    #   3. On retry (next paper_trade run with the same COID):
    #        - If status='submitted'+: skip immediately
    #        - If status='pending_submit': query Alpaca by COID
    #            * present at Alpaca -> finalize, no resubmit
    #            * absent at Alpaca -> discard pending, resubmit fresh
    #
    # This eliminates the orphan-at-Alpaca-but-no-DB-row failure mode.

    _PENDING_STATUS = "pending_submit"

    @staticmethod
    def _pending_alpaca_sentinel(coid: str) -> str:
        """Build the sentinel alpaca_order_id used for a pending row.
        Keeps the NOT NULL UNIQUE constraint on alpaca_order_id satisfied
        without inventing nulls."""
        return f"PENDING:{coid}"

    def get_order_by_client_order_id(self, client_order_id: str):
        """Look up an order row by its deterministic COID. Returns the
        full row dict (including status) or None."""
        row = self._conn.execute(
            "SELECT * FROM paper_orders WHERE client_order_id = ?",
            (client_order_id,),
        ).fetchone()
        return dict(row) if row else None

    def insert_pending_order(
        self,
        *,
        recommendation_id: int,
        client_order_id: str,
        ticker: str,
        qty: float,
        take_profit: float,
        stop_loss: float,
    ) -> int:
        """Insert a pending row BEFORE the Alpaca call. The UNIQUE on
        client_order_id (partial index) catches racing retries: a second
        insert with the same COID raises IntegrityError, which the caller
        treats as 'someone else is already submitting this'."""
        cur = self._conn.execute(
            """
            INSERT INTO paper_orders (
                recommendation_id, alpaca_order_id, client_order_id,
                ticker, side, qty, submitted_at, status,
                take_profit, stop_loss
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recommendation_id,
                self._pending_alpaca_sentinel(client_order_id),
                client_order_id,
                ticker,
                "buy",
                qty,
                datetime.now(timezone.utc).isoformat(),
                self._PENDING_STATUS,
                take_profit,
                stop_loss,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def finalize_pending_order(
        self,
        *,
        client_order_id: str,
        alpaca_order_id: str,
        status: str,
        submitted_at: str | None = None,
    ) -> bool:
        """Promote a pending row to fully-submitted by stamping the real
        alpaca_order_id. Returns True iff the row was updated (i.e. a
        pending row with this COID actually existed)."""
        cur = self._conn.execute(
            """
            UPDATE paper_orders
            SET alpaca_order_id = ?,
                status = ?,
                submitted_at = COALESCE(?, submitted_at)
            WHERE client_order_id = ?
              AND status = ?
            """,
            (
                alpaca_order_id,
                status,
                submitted_at,
                client_order_id,
                self._PENDING_STATUS,
            ),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def discard_pending_order(self, client_order_id: str) -> bool:
        """Delete a pending row when Alpaca confirms the original
        submission never landed. Only deletes rows still in the pending
        status — won't accidentally remove a submitted/filled order."""
        cur = self._conn.execute(
            """
            DELETE FROM paper_orders
            WHERE client_order_id = ?
              AND status = ?
            """,
            (client_order_id, self._PENDING_STATUS),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def insert_order(self, recommendation_id, order_dict, take_profit, stop_loss):
        cur = self._conn.execute(
            """
            INSERT INTO paper_orders (
                recommendation_id, alpaca_order_id, client_order_id,
                ticker, side, qty, submitted_at, status,
                take_profit, stop_loss
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recommendation_id,
                order_dict["order_id"],
                order_dict.get("client_order_id"),
                order_dict["ticker"],
                "buy",
                order_dict["qty"],
                order_dict.get("submitted_at") or datetime.now(timezone.utc).isoformat(),
                order_dict.get("status", "submitted"),
                take_profit,
                stop_loss,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_order_fill(self, alpaca_order_id, status, filled_qty, filled_price, filled_at):
        self._conn.execute(
            """
            UPDATE paper_orders
            SET status = ?, filled_qty = ?, filled_price = ?, filled_at = ?
            WHERE alpaca_order_id = ?
            """,
            (status, filled_qty, filled_price, filled_at, alpaca_order_id),
        )
        self._conn.commit()

    def get_order_by_alpaca_id(self, alpaca_order_id):
        row = self._conn.execute(
            "SELECT * FROM paper_orders WHERE alpaca_order_id = ?",
            (alpaca_order_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_open_buy_orders(self):
        """Return all paper_orders for BUY side that have a fill but no closing trade yet."""
        rows = self._conn.execute(
            """
            SELECT po.*, r.composite_score, r.scan_timestamp
            FROM paper_orders po
            LEFT JOIN recommendations r ON po.recommendation_id = r.id
            WHERE po.side = 'buy' AND po.filled_qty > 0
              AND NOT EXISTS (
                SELECT 1 FROM paper_trades pt
                WHERE pt.recommendation_id = po.recommendation_id
              )
            """
        ).fetchall()
        return [dict(r) for r in rows]

    # -- Trades ----------------------------------------------------------

    def insert_trade(self, recommendation_id, ticker, qty, entry_price, exit_price,
                     entry_at, exit_at, exit_reason, composite_score):
        try:
            entry_dt = datetime.fromisoformat(entry_at.replace("Z", "+00:00"))
            exit_dt = datetime.fromisoformat(exit_at.replace("Z", "+00:00"))
            hold_days = (exit_dt - entry_dt).days
        except (ValueError, TypeError):
            hold_days = None
        pnl = (exit_price - entry_price) * qty
        pnl_pct = (exit_price / entry_price - 1) * 100 if entry_price else 0
        cur = self._conn.execute(
            """
            INSERT INTO paper_trades (
                recommendation_id, ticker, qty, entry_price, exit_price,
                entry_at, exit_at, hold_days, pnl, pnl_pct,
                exit_reason, composite_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recommendation_id, ticker, qty, entry_price, exit_price,
                entry_at, exit_at, hold_days, pnl, pnl_pct,
                exit_reason, composite_score,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_all_trades(self):
        rows = self._conn.execute(
            "SELECT * FROM paper_trades ORDER BY exit_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_summary_counts(self):
        recs = self._conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0]
        submitted = self._conn.execute(
            "SELECT COUNT(*) FROM recommendations WHERE submitted = 1"
        ).fetchone()[0]
        orders = self._conn.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0]
        trades = self._conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        orphans = self._conn.execute(
            "SELECT COUNT(*) FROM orphan_fills WHERE resolved_at IS NULL"
        ).fetchone()[0]
        return {
            "recommendations": recs,
            "submitted": submitted,
            "orders": orders,
            "closed_trades": trades,
            "unresolved_orphans": orphans,
        }

    # -- Orphan fills (review M2) ----------------------------------------
    #
    # An "orphan" is an Alpaca order our local DB doesn't know about.
    # paper_evaluate.reconcile inserts orphans when it walks Alpaca's
    # fill list and hits an order that get_order_by_alpaca_id returns
    # None for. paper_trade.run then refuses to submit ANY new entry
    # for a ticker that has unresolved orphans — better to skip a
    # trade than to stack on top of an unrecorded position.

    def insert_orphan_fill(
        self,
        *,
        alpaca_order_id: str,
        client_order_id: str | None,
        ticker: str,
        side: str | None,
        qty: float | None,
        filled_qty: float | None,
        filled_price: float | None,
        filled_at: str | None,
        status: str | None,
    ) -> int | None:
        """Insert an orphan. Idempotent on alpaca_order_id — re-detecting
        the same orphan returns None (the DB UNIQUE constraint enforces
        single-row-per-broker-order)."""
        try:
            cur = self._conn.execute(
                """
                INSERT INTO orphan_fills (
                    alpaca_order_id, client_order_id, ticker, side, qty,
                    filled_qty, filled_price, filled_at, status, detected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alpaca_order_id, client_order_id, ticker, side, qty,
                    filled_qty, filled_price, filled_at, status,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            # already recorded — keep the original detected_at intact
            return None

    def get_orphan_tickers(self) -> set[str]:
        """Tickers with at least one unresolved orphan. paper_trade reads
        this once per run and refuses entries for any ticker in the set."""
        rows = self._conn.execute(
            "SELECT DISTINCT ticker FROM orphan_fills WHERE resolved_at IS NULL"
        ).fetchall()
        return {r["ticker"] for r in rows}

    def list_orphans(self, *, include_resolved: bool = False) -> list[dict]:
        """List orphan rows for CLI / dashboard surfaces. Unresolved
        first by default."""
        if include_resolved:
            sql = "SELECT * FROM orphan_fills ORDER BY resolved_at IS NULL DESC, detected_at DESC"
        else:
            sql = "SELECT * FROM orphan_fills WHERE resolved_at IS NULL ORDER BY detected_at DESC"
        return [dict(r) for r in self._conn.execute(sql).fetchall()]

    def resolve_orphan(
        self, alpaca_order_id: str, note: str = "manually resolved"
    ) -> bool:
        """Operator-driven clear. Returns True iff a row was updated."""
        cur = self._conn.execute(
            """
            UPDATE orphan_fills
            SET resolved_at = ?, resolution_note = ?
            WHERE alpaca_order_id = ? AND resolved_at IS NULL
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                note,
                alpaca_order_id,
            ),
        )
        self._conn.commit()
        return cur.rowcount > 0
