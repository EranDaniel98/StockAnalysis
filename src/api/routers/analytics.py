"""/api/analytics — derived metrics over recorded paper-trade history."""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db_session
from src.api.schemas.analytics import CalibrationBucket, ScoreCalibration
from src.api.schemas.analytics_trades import (
    CumulativePnlPoint,
    ExitReasonStat,
    HoldTimeBucket,
    StrategyStat,
    TickerStat,
    TradeAnalytics,
    TradeHeadline,
)
from src.db.models import PaperRecommendation, PaperTrade

logger = logging.getLogger(__name__)
router = APIRouter()


# Hold-time buckets — calibrated against the typical swing-trading window.
# Closed-open intervals; the top bucket catches anything 30+ days.
HOLD_BUCKETS: list[tuple[int, int, str]] = [
    (0, 1, "intraday"),
    (1, 4, "1-3d"),
    (4, 8, "4-7d"),
    (8, 15, "8-14d"),
    (15, 31, "15-30d"),
    (31, 10_000, "30d+"),
]


def _bucket_for_hold_days(days: int | None) -> tuple[int, int, str] | None:
    if days is None:
        return None
    for lo, hi, label in HOLD_BUCKETS:
        if lo <= days < hi:
            return (lo, hi, label)
    return None


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


@router.get("/trades-summary", response_model=TradeAnalytics)
async def trades_summary(
    db: AsyncSession = Depends(get_db_session),
) -> TradeAnalytics:
    """Aggregate analytics across every closed paper trade.

    Read-only — pulls all closed trades + their parent recommendation (for
    strategy attribution) in one query, then computes everything in memory.
    The trade table is unlikely to outgrow this scope for personal use; if
    it ever does, the per-section work each isolates cleanly.
    """
    # LEFT JOIN so trades without a recommendation_id (legacy migrated rows)
    # still feed the headline + cumulative views; they just don't attribute
    # to a strategy.
    stmt = (
        select(
            PaperTrade.id,
            PaperTrade.ticker,
            PaperTrade.pnl,
            PaperTrade.pnl_pct,
            PaperTrade.hold_days,
            PaperTrade.exit_at,
            PaperTrade.exit_reason,
            PaperRecommendation.strategy,
        )
        .join(
            PaperRecommendation,
            PaperTrade.recommendation_id == PaperRecommendation.id,
            isouter=True,
        )
        .order_by(PaperTrade.exit_at.asc())
    )
    rows = (await db.execute(stmt)).all()

    if not rows:
        return TradeAnalytics(
            as_of=datetime.now(timezone.utc),
            headline=TradeHeadline(
                n_trades=0,
                n_winners=0,
                n_losers=0,
                n_breakeven=0,
                win_rate=0.0,
                total_pnl=0.0,
                avg_pnl=0.0,
                avg_pnl_pct=0.0,
            ),
            notes=[
                "No closed paper trades yet — run `python -m src.cli.main "
                "paper trade` then `paper evaluate` once positions exit."
            ],
        )

    # --- headline --------------------------------------------------------
    pnls = [float(r.pnl) for r in rows]
    pnl_pcts = [float(r.pnl_pct) for r in rows]
    winners_pct = [p for p in pnl_pcts if p > 0]
    losers_pct = [p for p in pnl_pcts if p < 0]
    breakeven = sum(1 for p in pnl_pcts if p == 0)

    winners_pnl = sum(float(r.pnl) for r in rows if float(r.pnl_pct) > 0)
    losers_pnl_abs = abs(sum(float(r.pnl) for r in rows if float(r.pnl_pct) < 0))
    profit_factor = (
        winners_pnl / losers_pnl_abs if losers_pnl_abs > 0 else None
    )

    win_rate = (len(winners_pct) / len(pnl_pcts)) if pnl_pcts else 0.0
    loss_rate = (len(losers_pct) / len(pnl_pcts)) if pnl_pcts else 0.0
    avg_win = (sum(winners_pct) / len(winners_pct)) if winners_pct else None
    avg_loss = (sum(losers_pct) / len(losers_pct)) if losers_pct else None
    expectancy = None
    if avg_win is not None and avg_loss is not None:
        expectancy = win_rate * avg_win + loss_rate * avg_loss
    elif avg_win is not None:
        expectancy = win_rate * avg_win
    elif avg_loss is not None:
        expectancy = loss_rate * avg_loss

    hold_days_clean = [int(r.hold_days) for r in rows if r.hold_days is not None]

    headline = TradeHeadline(
        n_trades=len(rows),
        n_winners=len(winners_pct),
        n_losers=len(losers_pct),
        n_breakeven=breakeven,
        win_rate=win_rate,
        total_pnl=sum(pnls),
        avg_pnl=sum(pnls) / len(pnls),
        avg_pnl_pct=sum(pnl_pcts) / len(pnl_pcts),
        avg_win_pct=avg_win,
        avg_loss_pct=avg_loss,
        expectancy_pct=expectancy,
        profit_factor=profit_factor,
        avg_hold_days=(
            sum(hold_days_clean) / len(hold_days_clean) if hold_days_clean else None
        ),
        median_hold_days=(
            statistics.median(hold_days_clean) if hold_days_clean else None
        ),
        max_pnl_pct=max(pnl_pcts) if pnl_pcts else None,
        min_pnl_pct=min(pnl_pcts) if pnl_pcts else None,
    )

    # --- cumulative P&L by exit date ------------------------------------
    by_date: dict[datetime, float] = defaultdict(float)
    by_date_n: dict[datetime, int] = defaultdict(int)
    for r in rows:
        d = r.exit_at.date()
        by_date[d] += float(r.pnl)
        by_date_n[d] += 1
    cumulative_pnl_points: list[CumulativePnlPoint] = []
    running = 0.0
    for d in sorted(by_date):
        running += by_date[d]
        cumulative_pnl_points.append(
            CumulativePnlPoint(
                date=d,
                cumulative_pnl=running,
                n_trades=by_date_n[d],
            )
        )

    # --- by exit reason --------------------------------------------------
    by_reason: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in rows:
        key = (r.exit_reason or "unknown").lower()
        by_reason[key].append((float(r.pnl_pct), float(r.pnl)))
    exit_stats: list[ExitReasonStat] = []
    for reason, pairs in by_reason.items():
        pcts = [p for p, _ in pairs]
        pnls_for_reason = [pn for _, pn in pairs]
        wins = sum(1 for p in pcts if p > 0)
        exit_stats.append(
            ExitReasonStat(
                reason=reason,
                n_trades=len(pairs),
                avg_pnl_pct=sum(pcts) / len(pcts),
                win_rate=wins / len(pcts),
                total_pnl=sum(pnls_for_reason),
            )
        )
    exit_stats.sort(key=lambda s: s.n_trades, reverse=True)

    # --- by strategy -----------------------------------------------------
    by_strategy: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in rows:
        key = r.strategy or "unknown"
        by_strategy[key].append((float(r.pnl_pct), float(r.pnl)))
    strategy_stats: list[StrategyStat] = []
    for strat, pairs in by_strategy.items():
        pcts = [p for p, _ in pairs]
        pnls_for_strat = [pn for _, pn in pairs]
        wins = sum(1 for p in pcts if p > 0)
        strategy_stats.append(
            StrategyStat(
                strategy=strat,
                n_trades=len(pairs),
                avg_pnl_pct=sum(pcts) / len(pcts),
                win_rate=wins / len(pcts),
                total_pnl=sum(pnls_for_strat),
            )
        )
    strategy_stats.sort(key=lambda s: s.total_pnl, reverse=True)

    # --- hold-time histogram --------------------------------------------
    hold_groups: dict[tuple[int, int, str], list[float]] = defaultdict(list)
    for r in rows:
        bucket = _bucket_for_hold_days(r.hold_days)
        if bucket is None:
            continue
        hold_groups[bucket].append(float(r.pnl_pct))
    hold_buckets: list[HoldTimeBucket] = []
    for lo, hi, label in HOLD_BUCKETS:
        values = hold_groups.get((lo, hi, label), [])
        if values:
            wins = sum(1 for v in values if v > 0)
            hold_buckets.append(
                HoldTimeBucket(
                    label=label,
                    lower=lo,
                    upper=hi,
                    n_trades=len(values),
                    avg_pnl_pct=sum(values) / len(values),
                    win_rate=wins / len(values),
                )
            )
        else:
            hold_buckets.append(
                HoldTimeBucket(
                    label=label,
                    lower=lo,
                    upper=hi,
                    n_trades=0,
                )
            )

    # --- top winners / losers by ticker ---------------------------------
    by_ticker: dict[str, list[float]] = defaultdict(list)
    by_ticker_pnl: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_ticker[r.ticker].append(float(r.pnl_pct))
        by_ticker_pnl[r.ticker].append(float(r.pnl))
    per_ticker: list[TickerStat] = []
    for ticker, pcts in by_ticker.items():
        pnls_for_ticker = by_ticker_pnl[ticker]
        per_ticker.append(
            TickerStat(
                ticker=ticker,
                n_trades=len(pcts),
                total_pnl=sum(pnls_for_ticker),
                avg_pnl_pct=sum(pcts) / len(pcts),
            )
        )
    top_winners = sorted(per_ticker, key=lambda x: x.total_pnl, reverse=True)[:10]
    top_losers = sorted(per_ticker, key=lambda x: x.total_pnl)[:10]

    notes: list[str] = []
    if len(rows) < 30:
        notes.append(
            f"Only {len(rows)} closed trades — small-sample stats are noisy."
        )

    return TradeAnalytics(
        as_of=datetime.now(timezone.utc),
        headline=headline,
        cumulative_pnl=cumulative_pnl_points,
        by_exit_reason=exit_stats,
        by_strategy=strategy_stats,
        hold_time_distribution=hold_buckets,
        top_winners=top_winners,
        top_losers=top_losers,
        notes=notes,
    )
