"""Composite score and consensus diagnostics."""

from pydantic import BaseModel, ConfigDict, Field

from src.contracts.entities.signal import Signal


class ScoreBreakdownRow(BaseModel):
    """One row of the contribution breakdown table shown in CLI/web output.

    Mirrors src/scoring/engine.py:114-117 dict shape:
        {"category", "score", "weight", "contribution", "status"}

    ``score`` is None when the analyzer errored (status="error"); the row
    is still emitted so operators can see WHY a composite looks off
    rather than the slot just silently disappearing.
    """

    model_config = ConfigDict(frozen=True)

    category: str
    score: float | None = Field(default=None, ge=0, le=100)
    weight: str
    """Pre-formatted percentage (e.g. '30%'). Kept as str for display
    backwards-compat. May become float in a future contract revision."""
    contribution: float
    status: str = "ok"
    """One of 'ok', 'error'. 'disabled' slots are omitted from the
    breakdown entirely (the analyzer was never asked to run)."""
    effective_weight: float | None = Field(default=None, ge=0, le=1)
    """Renormalized weight after the error-slot exclusion. None when
    status != 'ok' (errored slots don't contribute). When set, this is
    the row's actual share of the composite — operators reading the
    breakdown for a stress investigation should use this, not the
    nominal ``weight``. Reviewer I6."""


class ConsensusDiagnostic(BaseModel):
    """Output of Carver-style consensus scaling. Empty when
    use_consensus_scaling is False on the strategy."""

    model_config = ConfigDict(frozen=True)

    confidence: float = Field(ge=0, le=1)
    """How much the original composite is trusted. 1.0 = full trust,
    0.4 (floor) = pulled toward neutral 50."""

    sub_score_std: float = Field(ge=0)
    """Standard deviation across sub-scores. Higher = more disagreement."""


class CompositeScore(BaseModel):
    """Final composite score for a ticker, with all the diagnostic context
    the CLI and future web layer need.

    Field-for-field replacement of the dict returned by
    src/scoring/engine.py:calculate_composite_score (lines 119-127), plus
    _atr and _close that backtest engine adds (see src/backtest/engine.py
    _score_ticker tail).
    """

    model_config = ConfigDict(frozen=True)

    ticker: str
    composite_score: float = Field(ge=0, le=100)
    sub_scores: dict[str, float] = Field(default_factory=dict)
    """Sub-score per analyzer category. Keys: 'technical', 'fundamental',
    'pattern', 'statistical', 'trend', optionally 'alpha158'."""

    all_signals: tuple[Signal, ...] = ()
    bullish_signals: int = Field(ge=0, default=0)
    bearish_signals: int = Field(ge=0, default=0)
    breakdown: tuple[ScoreBreakdownRow, ...] = ()
    consensus: ConsensusDiagnostic | None = None

    # --- Analyzer health metadata (Tier-1 #4 silent-50 fix) ---
    analyzer_status: dict[str, str] = Field(default_factory=dict)
    """Slot -> status mapping. Values: 'ok', 'disabled', 'error'.
    Used by downstream gates / dashboards to surface analyzer failures
    instead of treating them as a silent neutral 50."""

    error_count: int = Field(ge=0, default=0)
    error_slots: tuple[str, ...] = ()
    score_valid: bool = True
    """False iff every required analyzer slot errored — composite was
    not mathematically derivable so the value defaults to 50. Callers
    that gate on score should refuse to trade when this is False."""

    # --- Set when score is computed inside backtest context ---
    atr: float | None = None
    close: float | None = None

    def legacy_dict(self) -> dict:
        """Return the legacy untyped-dict shape that current consumers
        (scoring.recommender, backtest.engine, paper.trader) expect.

        Shim. Remove in Phase 1 once the parity test is green and call
        sites have migrated to typed access.
        """
        out: dict = {
            "composite_score": self.composite_score,
            "sub_scores": dict(self.sub_scores),
            "all_signals": [s.model_dump() for s in self.all_signals],
            "bullish_signals": self.bullish_signals,
            "bearish_signals": self.bearish_signals,
            "breakdown": [b.model_dump() for b in self.breakdown],
            "consensus": self.consensus.model_dump() if self.consensus else {},
            "analyzer_status": dict(self.analyzer_status),
            "error_count": self.error_count,
            "error_slots": list(self.error_slots),
            "score_valid": self.score_valid,
        }
        if self.atr is not None:
            out["_atr"] = self.atr
        if self.close is not None:
            out["_close"] = self.close
        return out
