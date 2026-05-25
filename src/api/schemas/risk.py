"""Typed risk-management envelope.

Replaces the previous ``dict[str, Any]`` shape on
:class:`src.api.schemas.scan.ScanResultItem.risk_management`. The
Python recommender already produces a fully structured dict — see
``src/scoring/recommender.py:_calculate_risk_management`` — so this
module just gives the structure a name, an OpenAPI surface, and
constraints so the FE can drop its ad-hoc ``isPlainObject`` /
``typeof === "number"`` guards.

The Literal unions are closed sets that match the methods implemented
in the recommender. Adding a new method requires updating BOTH the
recommender branch AND the Literal here — that's intentional, it
makes "we shipped a new method" a typecheck failure on the FE until
the label table is updated.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Stop-loss methods the recommender can emit. ``percentage`` is also
# the fallback any other method downgrades to when its inputs are
# unusable (no ATR data, no support level found), so callers need to
# accept it for every requested method.
StopMethod = Literal["atr", "percentage", "support"]

# Take-profit methods. ``risk_reward`` is the fallback for any other
# method that can't produce a usable price (no resistance ≥ min R/R).
TakeProfitMethod = Literal["risk_reward", "atr", "resistance"]

TimeStopMethod = Literal["calendar"]
PositionSizingMethod = Literal["fixed_fractional"]


class StopLoss(BaseModel):
    """Stop-loss level + provenance. ``method`` is what the recommender
    actually used (fallbacks rewrite it) — read the recommender code
    if you're tempted to assume the requested method always survives.
    """

    model_config = ConfigDict(extra="ignore")

    method: StopMethod
    price: float
    pct_from_current: float
    detail: str
    # Only populated when method='atr'. The recommender writes this on
    # the same branch that builds the detail string so the FE doesn't
    # have to regex-parse the multiplier back out of detail.
    atr_multiplier: Optional[float] = None


class TakeProfit(BaseModel):
    """Take-profit level + provenance.

    Note the asymmetry with StopLoss: when method='resistance' fails
    (no resistance ≥ min R/R), method is rewritten to 'risk_reward',
    matching the StopLoss percentage fallback pattern. The FE should
    branch on the FINAL method, not what was requested.
    """

    model_config = ConfigDict(extra="ignore")

    method: TakeProfitMethod
    price: float
    pct_from_current: float
    detail: str
    atr_multiplier: Optional[float] = None


class TimeStop(BaseModel):
    """Triple-barrier time stop — forced exit N calendar days after entry."""

    model_config = ConfigDict(extra="ignore")

    method: TimeStopMethod
    days: int = Field(gt=0)
    exit_date: str  # ISO date, kept as string to round-trip JSONB cleanly
    detail: str


class PositionSizing(BaseModel):
    """Per-trade position sizing output."""

    model_config = ConfigDict(extra="ignore")

    method: PositionSizingMethod
    portfolio_value: float
    recommended_shares: int = Field(ge=0)
    dollar_amount: float = Field(ge=0)
    pct_of_portfolio: float = Field(ge=0)
    # Realized risk after rounding shares to an integer. Optional because
    # SELL / STRONG SELL / HOLD recommendations short-circuit the sizing
    # math at zero shares and skip these.
    risk_per_trade: Optional[float] = None
    risk_pct: Optional[float] = None
    risk_budget_pct: Optional[float] = None


class RiskManagement(BaseModel):
    """Full risk envelope. All children are Optional so a recommendation
    can omit individual blocks (e.g. ``risk_management={}`` when the
    refusal gates fired) without violating the schema.
    """

    model_config = ConfigDict(extra="ignore")

    current_price: Optional[float] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[StopLoss] = None
    take_profit: Optional[TakeProfit] = None
    time_stop: Optional[TimeStop] = None
    position: Optional[PositionSizing] = None
    risk_reward_ratio: Optional[float] = Field(default=None, ge=0)
