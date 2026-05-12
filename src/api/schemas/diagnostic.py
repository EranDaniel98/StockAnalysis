"""Diagnostics (alphalens IC) request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

UniverseKind = Literal["watchlist", "portfolio", "themes", "tickers"]
FactorChoice = Literal[
    "composite", "technical", "fundamental", "pattern", "statistical", "trend", "alpha158"
]


class DiagnosticRequest(BaseModel):
    strategy: str = Field(default="swing_trading")
    universe: UniverseKind = Field(default="themes")
    tickers: list[str] | None = None
    years: float = Field(default=2.0, gt=0, le=10)
    factor: FactorChoice = Field(default="composite")
    quantiles: int = Field(default=5, ge=2, le=10)
    periods: list[int] = Field(
        default_factory=lambda: [1, 5, 21],
        description="Forward-return horizons in trading days.",
    )
    accept_lookahead: bool = Field(default=False)
    fresh: bool = Field(default=False)


class DiagnosticResponse(BaseModel):
    id: int
    factor: str
    universe_label: str
    window_start: datetime
    window_end: datetime
    created_at: datetime
    quantiles: int
    n_observations: int
    ic_mean: dict[str, float]
    ic_std: dict[str, float]
    ic_ir: dict[str, float]
    top_minus_bottom_pct: dict[str, float]
    verdict: str = ""


class DiagnosticSummary(BaseModel):
    id: int
    factor: str
    universe_label: str
    window_start: datetime
    window_end: datetime
    created_at: datetime
    n_observations: int
    verdict: str = ""
