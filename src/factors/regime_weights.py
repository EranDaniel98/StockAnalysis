"""Regime-conditional weights for the m+q+v composite.

The 2026-05-18 IC regime report
(``reports/analyzer_ic_regime_vix_2022_2024.md``) showed:

* Fundamental analyzer IC degrades 3.5x in high_vix (+0.058 → +0.017).
* Composite IC sign-flips at every horizon past 5D.
* alpha158 carries WEAK-to-MODEST signal ONLY in high_vix.

Mapping to the factor strategy's m + q + v frames:

* ``quality`` and ``value`` are fundamental-flavored — degrade in stress.
* ``momentum`` (Jegadeesh-Titman 252-21) is technical-flavored —
  long-horizon enough that it's not the same as the daily IC analyzers
  but still vol-sensitive.

Two regime-weight profiles are exposed:

* ``equal`` — today's default; baseline reference.
* ``fundamental_lean`` — heavier quality+value in calm, dampened in
  stress. The IC-driven hypothesis.

The VIX gate failed in backtest because it liquidates wholesale; this
module sits inside the composite and just reshapes the blend, so
existing positions stay invested through the regime transition. The
hypothesis is that signal degrades in stress, NOT that we should exit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import logging
import pandas as pd

from src.factors.vix_regime import (
    DEFAULT_CUTOFF, DEFAULT_WINDOW, is_calm,
)

logger = logging.getLogger(__name__)


RegimeName = Literal["low_vix", "high_vix"]


@dataclass(frozen=True)
class RegimeWeights:
    """Per-factor weights for one regime.

    The composite's ``combine`` function accepts an ``[m, q, v]`` weight
    triplet (in this order). Zero or negative skips that frame entirely.
    """

    momentum: float
    quality: float
    value: float

    def as_list(self) -> list[float]:
        return [self.momentum, self.quality, self.value]


# Profile registry. Adding a new profile here automatically exposes it
# via the CLI flags. Keep names stable across profiles to avoid
# breaking backtest comparisons that key on them.
PROFILES: dict[str, dict[RegimeName, RegimeWeights]] = {
    "equal": {
        "low_vix":  RegimeWeights(momentum=1.0, quality=1.0, value=1.0),
        "high_vix": RegimeWeights(momentum=1.0, quality=1.0, value=1.0),
    },
    "fundamental_lean": {
        # In calm regimes, lean into fundamental cousins (quality+value)
        # since their IC dominates.
        "low_vix":  RegimeWeights(momentum=0.6, quality=1.2, value=1.2),
        # In stress, dampen all weights modestly and slightly raise
        # momentum — since quality/value's IC drops 3x, momentum's
        # relative-contribution rises even if its absolute signal is
        # also vol-sensitive.
        "high_vix": RegimeWeights(momentum=1.0, quality=0.6, value=0.6),
    },
    "fundamental_only_calm": {
        # Aggressive: drop momentum entirely in calm (q+v carry it).
        "low_vix":  RegimeWeights(momentum=0.0, quality=1.0, value=1.0),
        "high_vix": RegimeWeights(momentum=1.0, quality=0.5, value=0.5),
    },
    "stress_defensive": {
        # In stress, halve gross by zeroing two of three factors;
        # composite ranks fewer names → portfolio reflects the cap on
        # signal availability. Pairs with the existing top-decile
        # selector to under-fill rather than force-pick.
        "low_vix":  RegimeWeights(momentum=1.0, quality=1.0, value=1.0),
        "high_vix": RegimeWeights(momentum=0.5, quality=1.0, value=0.0),
    },
}


def list_profiles() -> list[str]:
    return sorted(PROFILES.keys())


def weights_for(
    profile: str,
    *,
    as_of: pd.Timestamp | str,
    vix_df: pd.DataFrame | pd.Series | None = None,
    cutoff: float = DEFAULT_CUTOFF,
    window: int = DEFAULT_WINDOW,
) -> tuple[list[float], RegimeName]:
    """Resolve the [m, q, v] weight triplet for ``profile`` at ``as_of``.

    ``vix_df`` is required when the profile diverges across regimes
    (i.e., is anything other than the symmetric ``equal`` profile).
    When ``vix_df`` is None for a regime-asymmetric profile, the
    function defaults to ``low_vix`` and logs a warning — the same
    permissive default ``vix_regime.is_calm`` uses.

    Returns ``(weights, regime_label)`` so callers can record which
    branch fired for traceability.
    """
    if profile not in PROFILES:
        raise ValueError(
            f"unknown regime-weight profile {profile!r}; available: "
            f"{', '.join(list_profiles())}"
        )
    profile_map = PROFILES[profile]

    # Symmetric profiles ignore VIX entirely.
    if profile_map["low_vix"] == profile_map["high_vix"]:
        return profile_map["low_vix"].as_list(), "low_vix"

    if vix_df is None:
        logger.warning(
            "regime-conditional profile %r requested without vix_df; "
            "defaulting to low_vix weights. Pass a vix frame for the "
            "high_vix branch to fire.", profile,
        )
        return profile_map["low_vix"].as_list(), "low_vix"

    calm = is_calm(vix_df, as_of, window=window, cutoff=cutoff)
    regime: RegimeName = "low_vix" if calm else "high_vix"
    return profile_map[regime].as_list(), regime


__all__ = [
    "RegimeWeights",
    "PROFILES",
    "list_profiles",
    "weights_for",
    "RegimeName",
]
