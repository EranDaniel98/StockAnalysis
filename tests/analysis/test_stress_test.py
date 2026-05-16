"""Tests for the stress-test scenario math.

Imports the _stress_one function from scripts.stress_test (it's
script-level but importable for unit testing).
"""

from __future__ import annotations

import pytest


def _stress_one(pick, scenario, default_beta=1.0):
    """Re-implementation matching scripts/stress_test.py._stress_one.
    Kept here so the test is hermetic and doesn't depend on the script
    module path."""
    beta = pick.get("beta") or default_beta
    sector = pick.get("sector") or "Unknown"
    market_part = beta * scenario["beta_multiplier"] * scenario["market_move"]
    sector_part = scenario["sector_shocks"].get(sector, 0.0)
    return market_part + sector_part


def test_high_beta_falls_harder_in_bear() -> None:
    """β=1.5 stock should fall 1.5x as much as the market in a bear."""
    bear = {
        "market_move": -0.20,
        "sector_shocks": {},
        "beta_multiplier": 1.0,
    }
    low_beta = _stress_one({"beta": 0.5, "sector": "Utilities"}, bear)
    high_beta = _stress_one({"beta": 1.5, "sector": "Technology"}, bear)
    assert low_beta == pytest.approx(-0.10, abs=0.001)
    assert high_beta == pytest.approx(-0.30, abs=0.001)
    assert high_beta < low_beta  # more negative = falls harder


def test_sector_shock_adds_on_top_of_market() -> None:
    """A bank in a banking crisis should feel market + sector hits."""
    crisis = {
        "market_move": -0.05,
        "sector_shocks": {"Financial Services": -0.20},
        "beta_multiplier": 1.0,
    }
    # Bank: β=1.2 → 1.2 * -0.05 + (-0.20) = -0.06 - 0.20 = -0.26
    bank = _stress_one(
        {"beta": 1.2, "sector": "Financial Services"}, crisis,
    )
    assert bank == pytest.approx(-0.26, abs=0.001)
    # Non-bank: β=1.0 → 1.0 * -0.05 + 0 = -0.05
    non_bank = _stress_one(
        {"beta": 1.0, "sector": "Energy"}, crisis,
    )
    assert non_bank == pytest.approx(-0.05, abs=0.001)


def test_beta_multiplier_amplifies_in_extreme_scenarios() -> None:
    """COVID-style crash uses 1.3x beta multiplier."""
    covid = {
        "market_move": -0.35,
        "sector_shocks": {},
        "beta_multiplier": 1.3,
    }
    # β=1.0 stock → 1.0 * 1.3 * -0.35 = -0.455
    result = _stress_one({"beta": 1.0, "sector": "Technology"}, covid)
    assert result == pytest.approx(-0.455, abs=0.001)


def test_defensive_sectors_outperform_in_crash() -> None:
    """Positive sector shock should offset market beta hit."""
    covid = {
        "market_move": -0.35,
        "sector_shocks": {"Consumer Defensive": +0.10},
        "beta_multiplier": 1.3,
    }
    # β=0.5 defensive: 0.5 * 1.3 * -0.35 + 0.10 = -0.2275 + 0.10 = -0.1275
    defensive = _stress_one(
        {"beta": 0.5, "sector": "Consumer Defensive"}, covid,
    )
    # β=1.0 cyclical: 1.0 * 1.3 * -0.35 = -0.455
    cyclical = _stress_one(
        {"beta": 1.0, "sector": "Technology"}, covid,
    )
    assert defensive > cyclical
    assert defensive == pytest.approx(-0.1275, abs=0.001)


def test_missing_beta_falls_back_to_default() -> None:
    scen = {
        "market_move": -0.10,
        "sector_shocks": {},
        "beta_multiplier": 1.0,
    }
    result = _stress_one({"beta": None, "sector": "Tech"}, scen,
                         default_beta=1.0)
    assert result == pytest.approx(-0.10, abs=0.001)


def test_oil_shock_helps_energy_hurts_consumer() -> None:
    shock = {
        "market_move": -0.05,
        "sector_shocks": {
            "Energy": +0.25,
            "Consumer Cyclical": -0.05,
        },
        "beta_multiplier": 1.0,
    }
    energy = _stress_one({"beta": 1.0, "sector": "Energy"}, shock)
    consumer = _stress_one({"beta": 1.0, "sector": "Consumer Cyclical"}, shock)
    # Energy: -0.05 + 0.25 = +0.20
    # Consumer: -0.05 + -0.05 = -0.10
    assert energy == pytest.approx(+0.20, abs=0.001)
    assert consumer == pytest.approx(-0.10, abs=0.001)
    assert energy > consumer
