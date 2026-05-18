"""Schemas for /api/dashboard/briefing -- the morning-briefing summary.

Surfaces "what must I act on right now?" -- pre-trade drift gate,
factor coverage, and which positions hit stops or targets overnight.
Designed for a single banner card on the dashboard, not a full report.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

GateStatus = Literal["ok", "warn", "fail", "no_picks"]
PositionAlertStatus = Literal[
    "STOP_HIT", "TARGET_HIT", "NEAR_STOP", "NEAR_TARGET"
]


class FactorCoverage(BaseModel):
    """How many of today's picks have a non-null rank for one factor.
    A drop vs the rolling baseline is the canary for an ingest break."""
    factor: str            # "momentum" | "quality" | "value" | "pead"
    covered: int = Field(ge=0)
    total: int = Field(ge=0)
    pct: float = Field(ge=0.0, le=1.0)
    status: Literal["ok", "warn", "fail"]


class DriftCheckOut(BaseModel):
    """One drift-detector check, flattened for the FE."""
    name: str
    status: Literal["ok", "warn", "fail"]
    message: str


class PositionAlert(BaseModel):
    """A held position that hit a stop, target, or is within 2% of either."""
    ticker: str
    status: PositionAlertStatus
    current_price: float
    avg_entry: float
    stop: float
    target: float
    shares: float
    pl_pct: float
    source: Literal["strategy", "fallback_8pct"]


class BriefingResponse(BaseModel):
    picks_date: Optional[date] = Field(
        None,
        description=(
            "Date of the picks file underlying this briefing. Null when no "
            "picks have been generated yet for today."
        ),
    )
    gate_status: GateStatus = Field(
        description=(
            "Overall pre-trade gate verdict. 'fail' means refuse the "
            "rebalance; 'warn' means proceed with caution; 'ok' means "
            "drift checks clean; 'no_picks' means today's picks file is "
            "missing (briefing degrades to position alerts only)."
        ),
    )
    gate_message: str = Field(
        description=(
            "One-line summary of why the gate failed/warned, or 'all drift "
            "checks passed' on OK."
        ),
    )
    recommendation: str = Field(
        description=(
            "Single sentence: what the system thinks the operator should "
            "do this morning."
        ),
    )
    drift_checks: list[DriftCheckOut] = Field(default_factory=list)
    factor_coverage: list[FactorCoverage] = Field(default_factory=list)
    n_picks: int = Field(default=0, ge=0)
    position_alerts: list[PositionAlert] = Field(default_factory=list)
    n_stops_hit: int = Field(default=0, ge=0)
    n_targets_hit: int = Field(default=0, ge=0)
    n_near_stop: int = Field(default=0, ge=0)
    n_positions: int = Field(default=0, ge=0)
    generated_at: datetime
