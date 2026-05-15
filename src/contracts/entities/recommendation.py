"""Recommendation entity — the user-facing output of the scoring pipeline."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.contracts.entities.score import CompositeScore
from src.contracts.entities.signal import Signal

ActionLabel = Literal["STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"]
"""From src/scoring/recommender.py:_determine_action."""

ConfidenceLabel = Literal["High", "Medium-High", "Medium", "Low"]
"""From src/scoring/recommender.py:_determine_action."""

OrderType = Literal["Limit", "Stop", "Market"]

StopLossMethod = Literal["atr", "percentage", "support"]
TakeProfitMethod = Literal["risk_reward", "atr", "resistance"]


class StopLossSpec(BaseModel):
    """Typed stop-loss output from src/scoring/recommender.py:_calculate_stop_loss.

    Tier-1 audit #6 (D#17 / T#5 / X#7): the previous shape was a free-form
    dict, and the repository read it via `isinstance(rm.stop_loss, dict)`.
    A future caller passing the model itself instead of a dict bypassed
    the isinstance check, `stop_loss` quietly became `None`, and the
    paper trade shipped with no stop. The typed model + `extract_price`
    helper close that path.

    `method` is the method actually used at exit time. If the configured
    method fell back (e.g. ATR=0 -> percentage, support not found ->
    percentage), `method` must reflect the fallback — not the input
    config (audit X#7 specifically).
    """

    model_config = ConfigDict(frozen=True)

    method: StopLossMethod
    price: float = Field(gt=0)
    pct_from_current: float
    detail: str = ""


class TakeProfitSpec(BaseModel):
    """Typed take-profit output — see StopLossSpec for the rationale."""

    model_config = ConfigDict(frozen=True)

    method: TakeProfitMethod
    price: float = Field(gt=0)
    pct_from_current: float
    detail: str = ""


def extract_stop_loss_price(rm: "RiskManagement | dict | None") -> Optional[float]:
    """Pull the stop-loss price out of a RiskManagement, regardless of
    whether `stop_loss` is a typed spec, a legacy dict, or absent.

    The legacy ``isinstance(rm.stop_loss, dict)`` check returned None on
    a typed spec and shipped a stop-less paper trade. This helper raises
    on truly unrecognized shapes (so a future divergence is loud) and
    returns None only when the spec genuinely is absent.
    """
    if rm is None:
        return None
    sl = getattr(rm, "stop_loss", None) if not isinstance(rm, dict) else rm.get("stop_loss")
    return _extract_price(sl, field="stop_loss")


def extract_take_profit_price(rm: "RiskManagement | dict | None") -> Optional[float]:
    """Pull the take-profit price out of a RiskManagement. Symmetric with
    extract_stop_loss_price."""
    if rm is None:
        return None
    tp = getattr(rm, "take_profit", None) if not isinstance(rm, dict) else rm.get("take_profit")
    return _extract_price(tp, field="take_profit")


def _extract_price(spec: "StopLossSpec | TakeProfitSpec | dict | None", *, field: str) -> Optional[float]:
    if spec is None:
        return None
    if isinstance(spec, (StopLossSpec, TakeProfitSpec)):
        return spec.price
    if isinstance(spec, dict):
        price = spec.get("price")
        return float(price) if price is not None else None
    raise TypeError(
        f"Unrecognized {field} shape: {type(spec).__name__}. Expected "
        f"StopLossSpec/TakeProfitSpec, dict, or None."
    )


def _coerce_to_stop_loss_spec(value: Any) -> Any:
    """model_validator coercer — accept legacy dict OR typed StopLossSpec.
    Empty / missing -> None. Pydantic then validates the spec normally."""
    if value is None or isinstance(value, StopLossSpec):
        return value
    if isinstance(value, dict):
        if not value or "price" not in value:
            return None
        return value  # Pydantic constructs the spec from this dict
    raise TypeError(f"stop_loss must be StopLossSpec, dict, or None; got {type(value).__name__}")


def _coerce_to_take_profit_spec(value: Any) -> Any:
    if value is None or isinstance(value, TakeProfitSpec):
        return value
    if isinstance(value, dict):
        if not value or "price" not in value:
            return None
        return value
    raise TypeError(f"take_profit must be TakeProfitSpec, dict, or None; got {type(value).__name__}")


class RiskManagement(BaseModel):
    """Stop loss + take profit + position sizing + R/R for a single
    recommendation. Mirrors the dict shape from
    src/scoring/recommender.py:_calculate_risk_management."""

    model_config = ConfigDict(frozen=True)

    current_price: float
    stop_loss: StopLossSpec | None = None
    """Typed (Tier-1 #6). Recommender historically built a dict; the
    `_coerce_stop_loss` validator below converts on construction so
    legacy call sites still work."""
    take_profit: TakeProfitSpec | None = None
    position_size: dict = Field(default_factory=dict)
    risk_reward: dict = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _coerce_specs(cls, data: Any) -> Any:
        """Accept legacy dict shape for stop_loss / take_profit so the
        recommender (which still emits dicts) constructs a valid model
        without an explicit conversion step. Once the recommender returns
        typed specs natively, this validator becomes a no-op pass-through."""
        if not isinstance(data, dict):
            return data
        if "stop_loss" in data:
            data["stop_loss"] = _coerce_to_stop_loss_spec(data["stop_loss"])
        if "take_profit" in data:
            data["take_profit"] = _coerce_to_take_profit_spec(data["take_profit"])
        return data


class OrderInstruction(BaseModel):
    """Step-by-step broker instructions for a single recommendation.

    Generated by the recommender for BUY/STRONG BUY actions. Web layer
    will render these as cards; CLI uses src/presentation/cli/panels.
    """

    model_config = ConfigDict(frozen=True)

    order_type: OrderType
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    qty: int = Field(ge=0)
    steps: tuple[str, ...] = ()
    rationale: str = ""


class Recommendation(BaseModel):
    """Full investment recommendation for a single ticker.

    Field-for-field replacement of the dict returned by
    src/scoring/recommender.py:generate_recommendation.
    """

    model_config = ConfigDict(frozen=True)

    ticker: str
    action: ActionLabel
    composite_score: float = Field(ge=0, le=100)
    confidence: ConfidenceLabel
    sub_scores: dict[str, float] = Field(default_factory=dict)
    breakdown: list[dict] = Field(default_factory=list)
    """ScoreBreakdownRow.model_dump() entries. Kept as list[dict] for
    backwards-compat with current display code that iterates the dicts."""

    reasoning: tuple[str, ...] = ()
    bullish_signals: int = 0
    bearish_signals: int = 0
    all_signals: tuple[Signal, ...] = ()
    risk_management: RiskManagement | None = None
    order_instruction: OrderInstruction | None = None
    """Only set for BUY / STRONG BUY actions."""

    # --- denormalized fundamentals fields for display ---
    name: str = ""
    sector: str = "Unknown"
    industry: str = "Unknown"
    market_cap: Optional[float] = None

    # --- engine-level validity (Tier-1 B1 reviewer finding) ---
    # Propagated from CompositeScore so downstream gates (paper-trade,
    # backtest entry) can refuse on a structurally-broken score rather
    # than acting on the 50.0 placeholder composite. Default True keeps
    # callers that construct Recommendation directly working unchanged.
    score_valid: bool = True
    error_count: int = 0
    error_slots: tuple[str, ...] = ()

    def legacy_dict(self) -> dict:
        """Return the legacy untyped-dict shape current call sites expect.
        Shim. Remove in Phase 1.

        risk_management.{stop_loss,take_profit} emit as legacy sub-dicts
        rather than None-when-absent so paper_trade_service's
        ``.get("stop_loss", {}).get("price")`` chain doesn't crash on the
        migration (reviewer I3). The DB repo already uses
        ``extract_stop_loss_price`` which handles both shapes.

        score_valid / error_count / error_slots emit so downstream gates
        on the legacy-dict surface can refuse a broken-pipeline result
        (reviewer B1/I4)."""
        if self.risk_management is None:
            rm_payload: dict = {}
        else:
            rm_payload = self.risk_management.model_dump()
            # Empty-dict fallback preserves the legacy
            # ``.get("stop_loss", {}).get("price")`` chain (reviewer I3).
            if rm_payload.get("stop_loss") is None:
                rm_payload["stop_loss"] = {}
            if rm_payload.get("take_profit") is None:
                rm_payload["take_profit"] = {}
        return {
            "ticker": self.ticker,
            "action": self.action,
            "composite_score": self.composite_score,
            "confidence": self.confidence,
            "sub_scores": dict(self.sub_scores),
            "breakdown": list(self.breakdown),
            "reasoning": list(self.reasoning),
            "bullish_signals": self.bullish_signals,
            "bearish_signals": self.bearish_signals,
            "all_signals": [s.model_dump() for s in self.all_signals],
            "risk_management": rm_payload,
            "name": self.name,
            "sector": self.sector,
            "industry": self.industry,
            "market_cap": self.market_cap,
            "score_valid": self.score_valid,
            "error_count": self.error_count,
            "error_slots": list(self.error_slots),
        }

    @classmethod
    def from_score(
        cls,
        ticker: str,
        score: CompositeScore,
        action: ActionLabel,
        confidence: ConfidenceLabel,
        reasoning: tuple[str, ...] = (),
        risk_management: RiskManagement | None = None,
        order_instruction: OrderInstruction | None = None,
        name: str = "",
        sector: str = "Unknown",
        industry: str = "Unknown",
        market_cap: Optional[float] = None,
    ) -> "Recommendation":
        """Lift a CompositeScore + recommendation-layer outputs into a typed
        Recommendation. Used by ScoringService and Stream B carve."""
        return cls(
            ticker=ticker,
            action=action,
            composite_score=score.composite_score,
            confidence=confidence,
            sub_scores=dict(score.sub_scores),
            breakdown=[b.model_dump() for b in score.breakdown],
            reasoning=reasoning,
            bullish_signals=score.bullish_signals,
            bearish_signals=score.bearish_signals,
            all_signals=score.all_signals,
            risk_management=risk_management,
            order_instruction=order_instruction,
            name=name,
            sector=sector,
            industry=industry,
            market_cap=market_cap,
            score_valid=score.score_valid,
            error_count=score.error_count,
            error_slots=tuple(score.error_slots),
        )
