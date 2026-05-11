"""Postgres-backed ICRepository.

Persists alphalens IC diagnostic outputs. Backs the future web layer's
IC history view + Phase 4's drift detection (rolling IC vs training IC).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.contracts.entities.factor import ICReport, QuantileSpread
from src.db.models import ICDiagnostic


def _row_to_report(row: ICDiagnostic) -> ICReport:
    spreads = tuple(
        QuantileSpread.model_validate(s) for s in (row.quantile_spreads or [])
    )
    return ICReport(
        factor_column=row.factor_column,
        universe=row.universe_label,
        window_start=row.window_start,
        window_end=row.window_end,
        quantiles=row.quantiles,
        n_observations=row.n_observations,
        ic_mean=dict(row.ic_mean or {}),
        ic_std=dict(row.ic_std or {}),
        ic_ir=dict(row.ic_ir or {}),
        quantile_spreads=spreads,
        verdict=row.verdict or "",
    )


class PostgresICRepository:
    """Implements src.contracts.protocols.repositories.ICRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, report: ICReport) -> int:
        row = ICDiagnostic(
            factor_column=report.factor_column,
            universe_label=report.universe,
            window_start=report.window_start,
            window_end=report.window_end,
            created_at=datetime.now(timezone.utc),
            quantiles=report.quantiles,
            n_observations=report.n_observations,
            ic_mean=dict(report.ic_mean),
            ic_std=dict(report.ic_std),
            ic_ir=dict(report.ic_ir),
            quantile_spreads=[s.model_dump() for s in report.quantile_spreads],
            verdict=report.verdict,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row.id

    async def list_recent(
        self,
        factor_column: str | None = None,
        limit: int = 20,
    ) -> list[ICReport]:
        stmt = select(ICDiagnostic).order_by(desc(ICDiagnostic.created_at)).limit(limit)
        if factor_column:
            stmt = stmt.where(ICDiagnostic.factor_column == factor_column)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_row_to_report(r) for r in rows]
