"""Pre-trade sanity-check envelope.

Attached to BuySignal rows on /api/scans/latest-buys when the
sanity-check pass has run. The recommender doesn't know about this —
the check fires after the composite already produced a BUY, as a final
"does this make sense given recent news / filings?" gate.

See ``src/research_agent/sanity_check.py`` for the LLM-backed checker
and ``src/research_agent/sanity_mock.py`` for the no-API-key mock
that lets us ship the wiring before the live key lands.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Three-level verdict. The asymmetric REJECT bias is intentional:
# the sanity check can downgrade BUYs but never upgrade them. We
# never trust an LLM to invent confidence.
SanityVerdict = Literal["OK", "CAUTION", "REJECT"]


class SanityCheck(BaseModel):
    """One pre-trade sanity-check result. Renders as a badge on the
    /buy-signals row.

    A REJECT means the LLM identified an obvious one-off catalyst that
    explains the recent move and the BUY is likely to mean-revert. The
    FE's "Hide rejected" filter operates on this field.

    ``model_used`` and ``mocked`` exist so we can audit which checks
    came from a real LLM call vs the placeholder mock. Real-money
    constraint: every check that fed a decision must be auditable.
    """

    model_config = ConfigDict(extra="ignore")

    verdict: SanityVerdict
    reason: str
    catalysts_found: list[str] = Field(default_factory=list)
    # 0.0 = the checker has no confidence in its verdict (e.g. couldn't
    # find relevant filings); 1.0 = high confidence.
    confidence: float = Field(ge=0.0, le=1.0)

    # Provenance / audit fields.
    model_used: str = "mock"
    mocked: bool = False
    # ISO timestamp of when the check ran. Useful when a cached check
    # is shown next to a fresh scan — the operator should see staleness.
    checked_at: Optional[str] = None
