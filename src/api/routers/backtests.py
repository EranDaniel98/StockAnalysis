"""/api/backtests — kick off, list, fetch backtest runs.

Backtests can take minutes. The POST endpoint blocks until done in v1; if
you want progress, subscribe to /api/stream/scan-progress (Phase 1.7).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_config, get_db_session
from src.api.schemas.backtest import (
    BacktestRequest,
    BacktestResponse,
    BacktestSummary,
)
from src.api.services.backtest_runner import run_backtest_sync
from src.backtest.engine import LookaheadGuardError
from src.config_loader import Config
from src.db.models import BacktestRun

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_pg_timestamp(value) -> datetime:
    """Coerce engine-returned start/end (which may be pd.Timestamp or ISO str)
    into a tz-aware datetime suitable for the DB column."""
    ts = pd.Timestamp(value) if not isinstance(value, pd.Timestamp) else value
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    return ts.to_pydatetime()


def _extract_oos_scalars(result: dict) -> dict:
    oos = result.get("out_of_sample") or {}
    trades = result.get("trades") or []
    return {
        "n_trades": len(trades),
        "oos_sharpe": oos.get("sharpe"),
        "oos_total_return_pct": oos.get("total_return_pct"),
        "oos_max_drawdown_pct": oos.get("max_drawdown_pct"),
    }


@router.post("", response_model=BacktestResponse)
async def trigger_backtest(
    body: BacktestRequest,
    config: Config = Depends(get_config),
    db: AsyncSession = Depends(get_db_session),
) -> BacktestResponse:
    try:
        result = await asyncio.to_thread(run_backtest_sync, config, body)
    except LookaheadGuardError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    window_start = _to_pg_timestamp(result["window_start"])
    window_end = _to_pg_timestamp(result["window_end"])

    row = BacktestRun(
        strategy=body.strategy,
        universe_label=str(result.get("universe_label", "")),
        window_start=window_start,
        window_end=window_end,
        created_at=datetime.now(timezone.utc),
        result=result,
        **_extract_oos_scalars(result),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    return BacktestResponse(
        id=row.id,
        strategy=row.strategy,
        window_start=row.window_start,
        window_end=row.window_end,
        result=result,
    )


@router.get("", response_model=list[BacktestSummary])
async def list_backtests(
    strategy: str | None = Query(default=None),
    limit: int = Query(default=20, gt=0, le=200),
    db: AsyncSession = Depends(get_db_session),
) -> list[BacktestSummary]:
    stmt = select(BacktestRun).order_by(desc(BacktestRun.created_at)).limit(limit)
    if strategy:
        stmt = stmt.where(BacktestRun.strategy == strategy)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        BacktestSummary(
            id=r.id,
            strategy=r.strategy,
            universe_label=r.universe_label,
            window_start=r.window_start,
            window_end=r.window_end,
            created_at=r.created_at,
            n_trades=r.n_trades,
            oos_sharpe=r.oos_sharpe,
            oos_total_return_pct=r.oos_total_return_pct,
            oos_max_drawdown_pct=r.oos_max_drawdown_pct,
        )
        for r in rows
    ]


@router.get("/{run_id}", response_model=BacktestResponse)
async def get_backtest(
    run_id: int,
    db: AsyncSession = Depends(get_db_session),
) -> BacktestResponse:
    stmt = select(BacktestRun).where(BacktestRun.id == run_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="backtest not found")
    return BacktestResponse(
        id=row.id,
        strategy=row.strategy,
        window_start=row.window_start,
        window_end=row.window_end,
        result=row.result,
    )
