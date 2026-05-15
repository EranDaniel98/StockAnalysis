"""Timeout-wrapped yfinance contract.

Covers Tier-1 audit #8 (E#3 + E#4 + E#5 + E#6 + E#28 + X#9). The
`call_with_timeout` helper bounds every yfinance call; the timeout
fires within budget; `FetchOutcome` distinguishes ok / not_found /
timeout / error so callers can refuse to trade on a fetch failure
rather than treating None as 'no upside ahead'.

These tests do not hit yfinance — they exercise the helper with
synthetic sleeping / raising functions.
"""

from __future__ import annotations

import time

from src.data.fetch_outcome import (
    FetchOutcome,
    call_with_timeout,
    call_with_timeout_outcome,
)


# --- call_with_timeout -----------------------------------------------------


def test_call_with_timeout_returns_value_on_success():
    result, err = call_with_timeout(
        lambda: "hello",
        timeout_seconds=1.0,
        name="test.success",
    )
    assert result == "hello"
    assert err is None


def test_call_with_timeout_fires_within_budget():
    """Keystone for audit #8: a hung yfinance call must NOT block the
    caller past the budget. Build a synthetic 'hung' fn and assert the
    wall-clock cost is bounded by the budget, not the fn's sleep."""
    start = time.monotonic()
    result, err = call_with_timeout(
        lambda: time.sleep(2.0) or "never returned",  # noqa: B018
        timeout_seconds=0.1,
        name="test.hung",
    )
    elapsed = time.monotonic() - start

    assert result is None
    assert err is not None and "timed out" in err
    # Wall clock should be near the budget, NOT near 2s. The orphan
    # worker thread is allowed to keep running on the shared pool; the
    # CALLER returns immediately after the timeout fires.
    assert elapsed < 1.0, f"timeout did not fire within budget; elapsed={elapsed:.2f}s"


def test_call_with_timeout_captures_exception():
    def bomb():
        raise RuntimeError("downstream failure")

    result, err = call_with_timeout(
        bomb, timeout_seconds=1.0, name="test.bomb",
    )
    assert result is None
    assert err is not None
    assert "RuntimeError" in err
    assert "downstream failure" in err


# --- FetchOutcome discriminated type ---------------------------------------


def test_fetch_outcome_ok_is_truthy_via_is_ok():
    outcome = FetchOutcome.ok({"price": 100.0})
    assert outcome.is_ok is True
    assert outcome.status == "ok"
    assert outcome.value == {"price": 100.0}


def test_fetch_outcome_not_found_is_not_ok():
    """Critical distinction for the audit: 'not_found' is a successful
    fetch that returned nothing. Caller should treat it differently from
    'error' (transient failure) but it is NOT ok for real-money gating."""
    outcome = FetchOutcome.not_found()
    assert outcome.is_ok is False
    assert outcome.status == "not_found"


def test_fetch_outcome_timeout_is_not_ok_and_carries_msg():
    outcome = FetchOutcome.timeout("yf.history timed out after 30s")
    assert outcome.is_ok is False
    assert outcome.status == "timeout"
    assert "timed out" in outcome.error_msg


def test_fetch_outcome_error_is_not_ok_and_carries_msg():
    outcome = FetchOutcome.error("ConnectionError: refused")
    assert outcome.is_ok is False
    assert outcome.status == "error"
    assert outcome.error_msg == "ConnectionError: refused"


def test_call_with_timeout_outcome_maps_none_to_not_found():
    """A function that legitimately returns None (e.g. 'no fundamentals
    row for this ticker') must come back as ``not_found`` — distinct
    from the timeout / error cases."""
    outcome: FetchOutcome[None] = call_with_timeout_outcome(
        lambda: None, timeout_seconds=1.0, name="test.none",
    )
    assert outcome.status == "not_found"
    assert not outcome.is_ok


def test_call_with_timeout_outcome_maps_timeout_to_timeout_status():
    outcome = call_with_timeout_outcome(
        lambda: time.sleep(2.0) or "never",
        timeout_seconds=0.1,
        name="test.hung",
    )
    assert outcome.status == "timeout"
    assert outcome.error_msg is not None
