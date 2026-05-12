"""/api/analytics — derived metrics over recorded paper-trade history."""

from __future__ import annotations

import logging
import statistics
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db_session
from src.api.schemas.analytics import CalibrationBucket, ScoreCalibration
from src.db.models import PaperTrade

logger = logging.getLogger(__name__)
router = APIRouter()


# Default score bands. Each is [lower, upper); the top bucket is closed on
# the upper end. Tuned for the project's 0-100 composite score.
DEFAULT_BANDS: list[tuple[float, float]] = [
    (40.0, 50.0),
    (50.0, 60.0),
    (60.0, 70.0),
    (70.0, 80.0),
    (80.0, 100.01),  # 100.01 so a perfect 100 still lands here
]


def _label(lower: float, upper: float) -> str:
    hi = "100" if upper > 100 else f"{int(upper)}"
    return f"{int(lower)}-{hi}"


@router.get("/calibration", response_model=ScoreCalibration)
async def score_calibration(
    min_score: float = Query(default=40.0, ge=0, le=100),
    db: AsyncSession = Depends(get_db_session),
) -> ScoreCalibration:
    """Score-vs-realized-return calibration.

    Buckets every closed paper trade by its composite_score band and reports
    n_trades + avg / median pnl_pct + win_rate per bucket. The goal: confirm
    that higher composite scores really do produce higher realized returns
    — and surface drift early if they stop doing so.
    """
    stmt = (
        select(PaperTrade.composite_score, PaperTrade.pnl_pct)
        .where(PaperTrade.composite_score.is_not(None))
        .where(PaperTrade.composite_score >= min_score)
    )
    rows = (await db.execute(stmt)).all()

    bands = [b for b in DEFAULT_BANDS if b[1] > min_score]
    buckets_data: dict[tuple[float, float], list[float]] = {b: [] for b in bands}

    for score, pnl_pct in rows:
        if score is None or pnl_pct is None:
            continue
        for lo, hi in bands:
            if lo <= score < hi:
                buckets_data[(lo, hi)].append(float(pnl_pct))
                break

    buckets: list[CalibrationBucket] = []
    for (lo, hi), values in buckets_data.items():
        if values:
            wins = sum(1 for v in values if v > 0)
            buckets.append(
                CalibrationBucket(
                    label=_label(lo, hi),
                    lower=lo,
                    upper=min(hi, 100.0),
                    n_trades=len(values),
                    avg_pnl_pct=sum(values) / len(values),
                    median_pnl_pct=statistics.median(values),
                    win_rate=wins / len(values),
                )
            )
        else:
            buckets.append(
                CalibrationBucket(
                    label=_label(lo, hi),
                    lower=lo,
                    upper=min(hi, 100.0),
                    n_trades=0,
                )
            )

    notes: list[str] = []
    if not rows:
        notes.append(
            "No closed paper trades yet — run `python -m src.main paper trade` to "
            "submit, then `paper evaluate` after positions close."
        )
    elif sum(b.n_trades for b in buckets) < 30:
        notes.append(
            "Fewer than 30 closed trades — calibration is unstable; expect "
            "high noise per bucket."
        )

    return ScoreCalibration(
        as_of=datetime.now(timezone.utc),
        n_total_trades=len(rows),
        buckets=buckets,
        notes=notes,
    )
