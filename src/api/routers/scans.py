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
from src.api.schemas.sanity import SanityCheck
from src.api.schemas.scan import (
    BuySignal,
    SanityCheckTriggerRequest,
    ScanRequest,
    ScanResponse,
    ScanResultItem,
    ScanSummary,
)
from src.api.services.factor_picks_reader import load_latest_factor_picks
from src.api.services.scan_runner import run_scan_sync
from src.config_loader import Config
from src.db.models import SanityCheckRow, ScanRun
from src.research_agent.sanity_check import check_buy_signal_auto
from src.research_agent.sanity_evidence import build_sanity_inputs

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
        run_id=run_id,
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
                run_id=r.run_id,
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


async def _load_cached_sanity_checks(
    db: AsyncSession, run_ids: list[str],
) -> dict[tuple[str, str], SanityCheck]:
    """Return ``{(ticker, run_id): SanityCheck}`` for the given run_ids.

    Empty dict when none cached. Caller looks up by (ticker, run_id)
    when building each BuySignal — a miss leaves ``sanity_check=None``,
    which the FE renders as "no check run yet".
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
            # Strategy-level data filter (e.g. dividend_income +
            # non-payer). Belt-and-suspenders alongside the
            # recommender's HOLD/None forcing — also blocks any legacy
            # row whose action wasn't normalized at scan time.
            if rec.get("strategy_filter_failed"):
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

    # Single batched lookup for cached sanity checks across every
    # attributed run_id — avoids N+1 SELECTs when the FE renders 10+
    # rows. Miss → sanity_check stays None, FE renders "no check yet".
    run_ids = [entry["best_run"].run_id for entry in bucket.values()]
    sanity_cache = await _load_cached_sanity_checks(db, run_ids)

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
                run_id=run.run_id,
                consensus_count=len(entry["strategies"]),
                consensus_strategies=sorted(set(entry["strategies"])),
                sub_scores={
                    k: float(v)
                    for k, v in (rec.get("sub_scores") or {}).items()
                    if isinstance(v, (int, float))
                },
                earnings_announcement_ts=rec.get("earnings_announcement_ts"),
                earnings_call_ts=rec.get("earnings_call_ts"),
                sanity_check=sanity_cache.get((ticker, run.run_id)),
            )
        )

    out.sort(
        key=lambda b: (-b.composite_score, -b.consensus_count, b.ticker),
    )
    return out


@router.get("/factor-picks", response_model=list[BuySignal])
async def factor_picks(
    db: AsyncSession = Depends(get_db_session),
) -> list[BuySignal]:
    """Today's composite-factor picks (PIT S&P 500, m+q+v rank-blend).

    Reads from ``data/daily_picks/YYYY-MM-DD.json`` — the source the
    paper trader uses to place real (paper) orders. This is the
    canonical "what does the system want to BUY?" surface for the
    factor strategy. Sanity-check verdicts (cached against the
    synthetic ``factor:<strategy>:<as_of>`` run_id) are attached when
    present so the web UI can render the same brake-light pattern as
    the composite-path /latest-buys endpoint.

    Returns an empty list when no picks file exists (system not yet
    bootstrapped) or when the file is malformed — by design, since
    the scoring-path /latest-buys endpoint is a viable fallback for
    the FE.
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


@router.post("/sanity-check", response_model=list[BuySignal])
async def trigger_sanity_check(
    body: SanityCheckTriggerRequest,
    db: AsyncSession = Depends(get_db_session),
) -> list[BuySignal]:
    """Run the pre-trade AI sanity check over the current BuySignal set.

    Reuses ``latest_buys`` to assemble the candidate set (same DISTINCT
    ON / integrity-gate filtering), then runs the check on each row in
    parallel, upserts results into the ``sanity_checks`` table, and
    returns the refreshed BuySignal list with ``sanity_check``
    populated.

    Cost: ~$0.005/ticker on the live path (claude-sonnet-4-6); mock
    path is free. The check is asymmetric — it can downgrade BUYs to
    CAUTION or REJECT but never upgrade them.

    Idempotency: ``force_refresh=false`` skips tickers that already
    have a cached check for their run_id. Set ``force_refresh=true``
    to overwrite (e.g. after re-running with the live model).
    """
    candidates = await latest_buys(strong_only=body.strong_only, db=db)
    if not candidates:
        return []

    # Optional cache skip — keep the loop small when the operator just
    # wants to top up missing rows.
    if not body.force_refresh:
        existing_keys = {
            (c.ticker, c.run_id) for c in candidates if c.sanity_check is not None
        }
        targets = [c for c in candidates if (c.ticker, c.run_id) not in existing_keys]
    else:
        targets = list(candidates)

    async def _run_one(buy: BuySignal) -> tuple[BuySignal, SanityCheck]:
        inputs = await build_sanity_inputs(
            db=db,
            ticker=buy.ticker,
            composite_score=buy.composite_score,
            action=buy.action,
        )
        check = await check_buy_signal_auto(inputs, mode=body.mode)
        return buy, check

    # Run checks concurrently. asyncio.gather over ~10 tickers @ 30s
    # timeout each = ~30s wall-clock vs ~5 min serial. The Anthropic
    # client honors the per-call timeout, so a stuck call doesn't
    # block the batch.
    results = await asyncio.gather(
        *[_run_one(buy) for buy in targets], return_exceptions=True,
    )

    upserts = 0
    for outcome in results:
        if isinstance(outcome, BaseException):
            logger.exception("sanity-check task failed", exc_info=outcome)
            continue
        buy, check = outcome
        await _upsert_sanity_check(db, ticker=buy.ticker, run_id=buy.run_id, check=check)
        upserts += 1
    if upserts:
        await db.commit()

    # Re-read so the caller sees the refreshed sanity_check field.
    return await latest_buys(strong_only=body.strong_only, db=db)


async def _upsert_sanity_check(
    db: AsyncSession,
    *,
    ticker: str,
    run_id: str,
    check: SanityCheck,
) -> None:
    """Upsert one sanity-check row by (ticker, run_id).

    Plain SELECT-then-INSERT/UPDATE rather than PG-specific
    ``ON CONFLICT`` — the unique constraint is enforced at the DB level
    and the table is small enough that the extra round-trip doesn't
    matter. Caller commits.
    """
    stmt = (
        select(SanityCheckRow)
        .where(SanityCheckRow.ticker == ticker)
        .where(SanityCheckRow.run_id == run_id)
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()

    checked_at_dt = _parse_iso_or_now(check.checked_at)
    if existing is None:
        db.add(
            SanityCheckRow(
                ticker=ticker,
                run_id=run_id,
                verdict=check.verdict,
                reason=check.reason,
                catalysts_found=list(check.catalysts_found),
                confidence=check.confidence,
                model_used=check.model_used,
                mocked=check.mocked,
                checked_at=checked_at_dt,
            )
        )
    else:
        existing.verdict = check.verdict
        existing.reason = check.reason
        existing.catalysts_found = list(check.catalysts_found)
        existing.confidence = check.confidence
        existing.model_used = check.model_used
        existing.mocked = check.mocked
        existing.checked_at = checked_at_dt


def _parse_iso_or_now(value: str | None) -> datetime:
    """Parse the SanityCheck.checked_at ISO string. ``None`` or a
    malformed value falls through to the current UTC time — the field
    is provenance, not load-bearing.
    """
    if value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


@router.get("/{run_id}", response_model=ScanResponse)
async def get_scan(
    run_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> ScanResponse:
    stmt = (
        select(ScanRun)
        .where(ScanRun.run_id == run_id)
        .order_by(desc(ScanRun.scan_timestamp))
        .limit(1)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="scan not found")

    results = [ScanResultItem.model_validate(r) for r in row.recommendations]
    return ScanResponse(
        run_id=row.run_id,
        strategy=row.strategy,
        scan_timestamp=row.scan_timestamp,
        n_candidates=row.n_candidates,
        n_results=len(results),
        results=results,
    )
