"""/api/recommendations — read-only view of paper-trading recommendations."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db_session
from src.api.schemas.recommendation import PaperRecommendationItem
from src.db.models import PaperRecommendation

logger = logging.getLogger(__name__)
router = APIRouter()


def _row_to_item(row: PaperRecommendation) -> PaperRecommendationItem:
    sub_scores: dict[str, float] = {}
    if row.sub_scores_json:
        try:
            sub_scores = json.loads(row.sub_scores_json) or {}
        except json.JSONDecodeError:
            sub_scores = {}
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
    )


@router.get("", response_model=list[PaperRecommendationItem])
async def list_recommendations(
    ticker: str | None = Query(default=None),
    strategy: str | None = Query(default=None),
    submitted_only: bool = Query(default=False),
    limit: int = Query(default=50, gt=0, le=500),
    db: AsyncSession = Depends(get_db_session),
) -> list[PaperRecommendationItem]:
    """Most recent paper-trading recommendations, newest first."""
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
    return [_row_to_item(r) for r in rows]


@router.get("/{rec_id}", response_model=PaperRecommendationItem)
async def get_recommendation(
    rec_id: int,
    db: AsyncSession = Depends(get_db_session),
) -> PaperRecommendationItem:
    stmt = select(PaperRecommendation).where(PaperRecommendation.id == rec_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    return _row_to_item(row)
