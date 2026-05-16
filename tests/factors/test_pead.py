"""Unit tests for the PEAD factor wrapper.

These tests synthesize their own earnings DataFrames so they run
deterministically without yfinance / DB dependencies.
"""

from __future__ import annotations

import pandas as pd

from src.factors.pead import pead_factor


def _make_earnings(date: str, surprise_pct: float) -> pd.DataFrame:
    """Single-row earnings frame in the yfinance get_earnings_dates shape."""
    return pd.DataFrame(
        {"Surprise(%)": [surprise_pct]},
        index=pd.DatetimeIndex([pd.Timestamp(date)]),
    )


def test_empty_input_returns_empty_frame() -> None:
    out = pead_factor({}, as_of="2026-05-15")
    assert out.empty
    assert list(out.columns) == ["ticker", "raw", "rank", "z_score"]


def test_drops_tickers_without_active_drift_window() -> None:
    # Stale earnings (>60 days ago) → no active window → dropped.
    out = pead_factor(
        {"OLD": _make_earnings("2026-01-01", surprise_pct=20.0)},
        as_of="2026-05-15",
    )
    assert out.empty


def test_ranks_beats_above_misses() -> None:
    histories = {
        "BEAT": _make_earnings("2026-05-01", surprise_pct=18.0),
        "MISS": _make_earnings("2026-05-01", surprise_pct=-15.0),
        "INLINE": _make_earnings("2026-05-01", surprise_pct=0.5),
    }
    out = pead_factor(histories, as_of="2026-05-15")
    assert len(out) == 3
    # rank 1 should be the biggest beat.
    assert out.iloc[0]["ticker"] == "BEAT"
    # The miss should rank last (raw is most negative).
    assert out.iloc[-1]["ticker"] == "MISS"
    # raws strictly ordered.
    raws = out["raw"].tolist()
    assert raws == sorted(raws, reverse=True)


def test_drift_decay_shrinks_signal_at_window_edge() -> None:
    # Same surprise, different days_since: the older one must have a
    # smaller (less positive) raw.
    histories = {
        "FRESH": _make_earnings("2026-05-13", surprise_pct=15.0),  # 2d ago
        "OLD": _make_earnings("2026-03-25", surprise_pct=15.0),    # ~51d ago
    }
    out = pead_factor(histories, as_of="2026-05-15")
    fresh_raw = out.set_index("ticker").loc["FRESH", "raw"]
    old_raw = out.set_index("ticker").loc["OLD", "raw"]
    assert fresh_raw > old_raw, (
        f"fresh ({fresh_raw}) should outrank old ({old_raw}) due to decay"
    )


def test_z_score_is_finite_and_zero_mean_within_floating_tolerance() -> None:
    histories = {
        "A": _make_earnings("2026-05-10", surprise_pct=12.0),
        "B": _make_earnings("2026-05-10", surprise_pct=-8.0),
        "C": _make_earnings("2026-05-10", surprise_pct=3.0),
    }
    out = pead_factor(histories, as_of="2026-05-15")
    assert out["z_score"].notna().all()
    assert abs(out["z_score"].mean()) < 1e-9
