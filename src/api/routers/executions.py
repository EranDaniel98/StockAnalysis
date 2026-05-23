"""Paper-trade execution log endpoints.

Reads the on-disk per-day artifacts written by
``scripts.paper_trade_factor_picks`` to
``data/daily_picks/execution_log/YYYY-MM-DD.json``. Each file records:

  - account state at start (equity, capital splits)
  - basket shape (longs, shorts)
  - AI sanity-gate decision per pick (kept / rejected / cautioned)
  - submitted orders (with order_id, client_order_id, stop, target)
  - skipped + failed orders with reasons / errors

Replaces the legacy ``/api/recommendations`` DB log (5-engine,
``swing_trading`` only, last entry weeks old) on the FE.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date as _date, datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()

EXEC_DIR = Path("data/daily_picks/execution_log")


# ----------------------------- models ------------------------------


class SubmittedOrder(BaseModel):
    """One Alpaca order that landed (or was queued). Fields mirror the
    JSON shape verbatim — every key is defensive Optional so older log
    versions without long_short or sanity context still parse."""
    ticker: str
    side: Optional[str] = None
    qty: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    basis: Optional[str] = None
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    status: Optional[str] = None
    submitted_at: Optional[datetime] = None


class SkippedOrder(BaseModel):
    ticker: str
    side: Optional[str] = None
    reason: Optional[str] = None


class FailedOrder(BaseModel):
    ticker: str
    side: Optional[str] = None
    error: Optional[str] = None


class SanityGateOutcome(BaseModel):
    """Per-ticker AI sanity verdict captured at execution time. Same shape
    as the standalone ai_sanity_check_*.json per-pick rows."""
    verdict: Optional[str] = None  # "OK" / "CAUTION" / "REJECT" historically
    reason: Optional[str] = None
    confidence: Optional[float] = None
    model: Optional[str] = None
    mocked: Optional[bool] = None


class SanityGate(BaseModel):
    applied: bool = False
    mode: Optional[str] = None  # "auto" / "off" / etc.
    long_kept: list[str] = Field(default_factory=list)
    long_rejected: list[str] = Field(default_factory=list)
    long_cautioned: list[str] = Field(default_factory=list)
    short_kept: list[str] = Field(default_factory=list)
    short_rejected: list[str] = Field(default_factory=list)
    short_cautioned: list[str] = Field(default_factory=list)
    long_outcomes: dict[str, SanityGateOutcome] = Field(default_factory=dict)
    short_outcomes: dict[str, SanityGateOutcome] = Field(default_factory=dict)


class ExecutionSummary(BaseModel):
    """One row in the executions list view."""
    # Field name kept as 'date' on the wire for FE clarity. We renamed the
    # type import to ``_date`` so it doesn't shadow this Pydantic field
    # (Pydantic 2 errors on annotation/field name collisions).
    date: _date = Field(description="picks_date from the log file.")
    executed_at_utc: Optional[datetime] = None
    strategy: str
    long_short_mode: Optional[bool] = None
    equity_at_start: Optional[float] = None
    long_capital: Optional[float] = None
    short_capital: Optional[float] = None
    n_longs: int = 0
    n_shorts: int = 0
    n_submitted: int = 0
    n_skipped: int = 0
    n_failed: int = 0
    sanity_applied: bool = False
    sanity_long_rejected: int = 0
    sanity_long_cautioned: int = 0
    order_style: Optional[str] = None


class ExecutionDetail(ExecutionSummary):
    sanity_gate: Optional[SanityGate] = None
    submitted: list[SubmittedOrder] = Field(default_factory=list)
    skipped: list[SkippedOrder] = Field(default_factory=list)
    failed: list[FailedOrder] = Field(default_factory=list)


# ----------------------------- helpers ------------------------------


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _safe_int(v) -> int:
    f = _safe_float(v)
    if f is None:
        return 0
    try:
        return int(f)
    except (TypeError, ValueError):
        return 0


def _parse_date(v) -> Optional[_date]:
    if not isinstance(v, str):
        return None
    try:
        return _date.fromisoformat(v[:10])
    except ValueError:
        return None


def _parse_datetime(v) -> Optional[datetime]:
    if not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


def _build_summary(payload: dict, path: Path) -> ExecutionSummary:
    """Project the raw JSON into the wire summary. Defensive on every
    key so a partially-formed log doesn't 500 the list endpoint."""
    submitted = payload.get("submitted") or []
    skipped = payload.get("skipped") or []
    failed = payload.get("failed") or []
    sanity = payload.get("sanity_gate") or {}
    long_rejected = (
        len(sanity.get("long_rejected") or [])
        if isinstance(sanity, dict) else 0
    )
    long_cautioned = (
        len(sanity.get("long_cautioned") or [])
        if isinstance(sanity, dict) else 0
    )
    # Fall back to filename date when picks_date is missing.
    d = _parse_date(payload.get("picks_date")) or _parse_date(path.stem)
    if d is None:
        raise ValueError(f"Could not resolve a date for {path.name}")
    return ExecutionSummary(
        date=d,
        executed_at_utc=_parse_datetime(payload.get("executed_at_utc")),
        strategy=str(payload.get("strategy") or "unknown"),
        long_short_mode=(
            bool(payload["long_short_mode"])
            if "long_short_mode" in payload else None
        ),
        equity_at_start=_safe_float(payload.get("equity_at_start")),
        long_capital=_safe_float(payload.get("long_capital")),
        short_capital=_safe_float(payload.get("short_capital")),
        n_longs=_safe_int(payload.get("n_longs")),
        n_shorts=_safe_int(payload.get("n_shorts")),
        n_submitted=len(submitted) if isinstance(submitted, list) else 0,
        n_skipped=len(skipped) if isinstance(skipped, list) else 0,
        n_failed=len(failed) if isinstance(failed, list) else 0,
        sanity_applied=bool(sanity.get("applied")) if isinstance(sanity, dict) else False,
        sanity_long_rejected=long_rejected,
        sanity_long_cautioned=long_cautioned,
        order_style=payload.get("order_style"),
    )


def _parse_submitted(raw: dict) -> Optional[SubmittedOrder]:
    if not isinstance(raw, dict) or not raw.get("ticker"):
        return None
    return SubmittedOrder(
        ticker=str(raw["ticker"]),
        side=raw.get("side"),
        qty=_safe_float(raw.get("qty")),
        stop_loss=_safe_float(raw.get("stop_loss")),
        take_profit=_safe_float(raw.get("take_profit")),
        basis=raw.get("basis"),
        order_id=raw.get("order_id"),
        client_order_id=raw.get("client_order_id"),
        status=raw.get("status"),
        submitted_at=_parse_datetime(raw.get("submitted_at")),
    )


def _parse_skipped(raw: dict) -> Optional[SkippedOrder]:
    if not isinstance(raw, dict) or not raw.get("ticker"):
        return None
    return SkippedOrder(
        ticker=str(raw["ticker"]),
        side=raw.get("side"),
        reason=raw.get("reason"),
    )


def _parse_failed(raw: dict) -> Optional[FailedOrder]:
    if not isinstance(raw, dict) or not raw.get("ticker"):
        return None
    return FailedOrder(
        ticker=str(raw["ticker"]),
        side=raw.get("side"),
        error=raw.get("error"),
    )


def _parse_sanity_gate(raw) -> Optional[SanityGate]:
    if not isinstance(raw, dict):
        return None
    long_out: dict[str, SanityGateOutcome] = {}
    for t, payload in (raw.get("long_outcomes") or {}).items():
        if isinstance(payload, dict):
            long_out[str(t)] = SanityGateOutcome(
                verdict=payload.get("verdict"),
                reason=payload.get("reason"),
                confidence=_safe_float(payload.get("confidence")),
                model=payload.get("model"),
                mocked=(
                    bool(payload["mocked"]) if "mocked" in payload else None
                ),
            )
    short_out: dict[str, SanityGateOutcome] = {}
    for t, payload in (raw.get("short_outcomes") or {}).items():
        if isinstance(payload, dict):
            short_out[str(t)] = SanityGateOutcome(
                verdict=payload.get("verdict"),
                reason=payload.get("reason"),
                confidence=_safe_float(payload.get("confidence")),
                model=payload.get("model"),
                mocked=(
                    bool(payload["mocked"]) if "mocked" in payload else None
                ),
            )
    return SanityGate(
        applied=bool(raw.get("applied", False)),
        mode=raw.get("mode"),
        long_kept=list(raw.get("long_kept") or []),
        long_rejected=list(raw.get("long_rejected") or []),
        long_cautioned=list(raw.get("long_cautioned") or []),
        short_kept=list(raw.get("short_kept") or []),
        short_rejected=list(raw.get("short_rejected") or []),
        short_cautioned=list(raw.get("short_cautioned") or []),
        long_outcomes=long_out,
        short_outcomes=short_out,
    )


# ----------------------------- endpoints ------------------------------


@router.get("", response_model=list[ExecutionSummary])
async def list_executions(
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ExecutionSummary]:
    """Compact per-day summary, newest first."""
    out: list[ExecutionSummary] = []
    if not EXEC_DIR.exists():
        return out
    for path in EXEC_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Bad execution log %s: %s", path, e)
            continue
        if not isinstance(payload, dict):
            continue
        try:
            out.append(_build_summary(payload, path))
        except Exception as e:  # noqa: BLE001
            logger.warning("Summary build failed for %s: %s", path, e)
    out.sort(key=lambda r: r.date, reverse=True)
    return out[:limit]


@router.get("/{date_str}", response_model=ExecutionDetail)
async def get_execution(date_str: str) -> ExecutionDetail:
    """Full detail for one execution day. URL accepts the picks_date
    in YYYY-MM-DD form (matches the filename)."""
    parsed = _parse_date(date_str)
    if parsed is None:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    path = EXEC_DIR / f"{parsed.isoformat()}.json"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No execution log for {parsed.isoformat()}",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to read {path.name}: {e}")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="execution log is not a dict")

    summary = _build_summary(payload, path)
    submitted = [
        s for s in (_parse_submitted(r) for r in (payload.get("submitted") or []))
        if s is not None
    ]
    skipped = [
        s for s in (_parse_skipped(r) for r in (payload.get("skipped") or []))
        if s is not None
    ]
    failed = [
        f for f in (_parse_failed(r) for r in (payload.get("failed") or []))
        if f is not None
    ]

    return ExecutionDetail(
        **summary.model_dump(),
        sanity_gate=_parse_sanity_gate(payload.get("sanity_gate")),
        submitted=submitted,
        skipped=skipped,
        failed=failed,
    )
