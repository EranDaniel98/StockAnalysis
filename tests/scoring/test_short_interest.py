"""Tests for src.scoring.analyzers.short_interest.

Pure function over history lists — drives entirely with hand-built rows
through the bundled ShortInterestRow dataclass. No DB, no FINRA fetch.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, timedelta

import pytest

from src.scoring.analyzers.short_interest import (
    ShortInterestParams,
    ShortInterestRow,
    analyze,
)


AS_OF = date(2026, 5, 1)


def _row(
    settlement_date: date,
    short_interest_shares: int,
    avg_daily_volume: int | None = 1_000_000,
    days_to_cover: float | None = None,
) -> ShortInterestRow:
    return ShortInterestRow(
        settlement_date=settlement_date,
        short_interest_shares=short_interest_shares,
        avg_daily_volume=avg_daily_volume,
        days_to_cover=days_to_cover,
    )


class TestNoSignal:
    def test_empty_history_returns_none(self) -> None:
        assert analyze([], as_of=AS_OF) is None

    def test_single_row_returns_none(self) -> None:
        rows = [_row(AS_OF - timedelta(days=2), 5_000_000)]
        assert analyze(rows, as_of=AS_OF) is None

    def test_mild_change_returns_none_by_default(self) -> None:
        """A 2% bump over 30d falls inside the deadband — silence is
        preferred over forcing 50 into the composite."""
        rows = [
            _row(AS_OF - timedelta(days=32), 5_000_000),
            _row(AS_OF - timedelta(days=2), 5_100_000),
        ]
        assert analyze(rows, as_of=AS_OF) is None

    def test_zero_baseline_returns_none(self) -> None:
        rows = [
            _row(AS_OF - timedelta(days=32), 0),
            _row(AS_OF - timedelta(days=2), 5_000_000),
        ]
        assert analyze(rows, as_of=AS_OF) is None


class TestBearishSignals:
    def test_heavy_increase_with_high_dtc_scores_bearish(self) -> None:
        """+30% SI in 30d, DTC=7.5 -> deep bearish band."""
        rows = [
            _row(AS_OF - timedelta(days=32), 5_000_000, avg_daily_volume=1_000_000),
            _row(AS_OF - timedelta(days=2), 7_500_000, avg_daily_volume=1_000_000),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        assert result["score"] < 40
        assert result["score"] in range(25, 31)
        assert result["signals"][0]["type"] == "bearish"
        assert result["signals"][0]["source"] == "ShortInterest"
        assert result["days_to_cover"] == pytest.approx(7.5)

    def test_heavy_increase_without_high_dtc(self) -> None:
        """+25% SI but low DTC (1.0) -> still bearish, milder band."""
        rows = [
            _row(AS_OF - timedelta(days=32), 800_000, avg_daily_volume=1_000_000),
            _row(AS_OF - timedelta(days=2), 1_000_000, avg_daily_volume=1_000_000),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        assert 30 <= result["score"] < 40
        assert result["signals"][0]["type"] == "bearish"

    def test_catastrophic_dtc_no_decrease_scores_20(self) -> None:
        """DTC >= 10 sustained, change ~flat -> hard bearish 20."""
        rows = [
            _row(AS_OF - timedelta(days=32), 12_000_000, avg_daily_volume=1_000_000),
            _row(AS_OF - timedelta(days=2), 12_100_000, avg_daily_volume=1_000_000),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        assert result["score"] == 20
        assert result["indicators"]["catastrophic_level"] is True


class TestBullishSignals:
    def test_sharp_drop_after_high_dtc_scores_squeeze(self) -> None:
        """-30% SI in 30d, DTC was ~5.6 -> squeeze setup, score >55."""
        rows = [
            _row(AS_OF - timedelta(days=32), 8_000_000, avg_daily_volume=1_000_000),
            _row(AS_OF - timedelta(days=2), 5_600_000, avg_daily_volume=1_000_000),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        assert result["score"] > 55
        assert result["score"] in range(70, 81)
        assert result["signals"][0]["type"] == "bullish"

    def test_mild_decrease_scores_lean_bullish(self) -> None:
        rows = [
            _row(AS_OF - timedelta(days=32), 5_000_000, avg_daily_volume=1_000_000),
            _row(AS_OF - timedelta(days=2), 4_400_000, avg_daily_volume=1_000_000),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        assert 55 <= result["score"] <= 60
        assert result["signals"][0]["type"] == "bullish"


class TestDaysToCover:
    def test_dtc_derived_from_volume(self) -> None:
        rows = [
            _row(AS_OF - timedelta(days=32), 1_000_000, avg_daily_volume=500_000),
            _row(AS_OF - timedelta(days=2), 4_000_000, avg_daily_volume=500_000),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        assert result["days_to_cover"] == pytest.approx(8.0)

    def test_precomputed_dtc_preferred(self) -> None:
        """When days_to_cover is supplied directly it should be used
        rather than derived from volume."""
        rows = [
            _row(AS_OF - timedelta(days=32), 1_000_000,
                 avg_daily_volume=500_000, days_to_cover=2.5),
            _row(AS_OF - timedelta(days=2), 4_000_000,
                 avg_daily_volume=500_000, days_to_cover=3.0),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        assert result["days_to_cover"] == pytest.approx(3.0)

    def test_zero_volume_does_not_crash(self) -> None:
        """avg_daily_volume == 0 must not raise; analyzer falls back to
        None DTC and still scores off the change."""
        rows = [
            _row(AS_OF - timedelta(days=32), 5_000_000, avg_daily_volume=0),
            _row(AS_OF - timedelta(days=2), 6_500_000, avg_daily_volume=0),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        assert result["days_to_cover"] is None
        assert result["signals"][0]["type"] == "bearish"


class TestAsOfCutoff:
    def test_rows_after_as_of_are_excluded(self) -> None:
        """A row dated after as_of must not leak into the window — both
        the look-ahead-bias guard and the parity contract with the
        composite engine depend on this."""
        rows = [
            _row(AS_OF - timedelta(days=32), 5_000_000, avg_daily_volume=1_000_000),
            _row(AS_OF - timedelta(days=2), 5_100_000, avg_daily_volume=1_000_000),
            _row(AS_OF + timedelta(days=10), 10_000_000, avg_daily_volume=1_000_000),
        ]
        result = analyze(rows, as_of=AS_OF)
        # The future row would have triggered +96% bearish; without it
        # the change is ~2% which lands in the deadband -> None.
        assert result is None

    def test_with_future_row_excluded_history_still_evaluates(self) -> None:
        """Same setup but with a real signal in the eligible history —
        the future row stays excluded; the bearish signal still fires."""
        rows = [
            _row(AS_OF - timedelta(days=32), 5_000_000, avg_daily_volume=1_000_000),
            _row(AS_OF - timedelta(days=2), 7_500_000, avg_daily_volume=1_000_000),
            _row(AS_OF + timedelta(days=10), 1_000_000, avg_daily_volume=1_000_000),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        assert result["signals"][0]["type"] == "bearish"


class TestSharesOutstanding:
    def test_short_interest_pct_from_shares_outstanding(self) -> None:
        rows = [
            _row(AS_OF - timedelta(days=32), 5_000_000, avg_daily_volume=1_000_000),
            _row(AS_OF - timedelta(days=2), 7_500_000, avg_daily_volume=1_000_000),
        ]
        result = analyze(rows, as_of=AS_OF, shares_outstanding=100_000_000)
        assert result is not None
        assert result["short_interest_pct"] == pytest.approx(0.075)

    def test_short_interest_pct_falls_back_to_volume_ratio(self) -> None:
        """No shares_outstanding -> document the fallback uses
        volume-normalized intensity (numerically equal to DTC here)."""
        rows = [
            _row(AS_OF - timedelta(days=32), 5_000_000, avg_daily_volume=1_000_000),
            _row(AS_OF - timedelta(days=2), 7_500_000, avg_daily_volume=1_000_000),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        assert result["short_interest_pct"] == pytest.approx(7.5)


class TestParams:
    def test_frozen_dataclass_cannot_mutate(self) -> None:
        params = ShortInterestParams()
        with pytest.raises(FrozenInstanceError):
            params.window_days = 60  # type: ignore[misc]

    def test_emit_neutral_forces_50_on_deadband(self) -> None:
        """Diagnostic flag: when set, a mild change yields a neutral 50
        instead of None."""
        rows = [
            _row(AS_OF - timedelta(days=32), 5_000_000, avg_daily_volume=1_000_000),
            _row(AS_OF - timedelta(days=2), 5_100_000, avg_daily_volume=1_000_000),
        ]
        result = analyze(
            rows, as_of=AS_OF,
            params=ShortInterestParams(emit_neutral=True),
        )
        assert result is not None
        assert result["score"] == 50

    def test_custom_high_dtc_threshold(self) -> None:
        """Raising high_dtc to 10 demotes a DTC=7.5 case from the deep
        bearish band to the shallower one."""
        rows = [
            _row(AS_OF - timedelta(days=32), 5_000_000, avg_daily_volume=1_000_000),
            _row(AS_OF - timedelta(days=2), 7_500_000, avg_daily_volume=1_000_000),
        ]
        default = analyze(rows, as_of=AS_OF)
        stricter = analyze(
            rows, as_of=AS_OF,
            params=ShortInterestParams(high_dtc=10.0),
        )
        assert default is not None and stricter is not None
        assert stricter["score"] > default["score"]


class TestIndicators:
    def test_indicators_populated(self) -> None:
        rows = [
            _row(AS_OF - timedelta(days=32), 5_000_000, avg_daily_volume=1_000_000),
            _row(AS_OF - timedelta(days=2), 7_500_000, avg_daily_volume=1_000_000),
        ]
        result = analyze(rows, as_of=AS_OF, shares_outstanding=100_000_000)
        assert result is not None
        ind = result["indicators"]
        assert ind["change_30d_pct"] == pytest.approx(0.5)
        assert ind["current_short_interest_shares"] == 7_500_000
        assert ind["baseline_short_interest_shares"] == 5_000_000
        assert ind["baseline_age_days"] == 30
        assert ind["catastrophic_level"] is False
        assert ind["current_settlement_date"] == (
            AS_OF - timedelta(days=2)
        ).isoformat()
