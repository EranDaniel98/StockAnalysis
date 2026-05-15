"""Per-(date, ticker) score cache for A/B sweep replay.

Backtests spend the bulk of their CPU on the analyzer chain in
``_score_ticker``. When a sweep only varies *which* sub-scores feed the
composite (e.g. insider_flow off / signal_only / weighted), the inputs
to the weighted sum are identical across modes — only the weights and
the source-filter differ.

``ScoreCache`` captures the inputs once. ``recompose_composite``
mirrors the formula in ``src.scoring.engine.calculate_composite_score``
to produce a composite for any (weights, enabled_sources) pair without
re-running the analyzers.

Parity is checked in ``tests/parity/test_score_cache_parity.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


# Every sub-score source that ``calculate_composite_score`` will recognize.
# Sweeps build ``enabled_sources`` by subtracting unwanted sources from
# this set — e.g. ``ALL_SOURCES - {"insider_flow"}`` reproduces the
# pre-cache "off" baseline that ran the analyzer chain without insider data.
ALL_SOURCES: frozenset[str] = frozenset({
    "technical", "fundamental", "pattern", "statistical", "trend",
    "alpha158", "pead", "rel_strength",
    "insider_flow", "catalyst",
    "short_interest", "sector_flows",
    "analyst_revisions", "options_skew",
})


@dataclass(frozen=True)
class CachedScore:
    """Snapshot of one ticker's scoring at one as-of date.

    Stores everything ``recompose_composite`` needs to reproduce the
    composite for any (weights, enabled_sources) variant.
    """
    sub_scores: dict[str, float]
    bullish_by_source: dict[str, int]
    bearish_by_source: dict[str, int]
    pead_bonus: float
    atr: float
    close: float


@dataclass
class ScoreCache:
    """Two-level dict: as_of_date -> ticker -> CachedScore."""
    by_date: dict[pd.Timestamp, dict[str, CachedScore]] = field(default_factory=dict)

    def put(self, as_of: pd.Timestamp, ticker: str, score: CachedScore) -> None:
        self.by_date.setdefault(as_of, {})[ticker] = score

    def for_date(self, as_of: pd.Timestamp) -> dict[str, CachedScore]:
        return self.by_date.get(as_of, {})

    def __len__(self) -> int:
        return sum(len(v) for v in self.by_date.values())


def recompose_composite(
    cached: CachedScore,
    weights: dict[str, float],
    enabled_sources: Optional[set[str]] = None,
    use_consensus_scaling: bool = False,
) -> tuple[float, dict]:
    """Re-derive a composite score from cached sub-scores.

    Mirrors ``src.scoring.engine.calculate_composite_score``:
      1. weighted mean of (filtered) sub-scores
      2. + PEAD bonus (additive, in score points)
      3. (optional) Carver-style consensus scaling on the filtered sub-scores
      4. + signal-consensus adjustment (±5 from bullish/bearish balance)
      5. clamp to [0, 100]

    Args:
        cached: per-ticker per-date snapshot
        weights: strategy weights dict
        enabled_sources: if set, only these sub-score sources contribute
            (both to the weighted sum and to the signal-consensus
            adjustment). None means "all cached sources".
        use_consensus_scaling: if True, applies Carver-style scaling
            against the filtered sub-scores. Matches the
            ``strategy.use_consensus_scaling`` flag.

    Returns:
        ``(composite, consensus_diag)`` where ``consensus_diag`` is the
        diagnostic dict from ``apply_consensus_scaling`` (or empty when
        the flag is off).
    """
    if enabled_sources is None:
        active_subs = dict(cached.sub_scores)
        active_bull_by_src = cached.bullish_by_source
        active_bear_by_src = cached.bearish_by_source
    else:
        active_subs = {
            k: v for k, v in cached.sub_scores.items() if k in enabled_sources
        }
        active_bull_by_src = {
            k: v for k, v in cached.bullish_by_source.items() if k in enabled_sources
        }
        active_bear_by_src = {
            k: v for k, v in cached.bearish_by_source.items() if k in enabled_sources
        }

    # Tier-2 #21: count one bullish/bearish vote per ANALYZER source for
    # the ±5 consensus nudge, not one per indicator. Pre-fix the technical
    # analyzer's 3 moving-average signals counted as 3 bullish votes,
    # drowning out the fundamental analyzer's 1. Now each analyzer
    # contributes at most one bullish + one bearish vote — the nudge
    # reflects cross-analyzer agreement, not indicator count.
    bull_total = sum(1 for v in active_bull_by_src.values() if v > 0)
    bear_total = sum(1 for v in active_bear_by_src.values() if v > 0)

    total_weight = sum(weights.get(k, 0) for k in active_subs)
    if total_weight > 0:
        composite = sum(
            active_subs[k] * weights.get(k, 0) for k in active_subs
        ) / total_weight
    else:
        composite = 50.0

    composite += cached.pead_bonus

    consensus_diag: dict = {}
    if use_consensus_scaling:
        from src.scoring.diversification import apply_consensus_scaling
        composite, consensus_diag = apply_consensus_scaling(composite, active_subs)

    total_signals = bull_total + bear_total
    if total_signals > 0:
        composite += (bull_total - bear_total) / total_signals * 5

    composite = max(0.0, min(100.0, composite))
    return round(float(composite), 2), consensus_diag
