"""Market regime + macro indicator response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RegimeLabel = Literal["bull", "bear", "chop", "unknown"]
Tilt = Literal["bullish", "bearish", "neutral"]
Lean = Literal["risk_on", "neutral", "risk_off"]


class MarketRegime(BaseModel):
    """Snapshot of the broader-market regime indicators a swing trader cares
    about. Classification is intentionally crude — the user makes the call;
    this just surfaces the inputs."""

    as_of: datetime
    label: RegimeLabel
    spy_price: float | None = None
    spy_sma200: float | None = None
    spy_above_sma200: bool | None = None
    spy_pct_from_sma200: float | None = None
    vix_level: float | None = None
    vix_avg_20d: float | None = None
    notes: list[str] = Field(default_factory=list)


class PrePostMove(BaseModel):
    """Extended-hours move for one ticker on the latest session. premarket is
    vs the prior regular close; afterhours is vs that session's close."""
    ticker: str
    session_date: str
    last_close: float | None = None
    premarket_pct: float | None = None
    afterhours_pct: float | None = None


class OutlookSignal(BaseModel):
    """One transparent input to the market lean. Each contributes +1/0/-1."""
    name: str
    detail: str
    tilt: Tilt


class MarketOutlook(BaseModel):
    """A conditions read, NOT a forecast. Tallies a handful of objective
    signals (trend, VIX, news sentiment, after-hours drift) into a crude
    risk-on / neutral / risk-off lean, and surfaces the pre/post-market moves
    behind it. The caveat is part of the payload so the UI can't drop it."""
    as_of: datetime
    session_date: str
    lean: Lean
    lean_score: int               # sum of signal tilts (+bullish / -bearish)
    n_bullish: int
    n_bearish: int
    signals: list[OutlookSignal]
    prepost: list[PrePostMove]
    news_sentiment: dict[str, int]
    caveat: str
