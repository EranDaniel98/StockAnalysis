"""/api/diagnostics — alphalens IC diagnostic + history."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_config, get_db_session
from src.api.schemas.diagnostic import (
    DiagnosticRequest,
    DiagnosticResponse,
    DiagnosticSummary,
)
from src.api.services.diagnostic_runner import run_diagnostic_sync
from src.backtest.engine import LookaheadGuardError
from src.config_loader import Config
from src.db.models import ICDiagnostic

logger = logging.getLogger(__name__)
router = APIRouter()


IC_GATE = 0.03


def _verdict_from_ic(ic_mean: dict[str, float]) -> str:
    """Quick-and-dirty signal verdict — IC > 0.03 on any horizon is real."""
    if not ic_mean:
        return "no IC data"
    best = max(ic_mean.values())
    if best >= IC_GATE:
        return f"signal present (best IC {best:.4f})"
    return f"weak/no signal (best IC {best:.4f}, gate {IC_GATE})"


def _to_pg_ts(value) -> datetime:
    ts = pd.Timestamp(value) if not isinstance(value, pd.Timestamp) else value
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    return ts.to_pydatetime()


@router.post("", response_model=DiagnosticResponse)
async def trigger_diagnostic(
    body: DiagnosticRequest,
    config: Config = Depends(get_config),
    db: AsyncSession = Depends(get_db_session),
) -> DiagnosticResponse:
    try:
        result = await asyncio.to_thread(run_diagnostic_sync, config, body)
    except LookaheadGuardError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    ic_mean = result.get("ic_mean", {})
    verdict = _verdict_from_ic(ic_mean)

    row = ICDiagnostic(
        factor_column=body.factor,
        universe_label=str(result.get("universe_label", "")),
        window_start=_to_pg_ts(result["window_start"]),
        window_end=_to_pg_ts(result["window_end"]),
        created_at=datetime.now(timezone.utc),
        quantiles=body.quantiles,
        n_observations=int(result.get("n_observations", 0)),
        ic_mean=ic_mean,
        ic_std=result.get("ic_std", {}),
        ic_ir=result.get("ic_ir", {}),
        quantile_spreads=[
            {"period": k, "spread_pct": v}
            for k, v in (result.get("top_minus_bottom_pct") or {}).items()
        ],
        verdict=verdict,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    return DiagnosticResponse(
        id=row.id,
        factor=row.factor_column,
        universe_label=row.universe_label,
        window_start=row.window_start,
        window_end=row.window_end,
        created_at=row.created_at,
        quantiles=row.quantiles,
        n_observations=row.n_observations,
        ic_mean=ic_mean,
        ic_std=result.get("ic_std", {}),
        ic_ir=result.get("ic_ir", {}),
        top_minus_bottom_pct=result.get("top_minus_bottom_pct", {}),
        verdict=verdict,
    )


@router.get("", response_model=list[DiagnosticSummary])
async def list_diagnostics(
    factor: str | None = Query(default=None),
    limit: int = Query(default=20, gt=0, le=200),
    db: AsyncSession = Depends(get_db_session),
) -> list[DiagnosticSummary]:
    stmt = select(ICDiagnostic).order_by(desc(ICDiagnostic.created_at)).limit(limit)
    if factor:
        stmt = stmt.where(ICDiagnostic.factor_column == factor)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        DiagnosticSummary(
            id=r.id,
            factor=r.factor_column,
            universe_label=r.universe_label,
            window_start=r.window_start,
            window_end=r.window_end,
            created_at=r.created_at,
            n_observations=r.n_observations,
            verdict=r.verdict,
        )
        for r in rows
    ]


@router.get("/{run_id}", response_model=DiagnosticResponse)
async def get_diagnostic(
    run_id: int,
    db: AsyncSession = Depends(get_db_session),
) -> DiagnosticResponse:
    stmt = select(ICDiagnostic).where(ICDiagnostic.id == run_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="diagnostic not found")

    top_minus_bottom = {
        entry["period"]: entry["spread_pct"] for entry in (row.quantile_spreads or [])
    }
    return DiagnosticResponse(
        id=row.id,
        factor=row.factor_column,
        universe_label=row.universe_label,
        window_start=row.window_start,
        window_end=row.window_end,
        created_at=row.created_at,
        quantiles=row.quantiles,
        n_observations=row.n_observations,
        ic_mean=row.ic_mean,
        ic_std=row.ic_std,
        ic_ir=row.ic_ir,
        top_minus_bottom_pct=top_minus_bottom,
        verdict=row.verdict,
    )
