"""Postgres-backed BacktestRepository.

Stores BacktestResult trees as JSONB in the `backtest_runs` table. Surfaces
common scalar fields (n_trades, oos_sharpe, oos_total_return_pct,
oos_max_drawdown_pct) as dedicated columns for fast list views without
needing to parse JSONB.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.contracts.entities.backtest import BacktestResult
from src.db.models import BacktestRun


def _extract_oos_scalars(result_dict: dict) -> dict[str, Any]:
    """Pull the headline metrics from the OOS bucket dict for fast filtering.
    Returns None for missing keys — the dedicated columns are nullable."""
    oos = result_dict.get("out_of_sample") or {}
    trades = result_dict.get("trades") or []
    return {
        "n_trades": len(trades),
        "oos_sharpe": oos.get("sharpe"),
        "oos_total_return_pct": oos.get("total_return_pct"),
        "oos_max_drawdown_pct": oos.get("max_drawdown_pct"),
    }


def _row_to_result(row: BacktestRun) -> BacktestResult:
    """JSONB → BacktestResult. pydantic v2 validates and rebuilds the
    tuple fields from JSON arrays."""
    payload = dict(row.result)
    # Ensure required fields are populated from the row even if missing in JSONB
    payload.setdefault("strategy", row.strategy)
    payload.setdefault("window_start", row.window_start.isoformat())
    payload.setdefault("window_end", row.window_end.isoformat())
    return BacktestResult.model_validate(payload)


class PostgresBacktestRepository:
    """Implements src.contracts.protocols.repositories.BacktestRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, result: BacktestResult) -> int:
        payload = result.model_dump(mode="json")
        oos_scalars = _extract_oos_scalars(payload)
        row = BacktestRun(
            strategy=result.strategy,
            universe_label=str(payload.get("universe_label", "")),
            window_start=result.window_start,
            window_end=result.window_end,
            created_at=datetime.now(timezone.utc),
            **oos_scalars,
            result=payload,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row.id

    async def get_by_id(self, run_id: int) -> BacktestResult | None:
        stmt = select(BacktestRun).where(BacktestRun.id == run_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _row_to_result(row) if row else None

    async def list_recent(
        self,
        strategy: str | None = None,
        limit: int = 20,
    ) -> list[BacktestResult]:
        stmt = select(BacktestRun).order_by(desc(BacktestRun.created_at)).limit(limit)
        if strategy:
            stmt = stmt.where(BacktestRun.strategy == strategy)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_row_to_result(r) for r in rows]
