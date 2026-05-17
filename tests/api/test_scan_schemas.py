"""Unit tests for src.api.schemas.scan validators.

Schema-level tests are cheap (no DB, no API) and pin the contract that
both the recommender writer and the FE reader rely on.
"""

from __future__ import annotations

import pytest

from src.api.schemas.scan import ScanResultItem


def _minimal_rec(**overrides) -> dict:
    """Smallest valid ScanResultItem payload. Override individual fields
    in tests that exercise a specific validator."""
    base = {
        "ticker": "AAPL",
        "action": "BUY",
        "composite_score": 72.0,
        "confidence": "Medium-High",
    }
    base.update(overrides)
    return base


# --- earnings_*_ts range validator (catches yfinance ms vs seconds) ---


def test_earnings_ts_in_range_passes_through():
    """A valid unix seconds value (year 2026) is preserved."""
    rec = ScanResultItem.model_validate(
        _minimal_rec(earnings_call_ts=1_777_582_800.0)  # 2026-04-30 UTC
    )
    assert rec.earnings_call_ts == 1_777_582_800.0


def test_earnings_ts_in_milliseconds_is_nullified():
    """yfinance has historically returned milliseconds for this field.
    The range validator nullifies anything outside [2000, 2100] in
    seconds rather than letting it through to render as "Reports in
    19000 days" on the FE."""
    ms_value = 1_777_582_800_000.0  # same instant in ms (× 1000)
    rec = ScanResultItem.model_validate(
        _minimal_rec(earnings_call_ts=ms_value)
    )
    assert rec.earnings_call_ts is None, (
        "ms-instead-of-seconds value must be nullified, not surfaced"
    )


def test_earnings_ts_below_year_2000_is_nullified():
    """Defensive: a stray 0 or small int can't sneak through and render
    as "Reports in -20000 days"."""
    rec = ScanResultItem.model_validate(_minimal_rec(earnings_call_ts=0.0))
    assert rec.earnings_call_ts is None


def test_earnings_ts_none_stays_none():
    rec = ScanResultItem.model_validate(_minimal_rec(earnings_call_ts=None))
    assert rec.earnings_call_ts is None


def test_earnings_ts_non_numeric_string_is_nullified():
    """yfinance sometimes returns the string 'NaN' for missing values
    (it's already coerced to None by _coerce_numeric upstream, but the
    schema validator is the last line of defense)."""
    rec = ScanResultItem.model_validate(_minimal_rec(earnings_call_ts="garbage"))
    assert rec.earnings_call_ts is None


@pytest.mark.parametrize("field", [
    "earnings_announcement_ts",
    "earnings_call_ts",
    "earnings_window_start",
    "earnings_window_end",
])
def test_all_four_earnings_fields_share_the_validator(field: str):
    """All four earnings fields go through the same range check —
    parametrize so a future field rename surfaces here."""
    rec = ScanResultItem.model_validate(_minimal_rec(**{field: 999_999_999_999.0}))
    assert getattr(rec, field) is None
