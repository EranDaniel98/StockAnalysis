"""Compatibility shim for the pre-Stream-B import location.

The analyzers moved to src/scoring/analyzers/ — this module re-exports them
under the legacy path so existing `from src.analysis import technical`
imports keep working through Phase 0.

We also register each module in sys.modules under the legacy dotted name so
that submodule imports like `from src.analysis.trend_detector import X`
resolve without us needing to leave physical shim files behind for each
analyzer.

Remove in Phase 1 once every caller imports from src.scoring.analyzers.
"""

import sys as _sys
import warnings as _warnings

from src.scoring.analyzers import (  # noqa: F401  (re-exports)
    alpha158,
    fundamental,
    patterns,
    pead,
    statistical,
    technical,
    trend_detector,
)

# Make `from src.analysis.<name> import X` resolve to the real module.
# Without this, Python's import machinery looks for a physical file at
# src/analysis/<name>.py — which we moved — and raises ModuleNotFoundError.
for _name, _mod in (
    ("alpha158", alpha158),
    ("fundamental", fundamental),
    ("patterns", patterns),
    ("pead", pead),
    ("statistical", statistical),
    ("technical", technical),
    ("trend_detector", trend_detector),
):
    _sys.modules[f"src.analysis.{_name}"] = _mod

_warnings.warn(
    "src.analysis is a Phase-0 compatibility shim; import from "
    "src.scoring.analyzers instead. Will be removed in Phase 1.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "alpha158",
    "fundamental",
    "patterns",
    "pead",
    "statistical",
    "technical",
    "trend_detector",
]
