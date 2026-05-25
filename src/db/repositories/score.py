"""Postgres-backed ScoreRepository.

Persists composite scores from scan runs. Reads back for the future web layer's
score history view + Phase 4 calibration tracker.

Schema: one row per scan invocation in `scan_runs`, with `recommendations`
JSONB holding the list of CompositeScore dumps. Historical reads filter on
strategy + ticker by scanning the JSONB array — fine at our scale (<100k rows).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.contracts.entities.score import CompositeScore
from src.db.models import ScanRun


def _score_to_jsonable(s: CompositeScore) -> dict:
    """Serialize a CompositeScore for JSONB storage. Preserves the entity's
    tuple/dict shape so round-trip parses cleanly."""
    return {
        "ticker": s.ticker,
        "composite_score": s.composite_score,
        "sub_scores": dict(s.sub_scores),
        "all_signals": [sig.model_dump() for sig in s.all_signals],
        "bullish_signals": s.bullish_signals,
        "bearish_signals": s.bearish_signals,
        "breakdown": [b.model_dump() for b in s.breakdown],
        "consensus": s.consensus.model_dump() if s.consensus else None,
        "atr": s.atr,
        "close": s.close,
    }


def _jsonable_to_score(d: dict) -> CompositeScore:
    """Inverse of _score_to_jsonable. Pydantic v2 validates on construct."""
    return CompositeScore.model_validate(d)


class PostgresScoreRepository:
    """Implements src.contracts.protocols.repositories.ScoreRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_scan(
        self,
        run_id: str,
        strategy: str,
        as_of: datetime,
        scores: list[CompositeScore],
    ) -> None:
        """run_id is informational — Postgres assigns its own BigInteger PK.
        The string run_id is stashed in universe_label as a sentinel for
        callers that want to look it up by their own identifier (e.g. a UUID
        from a Celery task)."""
        row = ScanRun(
            strategy=strategy,
            scan_timestamp=as_of,
            universe_label=run_id,
            budget=None,
            n_candidates=len(scores),
            recommendations=[_score_to_jsonable(s) for s in scores],
        )
        self._session.add(row)
        await self._session.commit()

    async def get_scan(self, run_id: str) -> list[CompositeScore]:
        stmt = (
            select(ScanRun)
            .where(ScanRun.run_id == run_id)
            .order_by(desc(ScanRun.scan_timestamp))
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return []
        return [_jsonable_to_score(r) for r in row.recommendations]

    async def get_score_history(
        self,
        ticker: str,
        strategy: str,
        start: datetime,
        end: datetime,
    ) -> list[tuple[datetime, CompositeScore]]:
        """Scans every scan_run in [start, end] for matching strategy, then
        filters the embedded JSONB recommendations array for this ticker
        in Python.

        Intentionally simple. The composite (strategy, scan_timestamp DESC)
        index from migration 0011 makes the range filter cheap; the JSONB
        filter remains a sequential per-row scan, which Postgres handles
        fine at today's row counts. At >100k scan_runs promote to a
        materialized view or a projection table indexed by (strategy,
        ticker, scan_timestamp). NOTE: there is no GIN index on the
        recommendations column today — a previous version of this comment
        claimed otherwise."""
        stmt = (
            select(ScanRun)
            .where(ScanRun.strategy == strategy)
            .where(ScanRun.scan_timestamp >= start)
            .where(ScanRun.scan_timestamp <= end)
            .order_by(ScanRun.scan_timestamp)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        history: list[tuple[datetime, CompositeScore]] = []
        for row in rows:
            for rec in row.recommendations:
                if rec.get("ticker") == ticker:
                    history.append((row.scan_timestamp, _jsonable_to_score(rec)))
                    break
        return history
