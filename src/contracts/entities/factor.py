"""Factor snapshot + IC diagnostic entities."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FactorSnapshot(BaseModel):
    """One ticker's factor values at a single point in time. Reserved for
    Phase 4 ML feature store; stored as one row per (ticker, as_of, factor_set)
    in the future `factor_snapshots` table (declared empty in 0001_initial)."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    as_of: datetime
    factor_set: str
    """Identifier for the factor family. E.g. 'alpha158_v1', 'qlib_alpha158'."""

    values: dict[str, float] = Field(default_factory=dict)
    """Raw factor values keyed by factor name."""

    z_scores: dict[str, float] = Field(default_factory=dict)
    """z-score of each value vs its trailing-252d history."""


class QuantileSpread(BaseModel):
    """Top-minus-bottom quantile return spread for one forward-return
    horizon."""

    model_config = ConfigDict(frozen=True)

    horizon: str
    """E.g. '1D', '5D', '21D'."""

    spread_pct: float
    """(top_quantile_return - bottom_quantile_return) * 100."""


class ICReport(BaseModel):
    """Output of an alphalens IC diagnostic run.

    Replaces the dict returned by src/diagnostic/alphalens_runner.py:run_alphalens.
    """

    model_config = ConfigDict(frozen=True)

    factor_column: str
    """Which sub-score was tested. E.g. 'composite', 'alpha158'."""

    universe: str
    """Label of the ticker universe used. E.g. 'themes (36)' or 'custom (8)'."""

    window_start: datetime
    window_end: datetime
    quantiles: int
    n_observations: int

    ic_mean: dict[str, float] = Field(default_factory=dict)
    """Per-horizon mean IC. Keys like '1D', '5D'."""

    ic_std: dict[str, float] = Field(default_factory=dict)
    ic_ir: dict[str, float] = Field(default_factory=dict)
    """Information ratio = IC mean / IC std per horizon."""

    quantile_spreads: tuple[QuantileSpread, ...] = ()
    verdict: str = ""
    """Human-readable summary: 'STRONG signal', 'MODEST signal', 'NO signal'."""
