"""Compatibility shim — src.broker.alpaca_client moved to src.execution.alpaca.

Re-exports the module under both `from src.broker import alpaca_client` and
`from src.broker.alpaca_client import AlpacaClient` import forms. The
sys.modules registration mirrors the pattern in src.analysis (Stream B
slice 1).

Remove in Phase 1 once all callers import from src.execution.
"""

import sys as _sys
import warnings as _warnings

from src.execution import alpaca as alpaca_client  # noqa: F401

_sys.modules["src.broker.alpaca_client"] = alpaca_client

_warnings.warn(
    "src.broker is a Phase-0 compatibility shim; import from "
    "src.execution instead. Will be removed in Phase 1.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["alpaca_client"]
