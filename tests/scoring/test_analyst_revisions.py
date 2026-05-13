"""Tests for src.scoring.analyzers.analyst_revisions.

Pure function over history lists -- drives entirely with hand-built
``RevisionRow`` instances. No live yfinance calls.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, timedelta

import pytest

from src.scoring.analyzers import analyst_revisions
from src.scoring.analyzers.analyst_revisions import (
    AnalystRevisionsParams,
    RevisionRow,
    analyze,
)


AS_OF = date(2026, 5, 13)


def _row(
    days_ago: int,
    *,
    firm: str = "MorganStanley",
    action: str = "upgrade",
    from_grade: str | None = "hold",
    to_grade: str = "buy",
    target_prior: float | None = 100.0,
    target_new: float | None = 110.0,
) -> RevisionRow:
    return RevisionRow(
        revision_date=AS_OF - timedelta(days=days_ago),
        firm=firm,
        action=action,
        from_grade=from_grade,
        to_grade=to_grade,
        target_price_prior=target_prior,
        target_price_new=target_new,
    )


# ---------------------------------------------------------------------------
# Documentation contract
# ---------------------------------------------------------------------------


class TestLiveOnlyDocumented:
    def test_module_docstring_flags_live_only(self) -> None:
        """LIVE-ONLY must be explicit in the module docstring so any
        future engineer wiring the analyzer into the backtest path is
        immediately warned. Womack + Jegadeesh-Kim citations also
        required."""
        doc = analyst_revisions.__doc__ or ""
        upper = doc.upper()
        assert "LIVE-ONLY" in upper
        assert "BACKTEST" in upper
        assert "Womack" in doc
        # Either form of the cite is fine.
        assert "Jegadeesh" in doc


# ---------------------------------------------------------------------------
# No-signal paths
# ---------------------------------------------------------------------------


class TestNoSignal:
    def test_empty_history_returns_none(self) -> None:
        assert analyze([], as_of=AS_OF) is None

    def test_all_rows_outside_window_returns_none(self) -> None:
        """Everything 70+ days old -> outside the default 60d window."""
        rows = [
            _row(days_ago=75, from_grade="hold", to_grade="buy"),
            _row(days_ago=90, from_grade="hold", to_grade="buy"),
            _row(days_ago=120, from_grade="hold", to_grade="buy"),
        ]
        assert analyze(rows, as_of=AS_OF) is None

    def test_stable_revisions_return_none_by_default(self) -> None:
        """1 upgrade + 1 downgrade with ~no target movement -> deadband."""
        rows = [
            _row(days_ago=10, action="upgrade",
                 from_grade="hold", to_grade="buy",
                 target_prior=100.0, target_new=101.0),
            _row(days_ago=20, action="downgrade",
                 from_grade="buy", to_grade="hold",
                 target_prior=100.0, target_new=99.0),
        ]
        # Note: grade_delta_sum cancels (+1 and -1), raw_net=0,
        # target_delta_sum=0%. Solidly inside the deadband.
        assert analyze(rows, as_of=AS_OF) is None


# ---------------------------------------------------------------------------
# Bullish bands
# ---------------------------------------------------------------------------


class TestBullishSignals:
    def test_four_upgrades_plus_target_hike_scores_strong(self) -> None:
        """4 upgrades + summed +8% target delta -> strong bullish band."""
        rows = [
            _row(days_ago=2, firm="MS", action="upgrade",
                 from_grade="hold", to_grade="buy",
                 target_prior=100.0, target_new=102.0),
            _row(days_ago=5, firm="GS", action="upgrade",
                 from_grade="hold", to_grade="buy",
                 target_prior=100.0, target_new=102.0),
            _row(days_ago=15, firm="JPM", action="upgrade",
                 from_grade="hold", to_grade="buy",
                 target_prior=100.0, target_new=102.0),
            _row(days_ago=30, firm="BofA", action="upgrade",
                 from_grade="hold", to_grade="buy",
                 target_prior=100.0, target_new=102.0),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        assert result["score"] > 65
        assert result["score"] in range(75, 86)
        assert result["signals"][0]["type"] == "bullish"
        assert result["signals"][0]["source"] == "AnalystRevisions"
        assert result["net_upgrade_count"] == 4
        assert result["target_price_delta_pct"] == pytest.approx(0.08)

    def test_mild_bullish_single_upgrade(self) -> None:
        """One upgrade with +3% target hike -> mid-60s."""
        rows = [
            _row(days_ago=10, action="upgrade",
                 from_grade="hold", to_grade="buy",
                 target_prior=100.0, target_new=103.0),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        assert 60 <= result["score"] <= 70
        assert result["signals"][0]["type"] == "bullish"


# ---------------------------------------------------------------------------
# Bearish bands
# ---------------------------------------------------------------------------


class TestBearishSignals:
    def test_three_downgrades_minus_ten_target_scores_bearish(self) -> None:
        """3 downgrades + summed -10% target delta -> bearish band <40."""
        rows = [
            _row(days_ago=2, firm="MS", action="downgrade",
                 from_grade="buy", to_grade="hold",
                 target_prior=100.0, target_new=97.0),
            _row(days_ago=10, firm="GS", action="downgrade",
                 from_grade="buy", to_grade="hold",
                 target_prior=100.0, target_new=97.0),
            _row(days_ago=25, firm="JPM", action="downgrade",
                 from_grade="buy", to_grade="hold",
                 target_prior=100.0, target_new=96.0),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        assert result["score"] < 40
        assert result["signals"][0]["type"] == "bearish"
        assert result["net_upgrade_count"] == -3
        assert result["target_price_delta_pct"] == pytest.approx(-0.10)

    def test_severe_capitulation_scores_very_low(self) -> None:
        """3 strongBuy -> hold downgrades + -15% target -> severe band."""
        rows = [
            _row(days_ago=2, firm="MS", action="downgrade",
                 from_grade="strongBuy", to_grade="hold",
                 target_prior=100.0, target_new=95.0),
            _row(days_ago=10, firm="GS", action="downgrade",
                 from_grade="strongBuy", to_grade="hold",
                 target_prior=100.0, target_new=95.0),
            _row(days_ago=20, firm="JPM", action="downgrade",
                 from_grade="strongBuy", to_grade="hold",
                 target_prior=100.0, target_new=95.0),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        assert result["score"] in range(15, 21)
        assert result["signals"][0]["type"] == "bearish"


# ---------------------------------------------------------------------------
# Window cutoff
# ---------------------------------------------------------------------------


class TestWindowCutoff:
    def test_sixty_day_window_excludes_older_rows(self) -> None:
        """Bearish revisions inside the window stay; bullish revisions
        from 90 days ago must NOT pull the score back up."""
        rows = [
            # Out-of-window bullish noise
            _row(days_ago=90, action="upgrade",
                 from_grade="hold", to_grade="strongBuy",
                 target_prior=100.0, target_new=140.0),
            _row(days_ago=120, action="upgrade",
                 from_grade="hold", to_grade="strongBuy",
                 target_prior=100.0, target_new=140.0),
            # In-window bearish signal
            _row(days_ago=5, action="downgrade",
                 from_grade="buy", to_grade="hold",
                 target_prior=100.0, target_new=92.0),
            _row(days_ago=20, action="downgrade",
                 from_grade="buy", to_grade="hold",
                 target_prior=100.0, target_new=92.0),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        assert result["signals"][0]["type"] == "bearish"
        assert result["net_upgrade_count"] == -2

    def test_future_rows_are_excluded(self) -> None:
        """Look-ahead guard: rows dated after as_of must be dropped."""
        rows = [
            RevisionRow(
                revision_date=AS_OF + timedelta(days=5),
                firm="MS", action="upgrade",
                from_grade="hold", to_grade="strongBuy",
                target_price_prior=100.0, target_price_new=200.0,
            ),
        ]
        assert analyze(rows, as_of=AS_OF) is None


# ---------------------------------------------------------------------------
# Grade-delta sensitivity
# ---------------------------------------------------------------------------


class TestGradeDeltaSensitivity:
    def test_strongbuy_to_hold_is_more_bearish_than_buy_to_hold(self) -> None:
        """A two-notch ladder drop should produce a sharper bearish
        signal than a one-notch drop, holding count + target constant.

        Both rows hit the bearish band; the strong-drop version pushes
        net_eff past the severe threshold via grade-delta amplification
        while the mild-drop version lands in the regular bearish band.
        Target deltas are intentionally below the -10% severe cutoff so
        the grade ladder is the only discriminator.
        """
        # Strong drop: strongBuy -> hold across 2 brokers, mild target cut.
        # raw_net=-2, grade_delta_sum=-4 -> net_eff=-6 (severe via grade).
        # target_delta_sum=-6% (bearish but not severe alone).
        strong_drop = [
            _row(days_ago=5, firm="A", action="downgrade",
                 from_grade="strongBuy", to_grade="hold",
                 target_prior=100.0, target_new=97.0),
            _row(days_ago=10, firm="B", action="downgrade",
                 from_grade="strongBuy", to_grade="hold",
                 target_prior=100.0, target_new=97.0),
        ]
        # Mild drop: buy -> hold across 2 brokers, same target cut.
        # raw_net=-2, grade_delta_sum=-2 -> net_eff=-4 (bearish, not severe).
        mild_drop = [
            _row(days_ago=5, firm="A", action="downgrade",
                 from_grade="buy", to_grade="hold",
                 target_prior=100.0, target_new=97.0),
            _row(days_ago=10, firm="B", action="downgrade",
                 from_grade="buy", to_grade="hold",
                 target_prior=100.0, target_new=97.0),
        ]
        strong = analyze(strong_drop, as_of=AS_OF)
        mild = analyze(mild_drop, as_of=AS_OF)
        assert strong is not None and mild is not None
        assert strong["score"] < mild["score"]
        assert strong["indicators"]["grade_delta_sum"] == -4
        assert mild["indicators"]["grade_delta_sum"] == -2


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


class TestRobustness:
    def test_missing_target_prior_is_skipped(self) -> None:
        """Rows with no prior target shouldn't crash and shouldn't
        contribute to the target-delta sum. Direction still counts."""
        rows = [
            _row(days_ago=2, action="upgrade",
                 from_grade="hold", to_grade="buy",
                 target_prior=None, target_new=110.0),
            _row(days_ago=10, action="upgrade",
                 from_grade="hold", to_grade="buy",
                 target_prior=100.0, target_new=108.0),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        # Only the second row contributes to the target delta.
        assert result["target_price_delta_pct"] == pytest.approx(0.08)
        # Both rows count as upgrades.
        assert result["net_upgrade_count"] == 2

    def test_initiation_with_no_from_grade_handled(self) -> None:
        """Initiations have no prior grade -- they should not crash and
        should contribute 0 to net direction (no *change* in view)."""
        rows = [
            RevisionRow(
                revision_date=AS_OF - timedelta(days=5),
                firm="MS",
                action="initiate",
                from_grade=None,
                to_grade="buy",
                target_price_prior=None,
                target_price_new=120.0,
            ),
            RevisionRow(
                revision_date=AS_OF - timedelta(days=10),
                firm="GS",
                action="initiate",
                from_grade=None,
                to_grade="buy",
                target_price_prior=None,
                target_price_new=125.0,
            ),
        ]
        # No prior targets, no direction changes -> deadband -> None.
        assert analyze(rows, as_of=AS_OF) is None

    def test_unknown_grade_strings_dont_crash(self) -> None:
        """An unknown grade ('Speculative Buy') maps to neutral; the
        explicit action field still drives direction."""
        rows = [
            _row(days_ago=5, action="upgrade",
                 from_grade="Speculative Sell", to_grade="Speculative Buy",
                 target_prior=100.0, target_new=110.0),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        assert result["signals"][0]["type"] == "bullish"


# ---------------------------------------------------------------------------
# Params
# ---------------------------------------------------------------------------


class TestParams:
    def test_frozen_dataclass_cannot_mutate(self) -> None:
        params = AnalystRevisionsParams()
        with pytest.raises(FrozenInstanceError):
            params.window_days = 90  # type: ignore[misc]

    def test_row_frozen_dataclass_cannot_mutate(self) -> None:
        row = _row(days_ago=5)
        with pytest.raises(FrozenInstanceError):
            row.firm = "OtherFirm"  # type: ignore[misc]

    def test_emit_neutral_on_stable_forces_50(self) -> None:
        """Diagnostic toggle: a stable deadband should yield 50 instead
        of None when the flag is set."""
        rows = [
            _row(days_ago=10, action="upgrade",
                 from_grade="hold", to_grade="buy",
                 target_prior=100.0, target_new=101.0),
            _row(days_ago=20, action="downgrade",
                 from_grade="buy", to_grade="hold",
                 target_prior=100.0, target_new=99.0),
        ]
        result = analyze(
            rows, as_of=AS_OF,
            params=AnalystRevisionsParams(emit_neutral_on_stable=True),
        )
        assert result is not None
        assert result["score"] == 50

    def test_custom_window_includes_older_row(self) -> None:
        """Widening window_days to 120 should pull in a 90-day-old
        upgrade that the default 60-day analyzer excludes."""
        rows = [
            _row(days_ago=90, action="upgrade",
                 from_grade="hold", to_grade="buy",
                 target_prior=100.0, target_new=110.0),
        ]
        default = analyze(rows, as_of=AS_OF)
        wider = analyze(
            rows, as_of=AS_OF,
            params=AnalystRevisionsParams(window_days=120),
        )
        assert default is None
        assert wider is not None
        assert wider["signals"][0]["type"] == "bullish"


# ---------------------------------------------------------------------------
# Indicators payload
# ---------------------------------------------------------------------------


class TestIndicators:
    def test_indicators_populated(self) -> None:
        rows = [
            _row(days_ago=2, firm="MorganStanley", action="upgrade",
                 from_grade="hold", to_grade="buy",
                 target_prior=100.0, target_new=110.0),
            _row(days_ago=10, firm="GoldmanSachs", action="upgrade",
                 from_grade="hold", to_grade="buy",
                 target_prior=100.0, target_new=108.0),
            _row(days_ago=20, firm="JPMorgan", action="downgrade",
                 from_grade="buy", to_grade="hold",
                 target_prior=100.0, target_new=95.0),
        ]
        result = analyze(rows, as_of=AS_OF)
        assert result is not None
        ind = result["indicators"]
        assert ind["raw_upgrades"] == 2
        assert ind["raw_downgrades"] == 1
        assert ind["revisions_in_window"] == 3
        assert ind["rows_with_target"] == 3
        assert ind["window_days"] == 60
        assert ind["as_of"] == AS_OF.isoformat()
        assert "GoldmanSachs" in ind["firms"]
        assert "MorganStanley" in ind["firms"]
        assert "JPMorgan" in ind["firms"]
