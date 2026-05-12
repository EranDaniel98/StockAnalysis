"""/api/trades — closed paper-trade history + journal notes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db_session
from src.api.schemas.trades import PaperTradeItem, TradeNotesUpdate
from src.db.models import PaperTrade

logger = logging.getLogger(__name__)
router = APIRouter()


def _row_to_item(row: PaperTrade) -> PaperTradeItem:
    return PaperTradeItem(
        id=row.id,
        ticker=row.ticker,
        qty=row.qty,
        entry_price=row.entry_price,
        exit_price=row.exit_price,
        entry_at=row.entry_at,
        exit_at=row.exit_at,
        hold_days=row.hold_days,
        pnl=row.pnl,
        pnl_pct=row.pnl_pct,
        exit_reason=row.exit_reason,
        composite_score=row.composite_score,
        notes=row.notes,
    )


@router.get("", response_model=list[PaperTradeItem])
async def list_trades(
    ticker: str | None = Query(default=None),
    min_score: float | None = Query(default=None, ge=0, le=100),
    has_notes: bool | None = Query(default=None),
    limit: int = Query(default=100, gt=0, le=500),
    db: AsyncSession = Depends(get_db_session),
) -> list[PaperTradeItem]:
    """Closed paper trades, newest exit first. Filter by ticker, score
    floor, or whether the row already has notes."""
    stmt = select(PaperTrade).order_by(desc(PaperTrade.exit_at)).limit(limit)
    if ticker:
        stmt = stmt.where(PaperTrade.ticker == ticker.upper())
    if min_score is not None:
        stmt = stmt.where(PaperTrade.composite_score >= min_score)
    if has_notes is True:
        stmt = stmt.where(PaperTrade.notes.is_not(None))
    elif has_notes is False:
        stmt = stmt.where(PaperTrade.notes.is_(None))
    rows = (await db.execute(stmt)).scalars().all()
    return [_row_to_item(r) for r in rows]


@router.patch("/{trade_id}", response_model=PaperTradeItem)
async def update_trade_notes(
    trade_id: int,
    body: TradeNotesUpdate,
    db: AsyncSession = Depends(get_db_session),
) -> PaperTradeItem:
    """Replace the notes field. ``null`` clears the entry."""
    stmt = select(PaperTrade).where(PaperTrade.id == trade_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="trade not found")
    row.notes = body.notes
    await db.commit()
    await db.refresh(row)
    return _row_to_item(row)
