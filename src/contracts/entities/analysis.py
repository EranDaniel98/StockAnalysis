"""Single-analyzer results."""

from pydantic import BaseModel, ConfigDict, Field

from src.contracts.entities.signal import Signal


class SubAnalysisResult(BaseModel):
    """Output of one analyzer (technical, fundamental, patterns, statistical,
    trend, alpha158, pead).

    Today each analyzer returns a dict shaped roughly:
        {"score": 0-100, "indicators": {...}, "signals": [...], optional extras}

    This entity is the typed replacement. Extras like `breakdown`, `metrics`,
    `patterns`, `support_resistance` live in `extras` (untyped) until Phase 0
    parity is locked; then we type-narrow per analyzer in a follow-up.
    """

    model_config = ConfigDict(frozen=True)

    score: float = Field(ge=0, le=100)
    indicators: dict[str, float] = Field(default_factory=dict)
    signals: tuple[Signal, ...] = ()
    extras: dict = Field(default_factory=dict)
    """Analyzer-specific payload that doesn't fit the typed fields."""

    error: str | None = None
    """Set when the analyzer couldn't run (e.g. insufficient bars).
    Score defaults to 50 in that case."""


class AnalysisBundle(BaseModel):
    """All analyzer outputs for a single ticker, packaged for the composite
    scorer. Mirrors the kwargs of calculate_composite_score().

    alpha158 and pead are optional because they have history-length requirements
    (alpha158 needs 260+ bars; pead needs an earnings_history DataFrame)."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    technical: SubAnalysisResult
    fundamental: SubAnalysisResult
    pattern: SubAnalysisResult
    statistical: SubAnalysisResult
    trend: SubAnalysisResult
    alpha158: SubAnalysisResult | None = None
    pead: SubAnalysisResult | None = None
