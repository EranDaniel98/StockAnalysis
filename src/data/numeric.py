"""Shared numeric-coercion helper for the data + scoring layers.

yfinance occasionally returns string sentinels for undefined numerics —
``'Infinity'`` when a P/E is undefined because earnings are negative,
``'NaN'`` for missing analyst targets, occasionally empty strings or
``'null'``. Pre-fix, those strings propagated into the scoring layer
where comparisons like ``value > 0`` exploded with TypeError, and
``_score_ticker``'s bare-except silently dropped the ticker.

Two layers use this helper:

* ``src.data.fundamentals.FundamentalsFetcher.fetch`` coerces at the
  boundary so downstream callers get a float-or-None dict.
* ``src.scoring.analyzers.fundamental.analyze`` coerces ON ACCESS as
  belt-and-suspenders: even if the boundary coercion ever regresses,
  the analyzer's comparisons short-circuit cleanly.

Both layers using the same logic keeps "what counts as a missing
numeric" consistent across the codebase.
"""

from __future__ import annotations

from typing import Any


def coerce_numeric(value: Any) -> float | None:
    """Coerce a yfinance value to float or None.

    Returns None for: ``None``, NaN, +/-Inf (numeric or string),
    empty string, ``'null'`` / ``'None'`` strings, and anything that
    isn't a number or numeric-shaped string.

    Returns float for: legitimate numbers and parseable numeric strings.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        if f != f or f in (float("inf"), float("-inf")):  # NaN / +/-Inf
            return None
        return f
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() in {
            "nan", "inf", "infinity", "-inf", "-infinity", "none", "null",
        }:
            return None
        try:
            return coerce_numeric(float(stripped))
        except (TypeError, ValueError):
            return None
    return None
