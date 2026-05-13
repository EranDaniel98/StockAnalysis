"""/api/recommendations — read-only view of paper-trading recommendations."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db_session
from src.api.schemas.recommendation import PaperRecommendationItem
from src.db.models import PaperRecommendation, PaperTrade


_CANONICAL_REASONS = {"target_hit", "stop_hit", "manual"}


def _classify_outcome(
    submitted: bool,
    skip_reason: str | None,
    closed_reason: str | None,
) -> tuple[str, bool]:
    """Return (outcome, has_trade). The boolean tells the caller whether
    the join produced a paper_trade row, so the realized_pnl_pct only
    surfaces when applicable."""
    if not submitted:
        return ("skipped" if skip_reason else "pending", False)
    if closed_reason is None:
        return ("open", False)
    reason = closed_reason.lower()
    if reason in _CANONICAL_REASONS:
        return (reason, True)
    return ("other", True)

logger = logging.getLogger(__name__)
router = APIRouter()


def _row_to_item(
    row: PaperRecommendation,
    *,
    closed_reason: str | None = None,
    closed_pnl_pct: float | None = None,
) -> PaperRecommendationItem:
    sub_scores: dict[str, float] = {}
    if row.sub_scores_json:
        try:
            sub_scores = json.loads(row.sub_scores_json) or {}
        except json.JSONDecodeError:
            sub_scores = {}
    outcome, has_trade = _classify_outcome(
        bool(row.submitted), row.skip_reason, closed_reason
    )
    return PaperRecommendationItem(
        id=row.id,
        ticker=row.ticker,
        strategy=row.strategy,
        scan_timestamp=row.scan_timestamp,
        composite_score=row.composite_score,
        action=row.action,  # type: ignore[arg-type]
        sub_scores=sub_scores,
        entry_price=row.entry_price,
        stop_loss=row.stop_loss,
        take_profit=row.take_profit,
        sector=row.sector,
        earnings_in_days=row.earnings_in_days,
        submitted=bool(row.submitted),
        skip_reason=row.skip_reason,
        outcome=outcome,  # type: ignore[arg-type]
        realized_pnl_pct=closed_pnl_pct if has_trade else None,
    )


@router.get("", response_model=list[PaperRecommendationItem])
async def list_recommendations(
    ticker: str | None = Query(default=None),
    strategy: str | None = Query(default=None),
    submitted_only: bool = Query(default=False),
    limit: int = Query(default=50, gt=0, le=500),
    db: AsyncSession = Depends(get_db_session),
) -> list[PaperRecommendationItem]:
    """Most recent paper-trading recommendations, newest first.

    Left-joins paper_trades so each row carries the eventual outcome
    (target_hit / stop_hit / manual / other / open / pending / skipped)
    plus realized_pnl_pct when closed. A rec can spawn multiple trades
    (rare — partial fills, manual adds); we surface the most-recent
    closed trade.
    """
    stmt = (
        select(PaperRecommendation)
        .order_by(desc(PaperRecommendation.scan_timestamp))
        .limit(limit)
    )
    if ticker:
        stmt = stmt.where(PaperRecommendation.ticker == ticker.upper())
    if strategy:
        stmt = stmt.where(PaperRecommendation.strategy == strategy)
    if submitted_only:
        stmt = stmt.where(PaperRecommendation.submitted == 1)
    rows = (await db.execute(stmt)).scalars().all()

    if not rows:
        return []

    rec_ids = [r.id for r in rows]
    trade_stmt = (
        select(
            PaperTrade.recommendation_id,
            PaperTrade.exit_reason,
            PaperTrade.pnl_pct,
            PaperTrade.exit_at,
        )
        .where(PaperTrade.recommendation_id.in_(rec_ids))
        .order_by(PaperTrade.exit_at.desc())
    )
    trade_rows = (await db.execute(trade_stmt)).all()
    # Keep only the most-recent closed trade per recommendation.
    by_rec: dict[int, tuple[str | None, float | None]] = {}
    for rec_id, exit_reason, pnl_pct, _exit_at in trade_rows:
        if rec_id in by_rec:
            continue
        by_rec[rec_id] = (exit_reason, float(pnl_pct) if pnl_pct is not None else None)

    out: list[PaperRecommendationItem] = []
    for r in rows:
        closed_reason, closed_pnl = by_rec.get(r.id, (None, None))
        out.append(
            _row_to_item(r, closed_reason=closed_reason, closed_pnl_pct=closed_pnl)
        )
    return out


@router.get("/{rec_id}", response_model=PaperRecommendationItem)
async def get_recommendation(
    rec_id: int,
    db: AsyncSession = Depends(get_db_session),
) -> PaperRecommendationItem:
    stmt = select(PaperRecommendation).where(PaperRecommendation.id == rec_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    trade_stmt = (
        select(PaperTrade.exit_reason, PaperTrade.pnl_pct)
        .where(PaperTrade.recommendation_id == rec_id)
        .order_by(PaperTrade.exit_at.desc())
        .limit(1)
    )
    trade_row = (await db.execute(trade_stmt)).first()
    closed_reason = trade_row[0] if trade_row else None
    closed_pnl = float(trade_row[1]) if trade_row and trade_row[1] is not None else None
    return _row_to_item(row, closed_reason=closed_reason, closed_pnl_pct=closed_pnl)
