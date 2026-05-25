"""Strategy configuration — typed view over config/strategies.yaml."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrategyWeights(BaseModel):
    """Per-analyzer weights for the composite score. Must sum to ~1.0
    (validator tolerates 0.99-1.01 for human-edited yaml).

    The current yaml uses names like `technical: 0.30`. Optional analyzers
    (alpha158) default to 0 when absent from the yaml.
    """

    model_config = ConfigDict(frozen=True)

    technical: float = Field(ge=0, le=1, default=0.0)
    fundamental: float = Field(ge=0, le=1, default=0.0)
    pattern: float = Field(ge=0, le=1, default=0.0)
    statistical: float = Field(ge=0, le=1, default=0.0)
    trend: float = Field(ge=0, le=1, default=0.0)
    alpha158: float = Field(ge=0, le=1, default=0.0)

    @model_validator(mode="after")
    def _sum_check(self) -> "StrategyWeights":
        total = (
            self.technical
            + self.fundamental
            + self.pattern
            + self.statistical
            + self.trend
            + self.alpha158
        )
        if not 0.99 <= total <= 1.01:
            from src.contracts.errors import ValidationError

            raise ValidationError(
                f"Strategy weights must sum to ~1.0, got {total:.3f}"
            )
        return self


class StrategyThresholds(BaseModel):
    """Per-strategy recommendation thresholds. Override the global
    `scoring.thresholds` block from config/settings.yaml.

    Mirrors src/scoring/recommender.py:_determine_action threshold keys.
    All optional — recommender falls back to global config defaults.
    """

    model_config = ConfigDict(frozen=True)

    strong_buy: Optional[float] = None
    buy: Optional[float] = None
    hold_upper: Optional[float] = None
    hold_lower: Optional[float] = None
    sell: Optional[float] = None


class StrategyConfig(BaseModel):
    """One row from config/strategies.yaml.

    Lossy-tolerant load: unknown keys are accepted (extras dict) so future
    yaml additions don't break parse. Known keys are typed.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    name: str
    description: str = ""
    time_horizon: str = ""
    weights: StrategyWeights
    thresholds: StrategyThresholds = Field(default_factory=StrategyThresholds)
    emphasis: tuple[str, ...] = ()
    min_score: float = Field(ge=0, le=100, default=50)
    min_market_cap: float = 0
    prefer_profitable: bool = False
    use_consensus_scaling: bool = False
    # Strategy-level data filter. When true, the recommender refuses
    # any ticker whose fundamentals report no dividend (yield None or
    # <= 0). Closes the integrity gap where dividend_income could rank
    # a non-dividend stock #1 because the dividend sub-score returned
    # None and its weight redistributed to other categories.
    requires_dividend: bool = False
