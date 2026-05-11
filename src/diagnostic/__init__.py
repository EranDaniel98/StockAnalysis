"""Compatibility shim — src.diagnostic.* moved to src.research.* in Stream B.

Mapping:
  src.diagnostic.alphalens_runner  → src.research.diagnostic_service
  src.diagnostic.quantstats_runner → src.research.quantstats_service

Removed in Phase 1 once src/main.py imports from src.research directly.
"""

import sys as _sys
import warnings as _warnings

from src.research import (
    diagnostic_service as alphalens_runner,
    quantstats_service as quantstats_runner,
)

_sys.modules["src.diagnostic.alphalens_runner"] = alphalens_runner
_sys.modules["src.diagnostic.quantstats_runner"] = quantstats_runner

_warnings.warn(
    "src.diagnostic is a Phase-0 compatibility shim; import from "
    "src.research instead. Will be removed in Phase 1.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["alphalens_runner", "quantstats_runner"]
