"""Compatibility shim — src.display.cli_output moved to
src.presentation.cli.cli_output in Stream B slice 5.

Removed in Phase 1 once src/main.py and the execution-layer services
import from src.presentation directly.
"""

import sys as _sys
import warnings as _warnings

from src.presentation.cli import cli_output

_sys.modules["src.display.cli_output"] = cli_output

_warnings.warn(
    "src.display is a Phase-0 compatibility shim; import from "
    "src.presentation.cli instead. Will be removed in Phase 1.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["cli_output"]
