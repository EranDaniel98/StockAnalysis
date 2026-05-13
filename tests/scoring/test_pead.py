"""Tests for the enriched PEAD analyzer.

All synthetic — we hand-build the earnings_history DataFrame in the shape
yfinance's ``get_earnings_dates`` returns (DatetimeIndex with a Surprise(%)
column) and feed it directly. No network, no yfinance round-trip.

The analyzer's public contract is:
  * legacy keys preserved: ``composite_bonus`` (additive bonus the engine
    reads), ``signals``, ``indicators``
  * new diagnostic keys: ``score`` (0-100 band), ``surprise_pct``,
    ``days_since_earnings``, ``drift_window_active``

Both branches need coverage so the engine's bonus path stays byte-stable
while the new score path becomes usable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.scoring.analyzers.pead import (
    _band_score,
    _drift_decay,
    _multi_beat_bonus,
    analyze,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AS_OF = pd.Timestamp("2026-05-10")


def _eh(rows: list[tuple[pd.Timestamp, float]]) -> pd.DataFrame:
    """Build a yfinance-shaped earnings_history DataFrame.

    ``rows`` is a list of ``(announcement_date, surprise_pct)`` tuples,
    most-recent first or last — order doesn't matter, we sort by index.
    """
    idx = pd.DatetimeIndex([r[0] for r in rows])
    surprises = [r[1] for r in rows]
    return pd.DataFrame({"Surprise(%)": surprises}, index=idx).sort_index()


def _price_history(days: int, daily_vol: float, seed: int = 0) -> pd.DataFrame:
    """Synthetic OHLCV-ish frame with controlled daily-return vol."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, daily_vol, size=days)
    closes = 100.0 * np.cumprod(1.0 + rets)
    idx = pd.date_range(end=AS_OF, periods=days, freq="B")
    return pd.DataFrame({"Close": closes}, index=idx)


# ---------------------------------------------------------------------------
# Unit tests for the pure helpers
# ---------------------------------------------------------------------------


class TestBandScore:
    """Lock the surprise -> score band table so the wiring layer can rely
    on stable bucket boundaries when calibrating composite weights."""

    @pytest.mark.parametrize("surprise,expected", [
        (30.0, 85),    # blowout
        (15.0, 75),    # strong beat
        (10.0, 75),    # boundary of strong beat
        (7.0, 65),     # solid beat
        (3.0, 55),     # mild beat
        (0.0, 50),     # in-line
        (-3.0, 40),    # mild miss
        (-7.0, 30),    # solid miss
        (-15.0, 20),   # bad miss
        (-30.0, 15),   # disaster
    ])
    def test_band_lookup(self, surprise: float, expected: int) -> None:
        assert _band_score(surprise) == expected


class TestDriftDecay:
    def test_full_strength_in_first_5_days(self) -> None:
        for d in range(1, 6):
            assert _drift_decay(d, 60) == 1.0

    def test_linear_decay_after_day_5(self) -> None:
        # At day 32 (midpoint of the 5..60 fade), decay ~ 0.5.
        assert _drift_decay(32, 60) == pytest.approx(0.5, abs=0.05)

    def test_zero_outside_window(self) -> None:
        assert _drift_decay(0, 60) == 0.0
        assert _drift_decay(61, 60) == 0.0
        assert _drift_decay(120, 60) == 0.0


class TestMemoryBonus:
    def test_all_beats_fires_positive(self) -> None:
        assert _multi_beat_bonus([5.0, 8.0, 12.0]) > 0

    def test_all_misses_fires_negative(self) -> None:
        assert _multi_beat_bonus([-5.0, -8.0, -12.0]) < 0

    def test_mixed_returns_zero(self) -> None:
        assert _multi_beat_bonus([5.0, -8.0, 12.0]) == 0.0

    def test_too_short_returns_zero(self) -> None:
        assert _multi_beat_bonus([5.0]) == 0.0
        assert _multi_beat_bonus([]) == 0.0


# ---------------------------------------------------------------------------
# Integration tests for analyze()
# ---------------------------------------------------------------------------


class TestAnalyzeStrongBeat:
    def test_strong_beat_yields_high_score_and_bullish_signal(self) -> None:
        # 3 days post-announcement, +12% surprise: full decay weight,
        # +12% lands in the "strong beat" 75 band.
        eh = _eh([(AS_OF - pd.Timedelta(days=3), 12.0)])
        out = analyze("AAPL", eh, as_of_date=AS_OF)
        assert out["score"] > 65
        assert out["drift_window_active"] is True
        assert out["days_since_earnings"] == 3
        assert out["surprise_pct"] == 12.0
        assert any(s["type"] == "bullish" for s in out["signals"])

    def test_strong_beat_emits_composite_bonus(self) -> None:
        """Legacy additive bonus must still fire for backward compat."""
        eh = _eh([(AS_OF - pd.Timedelta(days=3), 12.0)])
        out = analyze("AAPL", eh, as_of_date=AS_OF)
        # +12% / 50 * 10 * full_decay = +2.4 score points before any clip.
        assert out["composite_bonus"] > 1.5
        assert out["composite_bonus"] <= 10.0


class TestAnalyzeStrongMiss:
    def test_strong_miss_yields_low_score_and_bearish_signal(self) -> None:
        eh = _eh([(AS_OF - pd.Timedelta(days=4), -12.0)])
        out = analyze("XYZ", eh, as_of_date=AS_OF)
        assert out["score"] < 35
        assert out["drift_window_active"] is True
        assert out["surprise_pct"] == -12.0
        assert any(s["type"] == "bearish" for s in out["signals"])
        assert out["composite_bonus"] < -1.5


class TestAnalyzeStaleEarnings:
    def test_stale_announcement_kills_drift_window(self) -> None:
        # 90 days back — well outside the 60-day drift window.
        eh = _eh([(AS_OF - pd.Timedelta(days=90), 15.0)])
        out = analyze("AAPL", eh, as_of_date=AS_OF)
        assert out["drift_window_active"] is False
        assert out["score"] == 50
        assert out["composite_bonus"] == 0.0
        # Signals should be empty when the window is closed.
        assert out["signals"] == []


class TestAnalyzeNoData:
    def test_none_returns_neutral(self) -> None:
        out = analyze("AAPL", None, as_of_date=AS_OF)
        assert out["score"] == 50
        assert out["composite_bonus"] == 0.0
        assert out["drift_window_active"] is False
        assert out["surprise_pct"] is None
        assert out["days_since_earnings"] is None

    def test_empty_dataframe_returns_neutral(self) -> None:
        out = analyze("AAPL", pd.DataFrame(), as_of_date=AS_OF)
        assert out["score"] == 50
        assert out["composite_bonus"] == 0.0
        assert out["drift_window_active"] is False


class TestAnalyzeMultiBeatMemory:
    def test_three_prior_beats_adds_memory_bonus(self) -> None:
        """When the prior 3 earnings prints were all beats, the score
        for the current beat should exceed the score for the same beat
        without that history."""
        latest = AS_OF - pd.Timedelta(days=3)
        eh_with_history = _eh([
            (latest, 6.0),
            (latest - pd.Timedelta(days=90), 8.0),
            (latest - pd.Timedelta(days=180), 5.0),
            (latest - pd.Timedelta(days=270), 7.0),
        ])
        eh_solo = _eh([(latest, 6.0)])

        out_history = analyze("AAPL", eh_with_history, as_of_date=AS_OF)
        out_solo = analyze("AAPL", eh_solo, as_of_date=AS_OF)
        assert out_history["score"] > out_solo["score"]
        assert out_history["indicators"]["pead_memory_bonus"] > 0
        assert out_solo["indicators"]["pead_memory_bonus"] == 0

    def test_mixed_history_no_memory_bonus(self) -> None:
        latest = AS_OF - pd.Timedelta(days=3)
        eh = _eh([
            (latest, 6.0),
            (latest - pd.Timedelta(days=90), -8.0),
            (latest - pd.Timedelta(days=180), 5.0),
        ])
        out = analyze("AAPL", eh, as_of_date=AS_OF)
        assert out["indicators"]["pead_memory_bonus"] == 0


class TestAnalyzeVolatilityScaling:
    def test_high_vol_shrinks_score(self) -> None:
        """Same +10% beat on a high-vol name should yield a lower score
        than on a low-vol name (the surprise is less informative when
        the stock routinely moves +/-5% daily)."""
        eh = _eh([(AS_OF - pd.Timedelta(days=3), 10.0)])
        low_vol_prices = _price_history(60, daily_vol=0.01, seed=1)
        high_vol_prices = _price_history(60, daily_vol=0.05, seed=2)

        out_low = analyze("AAPL", eh, as_of_date=AS_OF,
                          price_history=low_vol_prices)
        out_high = analyze("WILD", eh, as_of_date=AS_OF,
                           price_history=high_vol_prices)

        assert out_low["score"] >= out_high["score"]
        assert out_low["indicators"]["pead_daily_vol_pct"] < \
            out_high["indicators"]["pead_daily_vol_pct"]

    def test_no_price_history_keeps_raw_surprise(self) -> None:
        eh = _eh([(AS_OF - pd.Timedelta(days=3), 10.0)])
        out = analyze("AAPL", eh, as_of_date=AS_OF, price_history=None)
        # Without vol scaling, the surprise_pct reported = raw.
        assert out["surprise_pct"] == 10.0
        assert "pead_daily_vol_pct" not in out["indicators"]


class TestBackwardCompat:
    """Engine reads ``composite_bonus`` directly. Pin its presence and
    magnitude for the common in-range case so the bonus path stays
    byte-stable."""

    def test_composite_bonus_key_always_present(self) -> None:
        for eh in [
            None,
            pd.DataFrame(),
            _eh([(AS_OF - pd.Timedelta(days=3), 10.0)]),
            _eh([(AS_OF - pd.Timedelta(days=90), 10.0)]),  # stale
        ]:
            out = analyze("AAPL", eh, as_of_date=AS_OF)
            assert "composite_bonus" in out
            assert isinstance(out["composite_bonus"], float)

    def test_bonus_matches_legacy_formula_for_in_range_surprise(self) -> None:
        """Original formula: (clip(surprise, -50, 50) / 50) * max_bonus * decay.
        For a +10% surprise on day +3 (decay = 1.0) and max_bonus=10:
        (10 / 50) * 10 * 1.0 = +2.0."""
        eh = _eh([(AS_OF - pd.Timedelta(days=3), 10.0)])
        out = analyze("AAPL", eh, as_of_date=AS_OF)
        assert out["composite_bonus"] == pytest.approx(2.0, abs=0.01)

    def test_below_min_surprise_pct_yields_zero_bonus(self) -> None:
        """A +3% beat is below the default 5% threshold for the bonus
        path, even though the score band still shifts a bit above 50."""
        eh = _eh([(AS_OF - pd.Timedelta(days=3), 3.0)])
        out = analyze("AAPL", eh, as_of_date=AS_OF)
        assert out["composite_bonus"] == 0.0
        # Score band reflects the mild beat though.
        assert out["score"] > 50

    def test_signals_list_shape(self) -> None:
        eh = _eh([(AS_OF - pd.Timedelta(days=3), 12.0)])
        out = analyze("AAPL", eh, as_of_date=AS_OF)
        for sig in out["signals"]:
            assert "type" in sig
            assert "source" in sig
            assert sig["source"] == "PEAD"
            assert "detail" in sig
