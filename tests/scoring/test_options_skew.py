"""Tests for src.scoring.analyzers.options_skew.

Pure analyzer over a hand-built ``OptionsChain``. The synthetic chains
cover the score bands, the live-only sentinel checks (None paths), the
ATM-strike picking semantics, and the optional 25-delta-skew leg.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta
from typing import Optional

import pytest

from src.scoring.analyzers import options_skew as os_mod
from src.scoring.analyzers.options_skew import (
    OptionContract,
    OptionsChain,
    OptionsSkewParams,
    analyze,
)


# ---------------------------------------------------------------------------
# Builders. Keep the synthetic chains tiny so each test reads as a story.
# ---------------------------------------------------------------------------


SNAP = datetime(2024, 6, 3, 15, 30)
DEFAULT_EXPIRY = SNAP.date() + timedelta(days=30)   # ~monthly
NEAR_EXPIRY = SNAP.date() + timedelta(days=7)       # front-week, filtered out


def _contract(
    strike: float,
    contract_type: str,
    iv: float,
    *,
    expiry: date = DEFAULT_EXPIRY,
    volume: int = 100,
    open_interest: int = 500,
    delta: Optional[float] = None,
) -> OptionContract:
    return OptionContract(
        strike=strike,
        expiry=expiry,
        contract_type=contract_type,  # type: ignore[arg-type]
        implied_volatility=iv,
        volume=volume,
        open_interest=open_interest,
        delta=delta,
    )


def _chain(contracts: list[OptionContract], underlying: str = "FOO") -> OptionsChain:
    return OptionsChain(
        underlying=underlying,
        snapshot_time=SNAP,
        contracts=tuple(contracts),
    )


def _symmetric_chain(current_price: float = 100.0) -> OptionsChain:
    """Five strikes either side of spot with matching call & put IV —
    the canonical neutral case."""
    strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
    iv = 0.30
    contracts: list[OptionContract] = []
    for k in strikes:
        contracts.append(_contract(k, "call", iv, volume=200))
        contracts.append(_contract(k, "put", iv, volume=200))
    return _chain(contracts)


# ---------------------------------------------------------------------------
# No-signal / fallthrough.
# ---------------------------------------------------------------------------


class TestNoSignal:
    def test_returns_none_on_none_chain(self) -> None:
        assert analyze(None, current_price=100.0) is None

    def test_returns_none_on_empty_chain(self) -> None:
        empty = _chain([])
        assert analyze(empty, current_price=100.0) is None

    def test_returns_none_on_zero_or_negative_price(self) -> None:
        chain = _symmetric_chain()
        assert analyze(chain, current_price=0.0) is None
        assert analyze(chain, current_price=-5.0) is None

    def test_returns_none_when_no_expiry_at_least_21_days_out(self) -> None:
        """Front-week-only chain has nothing past the 21-day floor."""
        contracts = [
            _contract(100.0, "call", 0.30, expiry=NEAR_EXPIRY),
            _contract(100.0, "put", 0.30, expiry=NEAR_EXPIRY),
        ]
        assert analyze(_chain(contracts), current_price=100.0) is None

    def test_returns_none_when_no_strike_within_10pct_of_price(self) -> None:
        """All strikes are way OTM relative to spot."""
        contracts = [
            _contract(50.0, "call", 0.30),
            _contract(50.0, "put", 0.30),
            _contract(45.0, "call", 0.30),
            _contract(45.0, "put", 0.30),
        ]
        # Spot at 100 → nearest strike (50) is 50% away, outside the 10%
        # default window.
        assert analyze(_chain(contracts), current_price=100.0) is None

    def test_returns_none_when_atm_iv_missing(self) -> None:
        """IV = 0 is yfinance's missing-data sentinel — treated as None."""
        contracts = [
            _contract(100.0, "call", 0.0),
            _contract(100.0, "put", 0.30),
            _contract(95.0, "call", 0.0),
            _contract(95.0, "put", 0.30),
        ]
        assert analyze(_chain(contracts), current_price=100.0) is None

    def test_returns_none_when_one_leg_missing(self) -> None:
        """Calls-only chain — no put leg to compute the ratio."""
        contracts = [
            _contract(100.0, "call", 0.30),
            _contract(95.0, "call", 0.31),
            _contract(105.0, "call", 0.29),
        ]
        assert analyze(_chain(contracts), current_price=100.0) is None


# ---------------------------------------------------------------------------
# Score bands.
# ---------------------------------------------------------------------------


class TestScoreBands:
    def test_symmetric_chain_scores_neutral(self) -> None:
        """Matching call & put IV → score lands in the neutral band
        (50) and signals list is empty."""
        result = analyze(_symmetric_chain(), current_price=100.0)
        assert result is not None
        assert 45 <= result["score"] <= 55
        assert result["signals"] == []
        assert result["put_call_iv_ratio"] == pytest.approx(1.0, abs=0.01)

    def test_reverse_skew_scores_bullish(self) -> None:
        """Calls priced richer than puts + light put volume = bullish."""
        contracts: list[OptionContract] = []
        for k in [90.0, 95.0, 100.0, 105.0, 110.0]:
            contracts.append(_contract(k, "call", 0.40, volume=500))
            contracts.append(_contract(k, "put", 0.30, volume=100))
        result = analyze(_chain(contracts), current_price=100.0)
        assert result is not None
        assert result["score"] > 65
        assert result["put_call_iv_ratio"] < 0.95
        assert any(s["type"] == "bullish" for s in result["signals"])

    def test_heavy_put_skew_scores_bearish(self) -> None:
        """Puts priced ~30% richer than calls — heavy hedging demand."""
        contracts: list[OptionContract] = []
        for k in [90.0, 95.0, 100.0, 105.0, 110.0]:
            contracts.append(_contract(k, "call", 0.30, volume=200))
            contracts.append(_contract(k, "put", 0.40, volume=400))
        result = analyze(_chain(contracts), current_price=100.0)
        assert result is not None
        assert result["score"] < 40
        assert result["put_call_iv_ratio"] >= 1.20
        assert any(s["type"] == "bearish" for s in result["signals"])

    def test_extreme_put_skew_scores_fear_tape(self) -> None:
        """IV ratio >= 1.40 AND volume ratio >= 3.0 → score 15.
        Doubles as the documented contrarian-bullish-but-we-score-it-
        bearish edge case (see module rationale)."""
        contracts: list[OptionContract] = []
        for k in [90.0, 95.0, 100.0, 105.0, 110.0]:
            contracts.append(_contract(k, "call", 0.25, volume=100))
            contracts.append(_contract(k, "put", 0.40, volume=400))
        result = analyze(_chain(contracts), current_price=100.0)
        assert result is not None
        assert result["score"] == 15
        assert result["put_call_iv_ratio"] >= 1.40
        assert result["put_call_volume_ratio"] >= 3.0
        assert any(s["type"] == "bearish" for s in result["signals"])

    def test_mild_put_skew_scores_lean_bearish(self) -> None:
        """IV ratio in the [1.05, 1.20) band — mild hedging."""
        contracts: list[OptionContract] = []
        for k in [90.0, 95.0, 100.0, 105.0, 110.0]:
            contracts.append(_contract(k, "call", 0.30, volume=200))
            contracts.append(_contract(k, "put", 0.33, volume=200))
        result = analyze(_chain(contracts), current_price=100.0)
        assert result is not None
        assert 40 <= result["score"] <= 47
        assert 1.05 <= result["put_call_iv_ratio"] < 1.20


# ---------------------------------------------------------------------------
# ATM strike selection.
# ---------------------------------------------------------------------------


class TestAtmSelection:
    def test_atm_picks_strike_closest_to_price_not_just_geq(self) -> None:
        """Strikes are 95 and 102 with spot at 99 — closest is 95 (4
        away), not 102 (3 away). Actually closest is 102 — verify the
        analyzer picks 102, NOT the lowest strike >= price (which a
        naive implementation might do)."""
        contracts = [
            _contract(95.0, "call", 0.40, volume=100),
            _contract(95.0, "put", 0.40, volume=100),
            _contract(102.0, "call", 0.20, volume=100),
            _contract(102.0, "put", 0.20, volume=100),
        ]
        result = analyze(_chain(contracts), current_price=99.0)
        assert result is not None
        # Closest strike to 99 is 102 (distance 3) not 95 (distance 4),
        # so the ATM read should be 0.20 IV on both legs → ratio ~1.0.
        assert result["indicators"]["atm_call_strike"] == 102.0
        assert result["indicators"]["atm_put_strike"] == 102.0
        assert result["put_call_iv_ratio"] == pytest.approx(1.0)

    def test_atm_picks_lower_strike_when_price_is_below_midpoint(self) -> None:
        """Spot at 96 with strikes [95, 102] → 95 is closer (1 vs 6)."""
        contracts = [
            _contract(95.0, "call", 0.40, volume=100),
            _contract(95.0, "put", 0.40, volume=100),
            _contract(102.0, "call", 0.20, volume=100),
            _contract(102.0, "put", 0.20, volume=100),
        ]
        result = analyze(_chain(contracts), current_price=96.0)
        assert result is not None
        assert result["indicators"]["atm_call_strike"] == 95.0
        assert result["indicators"]["atm_put_strike"] == 95.0


# ---------------------------------------------------------------------------
# Multi-expiry handling.
# ---------------------------------------------------------------------------


class TestMultipleExpiries:
    def test_picks_nearest_expiry_past_21_day_floor(self) -> None:
        """Three expiries: 7d (front), 30d (nearest qualifier), 90d.
        Analyzer should land on 30d and read IV from that slice."""
        near = SNAP.date() + timedelta(days=7)
        monthly = SNAP.date() + timedelta(days=30)
        quarterly = SNAP.date() + timedelta(days=90)

        contracts: list[OptionContract] = []
        # Front-week: heavy put skew that should be IGNORED.
        for k in [95.0, 100.0, 105.0]:
            contracts.append(_contract(k, "call", 0.20, expiry=near, volume=100))
            contracts.append(_contract(k, "put", 0.60, expiry=near, volume=100))
        # Monthly: symmetric, the expiry we expect to score.
        for k in [95.0, 100.0, 105.0]:
            contracts.append(_contract(k, "call", 0.30, expiry=monthly, volume=200))
            contracts.append(_contract(k, "put", 0.30, expiry=monthly, volume=200))
        # Quarterly: another skewed slice that should also be ignored.
        for k in [95.0, 100.0, 105.0]:
            contracts.append(_contract(k, "call", 0.25, expiry=quarterly, volume=50))
            contracts.append(_contract(k, "put", 0.50, expiry=quarterly, volume=50))

        result = analyze(_chain(contracts), current_price=100.0)
        assert result is not None
        assert result["indicators"]["expiry"] == monthly.isoformat()
        assert result["indicators"]["days_to_expiry"] == 30
        assert result["put_call_iv_ratio"] == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# 25-delta skew.
# ---------------------------------------------------------------------------


class TestDeltaSkew:
    def test_25_delta_skew_present_when_deltas_populated(self) -> None:
        """Build a chain with explicit deltas — the analyzer should
        emit a 25_delta_skew field that's positive when puts are
        richer."""
        contracts = [
            # Calls — increasing delta as strike falls (deeper ITM).
            _contract(90.0, "call", 0.45, delta=0.80, volume=100),
            _contract(95.0, "call", 0.38, delta=0.55, volume=100),
            _contract(100.0, "call", 0.33, delta=0.30, volume=100),
            _contract(105.0, "call", 0.30, delta=0.25, volume=100),
            _contract(110.0, "call", 0.28, delta=0.10, volume=100),
            # Puts — negative deltas, more negative as strike falls.
            _contract(90.0, "put", 0.45, delta=-0.15, volume=200),
            _contract(95.0, "put", 0.42, delta=-0.25, volume=200),
            _contract(100.0, "put", 0.40, delta=-0.50, volume=200),
            _contract(105.0, "put", 0.38, delta=-0.75, volume=200),
            _contract(110.0, "put", 0.36, delta=-0.90, volume=200),
        ]
        result = analyze(_chain(contracts), current_price=100.0)
        assert result is not None
        assert "25_delta_skew" in result
        # 25Δ put IV (0.42 at strike 95) - 25Δ call IV (0.25 at strike 105) = +0.13
        assert result["25_delta_skew"] == pytest.approx(0.42 - 0.30, abs=0.05)

    def test_25_delta_skew_absent_when_no_deltas(self) -> None:
        """Default chain has delta=None on every leg — the key should
        not be present in the result."""
        result = analyze(_symmetric_chain(), current_price=100.0)
        assert result is not None
        assert "25_delta_skew" not in result


# ---------------------------------------------------------------------------
# Frozen dataclass + module contract.
# ---------------------------------------------------------------------------


class TestContracts:
    def test_params_is_frozen(self) -> None:
        params = OptionsSkewParams()
        with pytest.raises(dataclasses.FrozenInstanceError):
            params.min_days_to_expiry = 7  # type: ignore[misc]

    def test_option_contract_is_frozen(self) -> None:
        c = _contract(100.0, "call", 0.30)
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.implied_volatility = 0.99  # type: ignore[misc]

    def test_options_chain_is_frozen(self) -> None:
        ch = _symmetric_chain()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ch.underlying = "BAR"  # type: ignore[misc]

    def test_module_docstring_declares_live_only(self) -> None:
        """The module is intentionally NOT wired into the backtest
        engine — the docstring MUST advertise that or future-me will
        re-introduce the look-ahead bug."""
        doc = os_mod.__doc__ or ""
        assert "LIVE-ONLY" in doc
        assert "backtest" in doc.lower()


# ---------------------------------------------------------------------------
# Custom params.
# ---------------------------------------------------------------------------


class TestCustomParams:
    def test_tighter_min_days_to_expiry_filters_more_aggressively(self) -> None:
        """Push the floor to 45 days — a 30-day-only chain no longer
        qualifies."""
        contracts: list[OptionContract] = []
        for k in [95.0, 100.0, 105.0]:
            contracts.append(_contract(k, "call", 0.30, volume=200))
            contracts.append(_contract(k, "put", 0.30, volume=200))
        strict = OptionsSkewParams(min_days_to_expiry=45)
        assert analyze(_chain(contracts), current_price=100.0, params=strict) is None

    def test_wider_strike_window_admits_sparse_chain(self) -> None:
        """A chain with only a strike at 88 against spot=100 (12% away)
        is rejected by the default 10% window but accepted at 20%."""
        contracts = [
            _contract(88.0, "call", 0.30, volume=100),
            _contract(88.0, "put", 0.30, volume=100),
        ]
        default = analyze(_chain(contracts), current_price=100.0)
        assert default is None
        wide = OptionsSkewParams(max_strike_distance_pct=0.20)
        result = analyze(_chain(contracts), current_price=100.0, params=wide)
        assert result is not None
