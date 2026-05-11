"""Postgres-backed RecommendationRepository.

Persists Recommendation entities into the `paper_recommendations` table. The
table predates the typed contracts (it came from src/paper/db.py SQLite shape)
so the column set is narrower than Recommendation has — fields like
`reasoning`, `breakdown`, `all_signals`, `risk_management` are NOT persisted
columns; if Phase 4+ needs them we add a JSONB sidecar column.

For now, the repository preserves the columns the legacy CLI consumed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.contracts.entities.recommendation import Recommendation
from src.db.models import PaperRecommendation


def _row_to_recommendation(row: PaperRecommendation) -> Recommendation:
    """Inverse mapping. Loses fields that weren't persisted (reasoning,
    all_signals, breakdown, risk_management) — they come back empty."""
    sub_scores: dict[str, float] = {}
    if row.sub_scores_json:
        try:
            sub_scores = json.loads(row.sub_scores_json)
        except json.JSONDecodeError:
            sub_scores = {}
    return Recommendation(
        ticker=row.ticker,
        action=row.action,  # type: ignore[arg-type]
        composite_score=row.composite_score,
        confidence="Medium",  # not stored; default
        sub_scores=sub_scores,
        sector=row.sector or "Unknown",
    )


class PostgresRecommendationRepository:
    """Implements src.contracts.protocols.repositories.RecommendationRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, recommendation: Recommendation, run_id: str) -> int:
        """run_id is a free-form correlation tag (often a scan timestamp ISO
        string or a Celery task UUID). It does NOT map to scan_runs.id —
        history correlation should use scan_runs for the full picks set, and
        this table for the paper-trading subset that actually went to Alpaca."""
        rm = recommendation.risk_management
        entry_price = rm.current_price if rm else None
        stop_loss = (
            rm.stop_loss.get("price") if rm and isinstance(rm.stop_loss, dict) else None
        )
        take_profit = (
            rm.take_profit.get("price")
            if rm and isinstance(rm.take_profit, dict)
            else None
        )

        row = PaperRecommendation(
            ticker=recommendation.ticker,
            scan_timestamp=datetime.now(timezone.utc),
            strategy=run_id,  # repurposed — see docstring
            composite_score=recommendation.composite_score,
            action=recommendation.action,
            sub_scores_json=json.dumps(dict(recommendation.sub_scores)),
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            sector=recommendation.sector,
            earnings_in_days=None,
            submitted=0,
            skip_reason=None,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row.id

    async def get_by_run(self, run_id: str) -> list[Recommendation]:
        stmt = (
            select(PaperRecommendation)
            .where(PaperRecommendation.strategy == run_id)
            .order_by(PaperRecommendation.composite_score.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_row_to_recommendation(r) for r in rows]
