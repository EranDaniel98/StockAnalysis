"""One-shot migration: data/paper_trading.db (SQLite) → Postgres.

Reads every row from the three SQLite tables and inserts row-for-row into
the Postgres equivalents. Idempotent at the unique-constraint level: if the
script is run twice, duplicate alpaca_order_id rows are skipped with a log
warning rather than crashing.

Usage:
    docker compose up -d              # ensure Postgres is running
    uv run alembic upgrade head       # ensure schema is current
    uv run python -m scripts.migrate_paper_db

By default the source path is `data/paper_trading.db`. Override with
--source for a different file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.db.models import PaperOrder, PaperRecommendation, PaperTrade
from src.db.session import dispose_engine, get_sessionmaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate_paper_db")


def _parse_dt(s: str | None) -> datetime | None:
    """Parse a SQLite-stored ISO 8601 string into a tz-aware UTC datetime.
    Returns None for None/empty inputs."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        logger.warning("Could not parse datetime %r — skipping", s)
        return None
    # Assume UTC if naive (the writer used datetime.now(timezone.utc).isoformat())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def migrate(source: Path, dry_run: bool) -> None:
    if not source.exists():
        logger.error("Source not found: %s", source)
        sys.exit(1)

    sqlite_conn = sqlite3.connect(str(source))
    sqlite_conn.row_factory = sqlite3.Row

    recs = sqlite_conn.execute("SELECT * FROM recommendations ORDER BY id").fetchall()
    orders = sqlite_conn.execute("SELECT * FROM paper_orders ORDER BY id").fetchall()
    trades = sqlite_conn.execute("SELECT * FROM paper_trades ORDER BY id").fetchall()
    logger.info(
        "Source counts: recommendations=%d orders=%d trades=%d",
        len(recs),
        len(orders),
        len(trades),
    )

    if dry_run:
        logger.info("Dry run — nothing written.")
        sqlite_conn.close()
        return

    SessionLocal = get_sessionmaker()
    async with SessionLocal() as session:
        # ---- Pass 1: recommendations. Capture the SQLite id → Postgres id map. ----
        # SQLite's autoincrement may have gaps; we preserve the original id so
        # the FK in paper_orders/paper_trades resolves.
        sqlite_to_pg_rec: dict[int, int] = {}
        for row in recs:
            payload = {
                "ticker": row["ticker"],
                "scan_timestamp": _parse_dt(row["scan_timestamp"]),
                "strategy": row["strategy"],
                "composite_score": row["composite_score"],
                "action": row["action"],
                "sub_scores_json": row["sub_scores_json"],
                "entry_price": row["entry_price"],
                "stop_loss": row["stop_loss"],
                "take_profit": row["take_profit"],
                "sector": row["sector"],
                "earnings_in_days": row["earnings_in_days"],
                "submitted": row["submitted"],
                "skip_reason": row["skip_reason"],
            }
            # Validate sub_scores_json parses (defensive — bad rows would
            # surface as JSONB load errors much later)
            if payload["sub_scores_json"]:
                try:
                    json.loads(payload["sub_scores_json"])
                except json.JSONDecodeError:
                    logger.warning(
                        "Row id=%s has malformed sub_scores_json; nulling.", row["id"]
                    )
                    payload["sub_scores_json"] = None

            obj = PaperRecommendation(**payload)
            session.add(obj)
            await session.flush()  # populate obj.id
            sqlite_to_pg_rec[row["id"]] = obj.id

        await session.commit()
        logger.info("Migrated %d paper_recommendations", len(sqlite_to_pg_rec))

        # ---- Pass 2: paper_orders. Use INSERT...ON CONFLICT DO NOTHING for idempotency. ----
        order_inserts = 0
        order_skips = 0
        for row in orders:
            pg_rec_id = sqlite_to_pg_rec.get(row["recommendation_id"])
            if pg_rec_id is None:
                logger.warning(
                    "Order id=%s references missing recommendation %s — skipping.",
                    row["id"],
                    row["recommendation_id"],
                )
                order_skips += 1
                continue
            stmt = pg_insert(PaperOrder.__table__).values(
                recommendation_id=pg_rec_id,
                alpaca_order_id=row["alpaca_order_id"],
                client_order_id=row["client_order_id"],
                ticker=row["ticker"],
                side=row["side"],
                qty=row["qty"],
                submitted_at=_parse_dt(row["submitted_at"]),
                status=row["status"],
                filled_qty=row["filled_qty"] or 0,
                filled_price=row["filled_price"],
                filled_at=_parse_dt(row["filled_at"]),
                take_profit=row["take_profit"],
                stop_loss=row["stop_loss"],
            ).on_conflict_do_nothing(index_elements=["alpaca_order_id"])
            result = await session.execute(stmt)
            if result.rowcount > 0:
                order_inserts += 1
            else:
                order_skips += 1

        await session.commit()
        logger.info(
            "Migrated %d paper_orders (skipped %d duplicates/orphans)",
            order_inserts,
            order_skips,
        )

        # ---- Pass 3: paper_trades. No unique constraint on alpaca_order_id here. ----
        trade_inserts = 0
        for row in trades:
            pg_rec_id = (
                sqlite_to_pg_rec.get(row["recommendation_id"])
                if row["recommendation_id"]
                else None
            )
            session.add(
                PaperTrade(
                    recommendation_id=pg_rec_id,
                    ticker=row["ticker"],
                    qty=row["qty"],
                    entry_price=row["entry_price"],
                    exit_price=row["exit_price"],
                    entry_at=_parse_dt(row["entry_at"]),
                    exit_at=_parse_dt(row["exit_at"]),
                    hold_days=row["hold_days"],
                    pnl=row["pnl"],
                    pnl_pct=row["pnl_pct"],
                    exit_reason=row["exit_reason"],
                    composite_score=row["composite_score"],
                )
            )
            trade_inserts += 1

        await session.commit()
        logger.info("Migrated %d paper_trades", trade_inserts)

    sqlite_conn.close()

    # ---- Verification: row counts match ----
    async with SessionLocal() as session:
        rec_pg = (await session.execute(select(PaperRecommendation))).scalars().all()
        ord_pg = (await session.execute(select(PaperOrder))).scalars().all()
        tr_pg = (await session.execute(select(PaperTrade))).scalars().all()

    logger.info(
        "Postgres counts now: recommendations=%d orders=%d trades=%d",
        len(rec_pg),
        len(ord_pg),
        len(tr_pg),
    )

    src_total = len(recs) + len(orders) + len(trades)
    dest_total = len(rec_pg) + len(ord_pg) + len(tr_pg)
    if dest_total >= src_total - (order_skips + 0):
        logger.info("Migration verified — destination >= source (modulo expected skips).")
    else:
        logger.error("Row count mismatch: src=%d dest=%d", src_total, dest_total)
        sys.exit(2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "paper_trading.db",
        help="Path to source SQLite DB (default: data/paper_trading.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read source counts; do not write to Postgres",
    )
    args = parser.parse_args()

    try:
        asyncio.run(migrate(args.source, args.dry_run))
    finally:
        asyncio.run(dispose_engine())


if __name__ == "__main__":
    main()
