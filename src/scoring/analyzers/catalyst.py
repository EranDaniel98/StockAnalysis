"""Catalyst-narrative analyzer.

Consumes a pre-computed ``InsiderNarrativeSnapshot`` row and produces
the standard analyzer shape (score / signals / indicators).

Pure function over a snapshot dataclass-like object — no DB, no
embedder. The scan service does the bulk Postgres lookup once and
hands the per-ticker snapshot in via ``analyze``.

This is the **explainability twin** of the ML feature pipeline. Day 5's
A/B showed only +0.0053 IC from the narrative features as ML inputs,
so we don't expect the catalyst analyzer to dominate the composite —
its job is to surface a human-readable catalyst label
(``"$25B buyback authorization"``, ``"executive departure"``) alongside
the insider-cluster signal that drove the score, and let the
recommender include that context in the order rationale.

Composite-engine wiring follows the same opt-in convention as
``insider_flow``: returns ``None`` when no recent narrative exists, so
the composite engine skips the sub-score.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Protocol


class _NarrativeLike(Protocol):
    """Structural type covering ``InsiderNarrativeSnapshot`` (the
    SQLAlchemy ORM row). We only read these fields so any duck-typed
    test fake works."""

    ticker: str
    cluster_end_date: date
    has_recent_8k: bool
    top_bullish_anchor: Optional[str]
    top_bearish_anchor: Optional[str]
    top_bullish_sim: Optional[float]
    top_bearish_sim: Optional[float]
    narrative_skew: Optional[float]
    nearest_filing_form: Optional[str]
    nearest_filing_date: Optional[date]
    days_to_filing: Optional[int]


@dataclass(frozen=True)
class CatalystParams:
    """Tunable thresholds. Defaults sit at the conservative end:

    * ``min_sim`` 0.30 — below this, the chunk could be matching any
      stray filing text. Anchors typically score 0.30-0.55 on their
      "natural" filings (see scripts/eyeball_catalyst_anchors), so 0.30
      is the practical floor for "this catalyst actually appears."
    * ``max_age_days`` 60 — same window the ML pipeline uses; cluster
      drift is strongest in the first 60 days.
    * ``per_0p1_sim_points`` 10 — each 0.10 of sim above the floor
      contributes 10 score points (+/-, capped at 25 each side). Total
      addressable score range: 25-75 around the neutral 50.
    """

    min_sim: float = 0.30
    max_age_days: int = 60
    per_0p1_sim_points: float = 10.0
    max_one_side_points: float = 25.0


def _humanize_anchor(key: Optional[str]) -> str:
    """Turn ``"buyback_authorization"`` into ``"buyback authorization"``
    for display in signal detail text."""
    if not key:
        return "unknown"
    return key.replace("_", " ")


def _band_points(sim: Optional[float], params: CatalystParams) -> float:
    """Map a cosine similarity to score points. None or below ``min_sim``
    contributes 0. Linear above the floor, capped at
    ``max_one_side_points``."""
    if sim is None or sim < params.min_sim:
        return 0.0
    excess = sim - params.min_sim
    raw = (excess / 0.1) * params.per_0p1_sim_points
    return min(raw, params.max_one_side_points)


def analyze(
    narrative: Optional[_NarrativeLike],
    *,
    as_of: date,
    params: CatalystParams | None = None,
) -> Optional[dict]:
    """Score a ticker's most recent insider-cluster narrative.

    Returns ``None`` (composite engine skips the sub-score) when:
      * ``narrative`` is ``None`` — no cluster on file for the ticker;
      * the cluster is older than ``max_age_days`` — stale signal;
      * neither bullish nor bearish anchor crosses the ``min_sim``
        floor — the model can't tell what the catalyst is.

    Otherwise returns the standard analyzer shape:
      ``{"score", "signals", "indicators"}``
    """
    params = params or CatalystParams()
    if narrative is None:
        return None

    age_days = (as_of - narrative.cluster_end_date).days
    if age_days < 0 or age_days > params.max_age_days:
        return None

    bull_pts = _band_points(narrative.top_bullish_sim, params)
    bear_pts = _band_points(narrative.top_bearish_sim, params)
    if bull_pts == 0.0 and bear_pts == 0.0:
        return None

    # Net the bullish vs bearish contributions around the neutral 50.
    score = 50.0 + bull_pts - bear_pts
    score = max(0.0, min(100.0, score))

    signals: list[dict] = []
    if bull_pts > 0:
        signals.append({
            "type": "bullish",
            "source": "Catalyst",
            "detail": (
                f"{_humanize_anchor(narrative.top_bullish_anchor)} "
                f"(sim={narrative.top_bullish_sim:.2f}, "
                f"{narrative.nearest_filing_form or 'filing'} "
                f"{age_days}d ago)"
            ),
        })
    if bear_pts > 0:
        signals.append({
            "type": "bearish",
            "source": "Catalyst",
            "detail": (
                f"{_humanize_anchor(narrative.top_bearish_anchor)} "
                f"(sim={narrative.top_bearish_sim:.2f}, "
                f"{narrative.nearest_filing_form or 'filing'} "
                f"{age_days}d ago)"
            ),
        })

    return {
        "score": round(score, 1),
        "signals": signals,
        "indicators": {
            "top_bullish_anchor": narrative.top_bullish_anchor,
            "top_bearish_anchor": narrative.top_bearish_anchor,
            "top_bullish_sim": narrative.top_bullish_sim,
            "top_bearish_sim": narrative.top_bearish_sim,
            "narrative_skew": narrative.narrative_skew,
            "has_recent_8k": bool(narrative.has_recent_8k),
            "nearest_filing_form": narrative.nearest_filing_form,
            "nearest_filing_date": (
                narrative.nearest_filing_date.isoformat()
                if narrative.nearest_filing_date else None
            ),
            "days_to_filing": narrative.days_to_filing,
            "cluster_age_days": age_days,
        },
    }
