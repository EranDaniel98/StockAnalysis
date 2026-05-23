"""Daily-pipeline endpoints.

Triggers ``scripts.run_daily_pipeline`` as a subprocess and streams
per-step progress to the client via SSE. One pipeline runs at a time;
a second request gets 409 with the in-flight start time.

Used by /scan (the page) — replaces the on-demand 5-engine scanner
with a button to re-run the live daily pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

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
