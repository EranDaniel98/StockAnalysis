"""Unit tests for the leveraged-ETF + insufficient-history gates."""

from __future__ import annotations

import pandas as pd
import pytest

from src.scoring.instrument_classifier import (
    MIN_HISTORY_DAYS,
    classify_instrument,
    evaluate_history,
)


# --- Leveraged / inverse ETF detection ----------------------------------


@pytest.mark.parametrize("name", [
    "Tradr 2X Long WDC Daily ETF",
    "Tradr 2X Long SNDK Daily ETF",
    "ProShares UltraPro Short QQQ",
    "Direxion Daily Semiconductor Bull 3X Shares",
    "Direxion Daily Semiconductor Bear 3X Shares",
    "ProShares Short S&P 500",
    "Tradr -2X Inverse XYZ",
    # Fractional multipliers — Tradr ships 1.5X / 1.75X products that
    # the original integer-only regex missed.
    "Tradr 1.5X Long NVDA Daily ETF",
    "Tradr 1.75X Long AMZN Daily ETF",
    # MicroSectors family — uses "3X Leveraged" naming without the
    # "Daily" qualifier.
    "MicroSectors FANG+ 3X Leveraged ETN",
    # Bare "Leveraged" / "Levered" tokens — last-resort catch-all for
    # smaller issuers.
    "GraniteShares 2x Long Leveraged TSLA Daily ETF",
])
def test_leveraged_etf_names_are_flagged(name: str) -> None:
    out = classify_instrument("XXX", name)
    assert out.warning == "leveraged_or_inverse_etf", f"missed: {name}"


@pytest.mark.parametrize("name", [
    "Apple Inc.",
    "Broadcom Inc.",
    "JPMorgan Chase & Co.",
    "Sandisk Corporation",
    "Cerebras Systems Inc. Class A Common Stock",
])
def test_regular_stocks_pass_through(name: str) -> None:
    out = classify_instrument(
        "XXX", name,
        fundamentals={"sector": "Technology", "market_cap": 1e10},
    )
    assert out.warning is None


def test_generic_etf_flagged_when_sector_and_mcap_missing() -> None:
    """SPY-like ETFs lack sector + market_cap in yfinance. With the
    name containing 'ETF' / 'Fund' / 'Trust', we flag them as non-
    stock instruments — the composite isn't calibrated for them."""
    out = classify_instrument(
        "SPY", "SPDR S&P 500 ETF Trust",
        fundamentals={"sector": None, "market_cap": None},
    )
    assert out.warning == "non_stock_instrument"


def test_etf_with_market_cap_is_not_flagged_as_generic() -> None:
    """A ticker that returns market_cap is a real equity even if its
    name happens to contain 'Trust' (e.g. business-trust REITs)."""
    out = classify_instrument(
        "XXX", "Some Business Trust REIT",
        fundamentals={"sector": "Real Estate", "market_cap": 5e9},
    )
    assert out.warning is None


def test_empty_name_returns_no_warning() -> None:
    out = classify_instrument("UNKNOWN", "")
    assert out.warning is None
    out = classify_instrument("UNKNOWN", None)
    assert out.warning is None


def test_bull_in_company_name_does_not_false_positive() -> None:
    """'Bull Run Brewing' shouldn't trigger; the leveraged-ETF tells
    require the directional word to co-occur with 'Daily'."""
    out = classify_instrument(
        "BULL", "Bull Run Brewing Co.",
        fundamentals={"sector": "Consumer", "market_cap": 1e8},
    )
    assert out.warning is None


# --- Insufficient-history detection -------------------------------------


def test_evaluate_history_treats_none_as_untested_not_insufficient() -> None:
    """``None`` is the caller saying "I didn't measure" — not evidence
    of insufficient data, so we don't trip the gate."""
    insufficient, bars = evaluate_history(None)
    assert insufficient is False
    assert bars == 0


def test_evaluate_history_flags_empty_frame() -> None:
    """An empty DataFrame IS evidence of insufficient data (we measured
    and got zero bars). Trip the gate."""
    insufficient, bars = evaluate_history(pd.DataFrame())
    assert insufficient is True
    assert bars == 0


def test_evaluate_history_flags_below_threshold() -> None:
    df = pd.DataFrame({"Close": [1.0] * 100})
    insufficient, bars = evaluate_history(df)
    assert insufficient is True
    assert bars == 100


def test_evaluate_history_passes_at_threshold() -> None:
    df = pd.DataFrame({"Close": [1.0] * MIN_HISTORY_DAYS})
    insufficient, bars = evaluate_history(df)
    assert insufficient is False
    assert bars == MIN_HISTORY_DAYS


def test_evaluate_history_passes_above_threshold() -> None:
    df = pd.DataFrame({"Close": [1.0] * (MIN_HISTORY_DAYS + 100)})
    insufficient, bars = evaluate_history(df)
    assert insufficient is False
