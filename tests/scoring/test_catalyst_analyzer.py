"""Tests for src.scoring.analyzers.catalyst.

Pure function over a narrative-snapshot-shaped dataclass — no DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pytest

from src.scoring.analyzers.catalyst import (
    CatalystParams,
    _band_points,
    _humanize_anchor,
    analyze,
)


@dataclass
class FakeNarrative:
    """Drop-in for InsiderNarrativeSnapshot — only the fields the
    analyzer reads."""

    ticker: str = "CRM"
    cluster_end_date: date = date(2026, 3, 19)
    has_recent_8k: bool = True
    top_bullish_anchor: Optional[str] = "buyback_authorization"
    top_bearish_anchor: Optional[str] = "litigation_settlement"
    top_bullish_sim: Optional[float] = 0.50
    top_bearish_sim: Optional[float] = 0.20
    narrative_skew: Optional[float] = 0.30
    nearest_filing_form: Optional[str] = "8-K"
    nearest_filing_date: Optional[date] = date(2026, 3, 16)
    days_to_filing: Optional[int] = 3


class TestNoSignal:
    def test_none_narrative_returns_none(self) -> None:
        assert analyze(None, as_of=date(2026, 3, 22)) is None

    def test_stale_cluster_returns_none(self) -> None:
        """A cluster older than max_age_days (default 60) → no signal."""
        narr = FakeNarrative(cluster_end_date=date(2025, 12, 1))
        # as_of is 111 days later
        assert analyze(narr, as_of=date(2026, 3, 22)) is None

    def test_future_cluster_returns_none(self) -> None:
        """as_of < cluster_end_date can happen during backtest replay
        if the upstream loader didn't pre-filter; analyzer should
        ignore it (negative age)."""
        narr = FakeNarrative(cluster_end_date=date(2026, 6, 1))
        assert analyze(narr, as_of=date(2026, 3, 22)) is None

    def test_both_sims_below_threshold_returns_none(self) -> None:
        """The model couldn't classify the catalyst — bullish AND
        bearish anchors both stayed near zero similarity."""
        narr = FakeNarrative(top_bullish_sim=0.10, top_bearish_sim=0.15)
        assert analyze(narr, as_of=date(2026, 3, 22)) is None

    def test_both_sims_none_returns_none(self) -> None:
        narr = FakeNarrative(top_bullish_sim=None, top_bearish_sim=None)
        assert analyze(narr, as_of=date(2026, 3, 22)) is None


class TestScoring:
    @pytest.fixture
    def as_of(self) -> date:
        return date(2026, 3, 22)

    def test_strong_bullish_only_yields_above_neutral(self, as_of: date) -> None:
        """top_bull=0.50 is +20 above the 0.30 floor → +20 score pts.
        Bearish anchor 0.20 is below threshold → 0 pts. Result: 70."""
        narr = FakeNarrative(top_bullish_sim=0.50, top_bearish_sim=0.20)
        result = analyze(narr, as_of=as_of)
        assert result is not None
        assert result["score"] == pytest.approx(70.0, abs=0.5)
        assert any(s["type"] == "bullish" for s in result["signals"])
        assert not any(s["type"] == "bearish" for s in result["signals"])

    def test_strong_bearish_only_yields_below_neutral(self, as_of: date) -> None:
        narr = FakeNarrative(
            top_bullish_sim=0.10,
            top_bearish_sim=0.50,
        )
        result = analyze(narr, as_of=as_of)
        assert result is not None
        assert result["score"] == pytest.approx(30.0, abs=0.5)
        bear_signals = [s for s in result["signals"] if s["type"] == "bearish"]
        assert len(bear_signals) == 1

    def test_both_active_nets_to_signed_skew(self, as_of: date) -> None:
        """Bullish 0.45 (+15) + bearish 0.40 (+10) → 50 + 15 - 10 = 55.
        Both signals emitted."""
        narr = FakeNarrative(top_bullish_sim=0.45, top_bearish_sim=0.40)
        result = analyze(narr, as_of=as_of)
        assert result is not None
        assert result["score"] == pytest.approx(55.0, abs=0.5)
        types = {s["type"] for s in result["signals"]}
        assert types == {"bullish", "bearish"}

    def test_score_capped_at_75_one_side(self, as_of: date) -> None:
        """Each side caps at +25 points; a perfect-1.0 cosine
        contribution shouldn't blow past 75 (or below 25)."""
        narr = FakeNarrative(top_bullish_sim=1.0, top_bearish_sim=0.0)
        result = analyze(narr, as_of=as_of)
        assert result is not None
        assert result["score"] <= 75.5

    def test_signal_detail_includes_anchor_label_and_age(self, as_of: date) -> None:
        narr = FakeNarrative(
            top_bullish_sim=0.55,
            top_bullish_anchor="buyback_authorization",
            cluster_end_date=date(2026, 3, 19),
        )
        result = analyze(narr, as_of=as_of)
        bull = next(s for s in result["signals"] if s["type"] == "bullish")
        # snake_case → space-separated in human text
        assert "buyback authorization" in bull["detail"]
        # age in days from cluster_end_date to as_of
        assert "3d ago" in bull["detail"]
        # cosine similarity number
        assert "0.55" in bull["detail"]


class TestIndicators:
    def test_indicators_carry_raw_snapshot_fields(self) -> None:
        narr = FakeNarrative(
            top_bullish_sim=0.55,
            top_bearish_sim=0.20,
            narrative_skew=0.35,
            days_to_filing=3,
            nearest_filing_form="8-K",
            nearest_filing_date=date(2026, 3, 16),
        )
        result = analyze(narr, as_of=date(2026, 3, 22))
        ind = result["indicators"]
        assert ind["top_bullish_anchor"] == "buyback_authorization"
        assert ind["narrative_skew"] == pytest.approx(0.35)
        assert ind["has_recent_8k"] is True
        assert ind["nearest_filing_form"] == "8-K"
        assert ind["nearest_filing_date"] == "2026-03-16"
        assert ind["days_to_filing"] == 3
        assert ind["cluster_age_days"] == 3


class TestParams:
    def test_min_sim_threshold_raised(self) -> None:
        """Raise the floor to 0.50 — a 0.45 bullish anchor that would
        normally fire now stays silent."""
        narr = FakeNarrative(top_bullish_sim=0.45, top_bearish_sim=0.10)
        assert analyze(narr, as_of=date(2026, 3, 22),
                       params=CatalystParams(min_sim=0.50)) is None

    def test_max_age_can_widen_window(self) -> None:
        """Lengthen the window — a 120-day-old cluster now qualifies."""
        narr = FakeNarrative(cluster_end_date=date(2025, 11, 1),
                             top_bullish_sim=0.50)
        as_of = date(2026, 3, 1)  # 120 days old
        assert analyze(narr, as_of=as_of) is None  # default 60d
        widened = analyze(narr, as_of=as_of,
                          params=CatalystParams(max_age_days=180))
        assert widened is not None


class TestHelpers:
    def test_humanize_anchor(self) -> None:
        assert _humanize_anchor("buyback_authorization") == "buyback authorization"
        assert _humanize_anchor(None) == "unknown"
        assert _humanize_anchor("") == "unknown"

    def test_band_points_below_floor(self) -> None:
        p = CatalystParams()
        assert _band_points(0.0, p) == 0.0
        assert _band_points(0.29, p) == 0.0
        assert _band_points(None, p) == 0.0

    def test_band_points_linear_above_floor(self) -> None:
        p = CatalystParams()
        # 0.40 → excess 0.10 → 10 points
        assert _band_points(0.40, p) == pytest.approx(10.0)
        # 0.50 → excess 0.20 → 20 points
        assert _band_points(0.50, p) == pytest.approx(20.0)

    def test_band_points_capped(self) -> None:
        p = CatalystParams()
        # 0.80 → excess 0.50 → would be 50, capped at 25
        assert _band_points(0.80, p) == pytest.approx(25.0)
        assert _band_points(1.0, p) == pytest.approx(25.0)
