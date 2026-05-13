"""/api/scans — kick off, list, fetch market scans."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_config, get_db_session
from src.api.schemas.scan import (
    ScanRequest,
    ScanResponse,
    ScanResultItem,
    ScanSummary,
)
from src.api.services.scan_runner import run_scan_sync
from src.config_loader import Config
from src.db.models import ScanRun

logger = logging.getLogger(__name__)
router = APIRouter()


def _strategy_from_config(config: Config, name: str) -> dict:
    try:
        return config.get_strategy(name)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"unknown strategy '{name}'")


@router.post("", response_model=ScanResponse)
async def trigger_scan(
    body: ScanRequest,
    config: Config = Depends(get_config),
    db: AsyncSession = Depends(get_db_session),
) -> ScanResponse:
    """Run a synchronous scan and persist the result.

    Synchronous from the caller's perspective — blocks until the scan
    completes. Heavy compute runs in a worker thread so the event loop stays
    responsive. Phase 1.7 adds /api/stream/scan-progress for live updates.
    """
    strategy = _strategy_from_config(config, body.strategy)

    recs_raw = await asyncio.to_thread(
        run_scan_sync,
        config,
        strategy,
        universe=body.universe,
        theme=body.theme,
        sector=body.sector,
        fresh=body.fresh,
        live_signals=body.live_signals,
    )

    if body.top is not None:
        recs_raw = recs_raw[: body.top]

    results = [ScanResultItem.model_validate(r) for r in recs_raw]

    run_id = str(uuid.uuid4())
    scan_ts = datetime.now(timezone.utc)

    row = ScanRun(
        strategy=body.strategy,
        scan_timestamp=scan_ts,
        universe_label=run_id,
        budget=body.budget,
        n_candidates=len(results),
        recommendations=[r.model_dump() for r in results],
    )
    db.add(row)
    await db.commit()

    return ScanResponse(
        run_id=run_id,
        strategy=body.strategy,
        scan_timestamp=scan_ts,
        n_candidates=len(results),
        n_results=len(results),
        results=results,
    )


@router.get("", response_model=list[ScanSummary])
async def list_scans(
    strategy: str | None = Query(default=None),
    limit: int = Query(default=20, gt=0, le=200),
    db: AsyncSession = Depends(get_db_session),
) -> list[ScanSummary]:
    """Most recent scan runs, newest first."""
    stmt = select(ScanRun).order_by(desc(ScanRun.scan_timestamp)).limit(limit)
    if strategy:
        stmt = stmt.where(ScanRun.strategy == strategy)
    rows = (await db.execute(stmt)).scalars().all()

    summaries: list[ScanSummary] = []
    for r in rows:
        top = r.recommendations[0] if r.recommendations else None
        summaries.append(
            ScanSummary(
                run_id=r.universe_label,
                strategy=r.strategy,
                scan_timestamp=r.scan_timestamp,
                n_candidates=r.n_candidates,
                top_ticker=top.get("ticker") if top else None,
                top_score=top.get("composite_score") if top else None,
            )
        )
    return summaries


@router.get("/{run_id}", response_model=ScanResponse)
async def get_scan(
    run_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> ScanResponse:
    stmt = (
        select(ScanRun)
        .where(ScanRun.universe_label == run_id)
        .order_by(desc(ScanRun.scan_timestamp))
        .limit(1)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="scan not found")

    results = [ScanResultItem.model_validate(r) for r in row.recommendations]
    return ScanResponse(
        run_id=row.universe_label,
        strategy=row.strategy,
        scan_timestamp=row.scan_timestamp,
        n_candidates=row.n_candidates,
        n_results=len(results),
        results=results,
    )
