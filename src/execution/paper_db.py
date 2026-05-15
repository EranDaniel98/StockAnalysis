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
        return {
            "recommendations": recs,
            "submitted": submitted,
            "orders": orders,
            "closed_trades": trades,
        }
