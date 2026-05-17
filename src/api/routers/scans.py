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
    BuySignal,
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


_BUY_ACTIONS = ("STRONG BUY", "BUY")
_STRONG_BUY_ONLY = ("STRONG BUY",)


@router.get("/latest-buys", response_model=list[BuySignal])
async def latest_buys(
    strong_only: bool = Query(
        default=False,
        description="When true, returns only STRONG BUY signals (filters out plain BUY).",
    ),
    db: AsyncSession = Depends(get_db_session),
) -> list[BuySignal]:
    """Union of BUY+ rows from the latest scan per strategy.

    Pulls the most-recent scan_run per strategy, filters each to BUY+ rows,
    and deduplicates by ticker — attributing each ticker to the strategy
    that produced its highest composite_score. ``consensus_count`` reports
    how many strategies' latest runs agreed on the BUY+ rating for that
    ticker, so the FE can highlight cross-strategy conviction.

    Returns rows sorted by composite_score desc, consensus_count desc as
    tiebreak. Empty list when no recent scan has any BUY+ rows (not an
    error — the system simply isn't ringing the bell right now).
    """
    allowed = _STRONG_BUY_ONLY if strong_only else _BUY_ACTIONS

    # SELECT DISTINCT ON (strategy) ... ORDER BY strategy, scan_timestamp DESC
    # — one row per strategy, the most recent. Backed by the composite
    # index ix_scan_runs_strategy_ts_desc from alembic 0011, so this is
    # an index-only skip scan, O(strategies) work. Replaces the previous
    # "fetch last 50, dedupe in Python" pattern which could silently drop
    # a strategy if another strategy's burst of rescans monopolized the
    # top 50.
    stmt = (
        select(ScanRun)
        .distinct(ScanRun.strategy)
        .order_by(ScanRun.strategy, desc(ScanRun.scan_timestamp))
    )
    latest_per_strategy = (await db.execute(stmt)).scalars().all()

    bucket: dict[str, dict] = {}
    for run in latest_per_strategy:
        for rec in run.recommendations or []:
            if rec.get("action") not in allowed:
                continue
            # Refuse rows the safety gates marked unreliable, even if the
            # stored action says BUY. Belt-and-suspenders: the recommender
            # already forces HOLD when any of these is set, so this only
            # ever fires on a refactor regression OR a legacy row whose
            # action wasn't normalized at scan time.
            if rec.get("score_valid") is False:
                continue
            if rec.get("instrument_warning"):
                continue
            if rec.get("insufficient_history"):
                continue
            ticker = rec.get("ticker")
            if not ticker:
                continue
            score = float(rec.get("composite_score") or 0.0)
            entry = bucket.setdefault(
                ticker,
                {
                    "ticker": ticker,
                    "strategies": [],
                    "best_score": -1.0,
                    "best_rec": None,
                    "best_run": None,
                },
            )
            entry["strategies"].append(run.strategy)
            if score > entry["best_score"]:
                entry["best_score"] = score
                entry["best_rec"] = rec
                entry["best_run"] = run

    out: list[BuySignal] = []
    for ticker, entry in bucket.items():
        rec = entry["best_rec"]
        run = entry["best_run"]
        out.append(
            BuySignal(
                ticker=ticker,
                name=rec.get("name") or "",
                sector=rec.get("sector") or "Unknown",
                industry=rec.get("industry") or "Unknown",
                market_cap=rec.get("market_cap"),
                action=rec["action"],
                composite_score=float(rec["composite_score"]),
                confidence=str(rec.get("confidence") or ""),
                strategy=run.strategy,
                scan_timestamp=run.scan_timestamp,
                run_id=run.universe_label,
                consensus_count=len(entry["strategies"]),
                consensus_strategies=sorted(set(entry["strategies"])),
                earnings_announcement_ts=rec.get("earnings_announcement_ts"),
                earnings_call_ts=rec.get("earnings_call_ts"),
            )
        )

    out.sort(
        key=lambda b: (-b.composite_score, -b.consensus_count, b.ticker),
    )
    return out


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
