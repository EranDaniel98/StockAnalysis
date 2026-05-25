"""/api/scans — factor-pipeline picks read from disk.

What used to live here:
    POST /api/scans, GET /api/scans, GET /api/scans/{run_id},
    GET /api/scans/latest-buys, POST /api/scans/sanity-check

All of those drove the legacy 5-engine composite path: run an on-demand scan
through ``src.scoring.service``, persist a ``ScanRun`` row, surface the
results via the web UI. The FE has migrated to the factor pipeline
(``scripts/run_daily_pipeline.py``) and stopped calling those endpoints
months ago; they were deleted 2026-05-23.

What remains is the single read-only surface the factor pipeline writes to:

    GET /api/scans/factor-picks

Returns ``list[BuySignal]`` shaped identically to the legacy ``/latest-buys``
endpoint so the web layer can render with the same components.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db_session
from src.api.schemas.sanity import SanityCheck
from src.api.schemas.scan import BuySignal
from src.api.services.factor_picks_reader import load_latest_factor_picks
from src.db.models import SanityCheckRow

logger = logging.getLogger(__name__)
router = APIRouter()


async def _load_cached_sanity_checks(
    db: AsyncSession, run_ids: list[str],
) -> dict[tuple[str, str], SanityCheck]:
    """Return ``{(ticker, run_id): SanityCheck}`` for the given run_ids.

    Empty dict when none cached. Used by factor_picks to attach cached
    sanity-check verdicts (written by ``scripts/ai_sanity_check.py``) to
    each row.
    """
    if not run_ids:
        return {}
    stmt = select(SanityCheckRow).where(SanityCheckRow.run_id.in_(run_ids))
    rows = (await db.execute(stmt)).scalars().all()
    return {
        (row.ticker, row.run_id): SanityCheck(
            verdict=row.verdict,
            reason=row.reason,
            catalysts_found=list(row.catalysts_found or []),
            confidence=row.confidence,
            model_used=row.model_used,
            mocked=row.mocked,
            checked_at=row.checked_at.isoformat() if row.checked_at else None,
        )
        for row in rows
    }


@router.get("/factor-picks", response_model=list[BuySignal])
async def factor_picks(
    db: AsyncSession = Depends(get_db_session),
) -> list[BuySignal]:
    """Today's composite-factor picks (PIT S&P 500, m+q+v rank-blend).

    Reads from ``data/daily_picks/YYYY-MM-DD.json`` — the source the
    paper trader uses to place real (paper) orders. This is the
    canonical "what does the system want to BUY?" surface. Sanity-check
    verdicts (cached against the synthetic ``factor:<strategy>:<as_of>``
    run_id) are attached when present so the web UI can render
    brake-light state on each row.

    Returns an empty list when no picks file exists (system not yet
    bootstrapped) or when the file is malformed.
    """
    signals = load_latest_factor_picks()
    if not signals:
        return []
    run_ids = list({s.run_id for s in signals})
    sanity_cache = await _load_cached_sanity_checks(db, run_ids)
    for s in signals:
        cached = sanity_cache.get((s.ticker, s.run_id))
        if cached is not None:
            s.sanity_check = cached
    return signals
