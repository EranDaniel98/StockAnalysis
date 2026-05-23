"""Daily-pipeline endpoints.

Triggers ``scripts.run_daily_pipeline`` as a subprocess and streams
per-step progress to the client via SSE. One pipeline runs at a time;
a second request gets 409 with the in-flight start time.

Used by /scan (the page) — replaces the on-demand 5-engine scanner
with a button to re-run the live daily pipeline.

Also serves ``/today-actions``: the merged "what do I click in Alpaca
right now" view powering the /buy-signals page. Joins:

  - today's basket (picks JSON)
  - per-pick execution plan (portfolio_analysis JSON: entry / stop /
    target / sizing / time-exit / days-to-earnings)
  - AI sanity-check verdicts (ai_sanity_check JSON)
  - live paper positions (Alpaca)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src.execution.alpaca import AlpacaClient, AlpacaClientError

logger = logging.getLogger(__name__)
router = APIRouter()


# Ordered list of pipeline steps. Mirrors ``scripts.run_daily_pipeline.STEPS``.
# Surfacing it here lets the FE render the step ladder before any output
# arrives so the user sees the full plan immediately.
PIPELINE_STEPS = [
    "daily_factor_picks",
    "comprehensive_analysis",
    "exit_analysis",
    "position_monitor",
    "stress_test",
    "generate_watchlist",
    "ai_sanity_check",
    "morning_briefing",
    "paper_vs_spy_snapshot",
]

# Hard ceiling so a hung subprocess can't pin the lock forever.
_PIPELINE_TIMEOUT_S = 15 * 60  # 15 min

# Per-step output we keep for the FE to surface on failure. Keeps the
# server memory bounded even if a step screams thousands of stack lines.
_MAX_STEP_LINES = 50

# Singleton lock — one pipeline at a time. The asyncio.Lock instance is
# safe across coroutines on the same event loop, which is what uvicorn
# gives us for a single-worker dev process. The companion timestamp
# powers the 409 message ("started 2m ago").
_pipeline_lock = asyncio.Lock()
_pipeline_started_at: Optional[datetime] = None


# Log-line shape from scripts/run_daily_pipeline.py — keep these in sync
# with the logger.info / logger.error format strings there.
_STEP_START_RE = re.compile(r"STEP: ([A-Za-z_][A-Za-z0-9_]*)\s*$")
_STEP_DONE_RE = re.compile(
    r"STEP ([A-Za-z_][A-Za-z0-9_]*) exit code (-?\d+)\s*$"
)


ActionType = Literal["NEW_BUY", "KEEP", "EXIT"]
PositionStatus = Literal[
    "HOLDING", "STOP_HIT", "NEAR_STOP", "TARGET_HIT", "NEAR_TARGET",
]
SanityVerdict = Literal["KEEP", "FLAG", "VETO"]


class TodayActionItem(BaseModel):
    """One row in the /today-actions table. Carries everything the user
    needs to actually click Buy/Sell on Alpaca: ticker, action, target
    sizing, stop, target, plus live position state and any pre-trade
    warnings (sanity verdict, near-earnings flag, near-stop status)."""
    ticker: str
    action: ActionType
    sector: Optional[str] = None
    composite_z: Optional[float] = None

    # Strategy plan — present for NEW_BUY and KEEP. None for EXIT.
    entry_price: Optional[float] = None
    target_shares: Optional[int] = None
    position_size_usd: Optional[float] = None
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    expected_return_pct: Optional[float] = None
    time_exit_date: Optional[date] = None
    days_to_earnings: Optional[int] = None
    rationale: Optional[str] = None

    # Live state — present for KEEP and EXIT. None for NEW_BUY.
    current_shares: Optional[float] = None
    current_price: Optional[float] = None
    market_value: Optional[float] = None
    unrealized_pnl_usd: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    position_status: Optional[PositionStatus] = None

    # Sanity check — present for NEW_BUY and KEEP when ai_sanity_check ran.
    sanity_verdict: Optional[SanityVerdict] = None
    sanity_reason: Optional[str] = None
    sanity_evidence: Optional[str] = None


class TodayActionsResponse(BaseModel):
    picks_date: Optional[date] = None
    sources: dict[str, Optional[str]] = Field(
        default_factory=dict,
        description=(
            "Filenames consulted, keyed by role: picks / analysis / "
            "sanity. Null when the file didn't exist; FE surfaces the "
            "gap so the user knows what's stale."
        ),
    )
    n_picks_today: int = Field(default=0, ge=0)
    n_positions: int = Field(default=0, ge=0)
    new_buys: list[TodayActionItem] = Field(default_factory=list)
    keeps: list[TodayActionItem] = Field(default_factory=list)
    exits: list[TodayActionItem] = Field(default_factory=list)
    n_at_risk: int = Field(
        default=0, ge=0,
        description="Held positions with status != HOLDING (urgent action).",
    )
    n_sanity_flagged: int = Field(
        default=0, ge=0,
        description="Picks the AI sanity check flagged FLAG or VETO.",
    )


class PipelineRecentRun(BaseModel):
    """One historical pipeline-or-picks invocation, derived from disk
    artifacts. Used by /scan to list the last few runs."""
    picks_date: date
    picks_generated_at: datetime = Field(
        description="Mtime of data/daily_picks/<date>.json — proxy for run time.",
    )
    n_picks: int
    has_analysis: bool
    has_briefing: bool
    has_exit_plan: bool
    has_sanity_check: bool


class PipelineRecentResponse(BaseModel):
    runs: list[PipelineRecentRun] = Field(default_factory=list)
    in_flight: bool = Field(
        description="True if a pipeline run is currently executing.",
    )
    in_flight_started_at: Optional[datetime] = None


# Fallback bands for held positions that aren't in today's basket (no
# strategy plan). Mirrors briefing.py / portfolio.py constants — keep
# the three in sync, or factor into a single helper if a fourth caller
# arrives.
_FALLBACK_STOP_PCT = 0.08
_FALLBACK_TARGET_PCT = 0.10
_NEAR_STOP_MULT = 1.02
_NEAR_TARGET_MULT = 0.98


def _classify_position(
    current: float, stop: float, target: float,
) -> PositionStatus:
    if current <= stop:
        return "STOP_HIT"
    if current >= target:
        return "TARGET_HIT"
    if current <= stop * _NEAR_STOP_MULT:
        return "NEAR_STOP"
    if current >= target * _NEAR_TARGET_MULT:
        return "NEAR_TARGET"
    return "HOLDING"


def _safe_float(v) -> Optional[float]:
    """Tolerate None / NaN / non-numeric / Pydantic-rejecting cases."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _safe_int(v) -> Optional[int]:
    f = _safe_float(v)
    if f is None:
        return None
    try:
        return int(f)
    except (TypeError, ValueError):
        return None


async def _fetch_positions_safe() -> list[dict]:
    """Same fail-soft pattern as briefing.py: missing creds / Alpaca
    outage degrades to an empty positions list so the actions page
    still renders (it'll just show NEW_BUYs without KEEPs/EXITs)."""
    try:
        client = AlpacaClient()
    except AlpacaClientError as e:
        logger.warning("Alpaca client unavailable: %s", e)
        return []
    try:
        return await asyncio.to_thread(client.get_positions)
    except Exception as e:  # noqa: BLE001
        logger.warning("Alpaca get_positions failed: %s", e)
        return []


def _load_picks_for(picks_date: Optional[date]) -> tuple[Optional[Path], Optional[dict]]:
    """Pick file resolution. If ``picks_date`` is None or that day's
    file is missing, fall back to the freshest on disk so the page
    doesn't go blank on a missed-pipeline morning."""
    picks_dir = Path("data/daily_picks")
    if picks_date is not None:
        candidate = picks_dir / f"{picks_date.isoformat()}.json"
        if candidate.exists():
            try:
                return candidate, json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Bad picks JSON %s: %s", candidate, e)
                return candidate, None
    if not picks_dir.exists():
        return None, None
    candidates = sorted(picks_dir.glob("*.json"))
    if not candidates:
        return None, None
    latest = candidates[-1]
    try:
        return latest, json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Bad picks JSON %s: %s", latest, e)
        return latest, None


def _load_analysis_for(picks_date: date) -> tuple[Optional[Path], dict[str, dict]]:
    """portfolio_analysis_*.json keyed by ticker, for the same date."""
    us = picks_date.isoformat().replace("-", "_")
    p = Path("reports") / f"portfolio_analysis_{us}.json"
    if not p.exists():
        return p, {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Bad analysis JSON %s: %s", p, e)
        return p, {}
    return p, {row["ticker"]: row for row in data.get("picks", []) if isinstance(row, dict)}


def _load_sanity_for(picks_date: date) -> tuple[Optional[Path], dict[str, dict]]:
    """ai_sanity_check_*.json (dash-separated date) keyed by ticker."""
    p = Path("reports") / f"ai_sanity_check_{picks_date.isoformat()}.json"
    if not p.exists():
        return p, {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Bad sanity JSON %s: %s", p, e)
        return p, {}
    per_pick = (data.get("verdict") or {}).get("per_pick", []) or []
    return p, {
        row["ticker"]: row for row in per_pick if isinstance(row, dict)
    }


def _build_new_buy(
    ticker: str, plan: Optional[dict], pick: Optional[dict],
    sanity: Optional[dict],
) -> TodayActionItem:
    """A NEW_BUY: not currently held, in today's basket. All the data we
    have is forward-looking (entry/stop/target/sizing/rationale)."""
    return TodayActionItem(
        ticker=ticker,
        action="NEW_BUY",
        sector=(plan or {}).get("sector") or (pick or {}).get("sector"),
        composite_z=_safe_float((pick or {}).get("z_score")),
        entry_price=_safe_float((plan or {}).get("entry_price")),
        target_shares=_safe_int((plan or {}).get("target_shares")),
        position_size_usd=_safe_float((plan or {}).get("position_size_usd")),
        stop_loss=_safe_float((plan or {}).get("stop_loss")),
        target=_safe_float((plan or {}).get("target")),
        expected_return_pct=_safe_float((plan or {}).get("expected_return_pct")),
        time_exit_date=_parse_iso_date((plan or {}).get("time_exit_date")),
        days_to_earnings=_safe_int((plan or {}).get("days_to_earnings")),
        rationale=(plan or {}).get("rationale"),
        sanity_verdict=(sanity or {}).get("verdict"),
        sanity_reason=(sanity or {}).get("reason"),
        sanity_evidence=(sanity or {}).get("evidence"),
    )


def _build_keep(
    ticker: str, plan: Optional[dict], pick: Optional[dict],
    sanity: Optional[dict], pos: dict,
) -> TodayActionItem:
    """A KEEP: currently held AND in today's basket. Merge forward plan
    + live position. position_status is computed from current vs the
    strategy stop/target (or fallback bands when no plan exists)."""
    current = _safe_float(pos.get("current_price")) or 0.0
    avg_entry = _safe_float(pos.get("avg_price")) or 0.0
    if plan and _safe_float(plan.get("stop_loss")) and _safe_float(plan.get("target")):
        stop = float(plan["stop_loss"])
        target = float(plan["target"])
    elif avg_entry > 0:
        stop = avg_entry * (1 - _FALLBACK_STOP_PCT)
        target = avg_entry * (1 + _FALLBACK_TARGET_PCT)
    else:
        stop = 0.0
        target = 0.0
    status: Optional[PositionStatus] = (
        _classify_position(current, stop, target)
        if current > 0 and stop > 0 and target > 0 else None
    )
    return TodayActionItem(
        ticker=ticker,
        action="KEEP",
        sector=(plan or {}).get("sector") or (pick or {}).get("sector"),
        composite_z=_safe_float((pick or {}).get("z_score")),
        entry_price=_safe_float((plan or {}).get("entry_price")),
        target_shares=_safe_int((plan or {}).get("target_shares")),
        position_size_usd=_safe_float((plan or {}).get("position_size_usd")),
        stop_loss=stop if stop > 0 else None,
        target=target if target > 0 else None,
        expected_return_pct=_safe_float((plan or {}).get("expected_return_pct")),
        time_exit_date=_parse_iso_date((plan or {}).get("time_exit_date")),
        days_to_earnings=_safe_int((plan or {}).get("days_to_earnings")),
        rationale=(plan or {}).get("rationale"),
        current_shares=_safe_float(pos.get("shares")),
        current_price=current if current > 0 else None,
        market_value=_safe_float(pos.get("market_value")),
        unrealized_pnl_usd=_safe_float(pos.get("unrealized_pnl")),
        unrealized_pnl_pct=_safe_float(pos.get("unrealized_pnl_pct")),
        position_status=status,
        sanity_verdict=(sanity or {}).get("verdict"),
        sanity_reason=(sanity or {}).get("reason"),
        sanity_evidence=(sanity or {}).get("evidence"),
    )


def _build_exit(ticker: str, pos: dict) -> TodayActionItem:
    """An EXIT: currently held, not in today's basket. No strategy plan
    available (ticker dropped out); use fallback ±8% / +10% bands for
    status classification so the position-monitor stop/target columns
    stay populated."""
    current = _safe_float(pos.get("current_price")) or 0.0
    avg_entry = _safe_float(pos.get("avg_price")) or 0.0
    stop = avg_entry * (1 - _FALLBACK_STOP_PCT) if avg_entry > 0 else 0.0
    target = avg_entry * (1 + _FALLBACK_TARGET_PCT) if avg_entry > 0 else 0.0
    status: Optional[PositionStatus] = (
        _classify_position(current, stop, target)
        if current > 0 and stop > 0 else None
    )
    return TodayActionItem(
        ticker=ticker,
        action="EXIT",
        stop_loss=stop if stop > 0 else None,
        target=target if target > 0 else None,
        current_shares=_safe_float(pos.get("shares")),
        current_price=current if current > 0 else None,
        market_value=_safe_float(pos.get("market_value")),
        unrealized_pnl_usd=_safe_float(pos.get("unrealized_pnl")),
        unrealized_pnl_pct=_safe_float(pos.get("unrealized_pnl_pct")),
        position_status=status,
    )


def _parse_iso_date(v) -> Optional[date]:
    if not isinstance(v, str):
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


@router.get("/today-actions", response_model=TodayActionsResponse)
async def get_today_actions(
    picks_date: Optional[date] = Query(
        default=None,
        description="YYYY-MM-DD. Defaults to the freshest picks file on disk.",
    ),
) -> TodayActionsResponse:
    """Merged execution view powering /buy-signals. Set-diff today's
    picks against current holdings + join each row with its analysis
    plan + AI sanity verdict + (for held tickers) live state."""
    picks_path, picks_payload = _load_picks_for(picks_date)
    positions = await _fetch_positions_safe()

    sources: dict[str, Optional[str]] = {
        "picks": picks_path.name if picks_path and picks_path.exists() else None,
        "analysis": None,
        "sanity": None,
    }

    pick_rows: list[dict] = []
    resolved_date: Optional[date] = None
    if picks_payload:
        pick_rows = [
            p for p in (picks_payload.get("picks") or [])
            if isinstance(p, dict)
        ]
        as_of = picks_payload.get("as_of")
        if isinstance(as_of, str):
            resolved_date = _parse_iso_date(as_of)
        if resolved_date is None and picks_path:
            resolved_date = _parse_iso_date(picks_path.stem)

    plans: dict[str, dict] = {}
    sanity: dict[str, dict] = {}
    if resolved_date is not None:
        analysis_path, plans = _load_analysis_for(resolved_date)
        sanity_path, sanity = _load_sanity_for(resolved_date)
        sources["analysis"] = (
            analysis_path.name if analysis_path and analysis_path.exists() else None
        )
        sources["sanity"] = (
            sanity_path.name if sanity_path and sanity_path.exists() else None
        )

    pick_by_ticker = {
        (p.get("ticker") or "").upper(): p for p in pick_rows if p.get("ticker")
    }
    pick_set = set(pick_by_ticker.keys())
    pos_by_ticker = {
        (p.get("ticker") or "").upper(): p
        for p in positions if isinstance(p, dict) and p.get("ticker")
    }
    pos_set = set(pos_by_ticker.keys())

    new_buy_tickers = sorted(pick_set - pos_set)
    keep_tickers = sorted(pick_set & pos_set)
    exit_tickers = sorted(pos_set - pick_set)

    new_buys = [
        _build_new_buy(
            t,
            plans.get(t),
            pick_by_ticker.get(t),
            sanity.get(t),
        )
        for t in new_buy_tickers
    ]
    keeps = [
        _build_keep(
            t,
            plans.get(t),
            pick_by_ticker.get(t),
            sanity.get(t),
            pos_by_ticker[t],
        )
        for t in keep_tickers
    ]
    exits = [
        _build_exit(t, pos_by_ticker[t]) for t in exit_tickers
    ]

    # Sort: exits and keeps worst-first by urgency, new_buys by composite_z
    # (best signal first since the FE leads with them).
    urgency_rank = {
        "STOP_HIT": 0, "NEAR_STOP": 1, "TARGET_HIT": 2, "NEAR_TARGET": 3,
        "HOLDING": 4,
    }
    keeps.sort(
        key=lambda r: (urgency_rank.get(r.position_status or "HOLDING", 9), r.ticker),
    )
    exits.sort(
        key=lambda r: (urgency_rank.get(r.position_status or "HOLDING", 9), r.ticker),
    )
    new_buys.sort(
        key=lambda r: (-(r.composite_z or 0.0), r.ticker),
    )

    n_at_risk = sum(
        1 for r in (*keeps, *exits)
        if r.position_status and r.position_status != "HOLDING"
    )
    n_sanity_flagged = sum(
        1 for r in (*new_buys, *keeps)
        if r.sanity_verdict in ("FLAG", "VETO")
    )

    return TodayActionsResponse(
        picks_date=resolved_date,
        sources=sources,
        n_picks_today=len(pick_set),
        n_positions=len(positions),
        new_buys=new_buys,
        keeps=keeps,
        exits=exits,
        n_at_risk=n_at_risk,
        n_sanity_flagged=n_sanity_flagged,
    )


@router.get("/recent", response_model=PipelineRecentResponse)
async def get_recent(limit: int = Query(default=5, ge=1, le=30)) -> PipelineRecentResponse:
    """List the last ``limit`` pipeline-style runs by inspecting disk
    artifacts. Each entry says which downstream files exist so the FE
    can show a per-step completion mark."""
    picks_dir = Path("data/daily_picks")
    reports_dir = Path("reports")

    runs: list[PipelineRecentRun] = []
    if picks_dir.exists():
        # Sorted by name = sorted by ISO date.
        candidates = sorted(
            (f for f in picks_dir.glob("*.json") if not f.is_dir()),
            reverse=True,
        )
        for f in candidates[:limit]:
            try:
                payload = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            stem = f.stem  # "2026-05-23"
            try:
                d = date.fromisoformat(stem)
            except ValueError:
                continue
            us = stem.replace("-", "_")
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            runs.append(PipelineRecentRun(
                picks_date=d,
                picks_generated_at=mtime,
                n_picks=len(payload.get("picks", []) or []),
                has_analysis=(reports_dir / f"portfolio_analysis_{us}.json").exists(),
                has_briefing=(reports_dir / f"morning_briefing_{us}.md").exists(),
                has_exit_plan=(reports_dir / f"exit_plan_{us}.md").exists(),
                has_sanity_check=(reports_dir / f"ai_sanity_check_{stem}.json").exists(),
            ))

    return PipelineRecentResponse(
        runs=runs,
        in_flight=_pipeline_lock.locked(),
        in_flight_started_at=_pipeline_started_at if _pipeline_lock.locked() else None,
    )


@router.get("/stream")
async def stream_pipeline(
    request: Request,
    picks_date: Optional[date] = Query(
        default=None,
        description="YYYY-MM-DD. Defaults to today's UTC date.",
    ),
    top_n: int = Query(default=15, ge=1, le=50),
) -> EventSourceResponse:
    """Spawn ``scripts.run_daily_pipeline`` and stream per-step progress.

    SSE event types:
      - ``ready``           {steps:[...]}    sent once before subprocess starts
      - ``step_started``    {step, ts}       new step begins
      - ``step_completed``  {step, exit_code, elapsed_s, tail:[...]}
      - ``heartbeat``       {}               keepalive every ~1s during quiet stretches
      - ``done``            {exit_code, total_elapsed_s, steps:{name: exit_code}}
      - ``error``           {detail}         setup error or 409 conflict
    """
    if _pipeline_lock.locked():
        # Don't enqueue — fail fast so the FE can show a clear conflict
        # message rather than mysteriously hanging.
        return EventSourceResponse(
            _emit_busy_event(_pipeline_started_at),
            media_type="text/event-stream",
        )
    return EventSourceResponse(
        _pipeline_event_stream(request, picks_date, top_n),
    )


async def _emit_busy_event(
    started_at: Optional[datetime],
) -> AsyncIterator[dict]:
    """One-shot generator that emits a 'busy' error event then closes.
    Used when another pipeline run is already in flight."""
    yield {
        "event": "error",
        "data": json.dumps({
            "detail": "pipeline already running",
            "started_at": started_at.isoformat() if started_at else None,
        }),
    }


async def _pipeline_event_stream(
    request: Request,
    picks_date: Optional[date],
    top_n: int,
) -> AsyncIterator[dict]:
    """Acquire the lock, spawn the pipeline, parse its log output, emit
    SSE events per step transition. Drops the subprocess on client
    disconnect or timeout."""
    global _pipeline_started_at

    # acquire_nowait would be cleaner but isn't on asyncio.Lock; use the
    # locked() guard pattern. The window between check + acquire is OK
    # because we're single-threaded inside the event loop.
    await _pipeline_lock.acquire()
    _pipeline_started_at = datetime.now(timezone.utc)
    started_monotonic = time.monotonic()

    yield {
        "event": "ready",
        "data": json.dumps({
            "steps": PIPELINE_STEPS,
            "started_at": _pipeline_started_at.isoformat(),
            "picks_date": picks_date.isoformat() if picks_date else None,
            "top_n": top_n,
        }),
    }

    # Build the subprocess command. Inherit env + force unbuffered Python
    # so log lines flow through to our reader without 8KB block delays.
    cmd = ["uv", "run", "python", "-u", "-m", "scripts.run_daily_pipeline",
           "--top-n", str(top_n)]
    if picks_date is not None:
        cmd.extend(["--picks-date", picks_date.isoformat()])
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}

    proc: Optional[asyncio.subprocess.Process] = None
    current_step: Optional[str] = None
    current_step_started: Optional[float] = None
    current_step_lines: list[str] = []
    step_exit_codes: dict[str, int] = {}

    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
        except (OSError, FileNotFoundError) as e:
            yield {
                "event": "error",
                "data": json.dumps({"detail": f"spawn failed: {e}"}),
            }
            return

        # Drain stdout. We read lines with a small timeout so we can
        # interleave heartbeats and disconnect checks.
        assert proc.stdout is not None
        deadline = time.monotonic() + _PIPELINE_TIMEOUT_S
        while True:
            if time.monotonic() > deadline:
                yield {
                    "event": "error",
                    "data": json.dumps({"detail": "pipeline timeout (15 min)"}),
                }
                break

            if await request.is_disconnected():
                logger.info("pipeline stream client disconnected — killing subprocess")
                break

            try:
                line_bytes = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=1.0,
                )
            except asyncio.TimeoutError:
                yield {"event": "heartbeat", "data": "{}"}
                continue

            if not line_bytes:
                # EOF — subprocess exited
                break

            line = line_bytes.decode("utf-8", errors="replace").rstrip()

            # Capture step-tail context for failure surfacing.
            if current_step:
                current_step_lines.append(line)
                if len(current_step_lines) > _MAX_STEP_LINES:
                    current_step_lines = current_step_lines[-_MAX_STEP_LINES:]

            m_start = _STEP_START_RE.search(line)
            if m_start:
                # Previous step (if any) didn't emit a done line — happens
                # when the subprocess crashes hard. Emit a synthetic "?"
                # completion so the FE doesn't show two simultaneous
                # running steps.
                if current_step is not None and current_step not in step_exit_codes:
                    elapsed = (
                        time.monotonic() - current_step_started
                        if current_step_started else 0.0
                    )
                    yield {
                        "event": "step_completed",
                        "data": json.dumps({
                            "step": current_step,
                            "exit_code": -1,
                            "elapsed_s": round(elapsed, 2),
                            "tail": current_step_lines[-_MAX_STEP_LINES:],
                            "synthetic": True,
                        }),
                    }
                current_step = m_start.group(1)
                current_step_started = time.monotonic()
                current_step_lines = []
                yield {
                    "event": "step_started",
                    "data": json.dumps({
                        "step": current_step,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }),
                }
                continue

            m_done = _STEP_DONE_RE.search(line)
            if m_done:
                step_name = m_done.group(1)
                exit_code = int(m_done.group(2))
                step_exit_codes[step_name] = exit_code
                elapsed = (
                    time.monotonic() - current_step_started
                    if current_step_started else 0.0
                )
                yield {
                    "event": "step_completed",
                    "data": json.dumps({
                        "step": step_name,
                        "exit_code": exit_code,
                        "elapsed_s": round(elapsed, 2),
                        # Tail only useful when the step failed; include
                        # always for tooltip simplicity, FE can decide.
                        "tail": current_step_lines[-_MAX_STEP_LINES:],
                    }),
                }
                current_step = None
                current_step_started = None
                current_step_lines = []

        # Drain rest of subprocess (let it exit cleanly when possible).
        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            rc = -1

        yield {
            "event": "done",
            "data": json.dumps({
                "exit_code": rc,
                "total_elapsed_s": round(time.monotonic() - started_monotonic, 2),
                "steps": step_exit_codes,
            }),
        }

    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    try:
                        await proc.wait()
                    except Exception:  # noqa: BLE001
                        pass
            except ProcessLookupError:
                pass
        _pipeline_started_at = None
        _pipeline_lock.release()
