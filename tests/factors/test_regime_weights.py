"""Regime-conditional weight resolver tests."""

from __future__ import annotations

import pandas as pd
import pytest

from src.factors.composite import combine
from src.factors.regime_weights import (
    PROFILES,
    RegimeWeights,
    list_profiles,
    weights_for,
)


def _vix(values: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    idx = pd.bdate_range(start=start, periods=len(values))
    return pd.DataFrame({"Close": values}, index=idx)


def _frame(rows: list[tuple[str, int]]) -> pd.DataFrame:
    return pd.DataFrame([
        {"ticker": t, "raw": -r, "rank": r, "z_score": -r * 0.1}
        for t, r in rows
    ])


def test_list_profiles_includes_known_names() -> None:
    profiles = list_profiles()
    assert "equal" in profiles
    assert "fundamental_lean" in profiles
    assert "fundamental_only_calm" in profiles
    assert "stress_defensive" in profiles


def test_equal_profile_is_symmetric() -> None:
    p = PROFILES["equal"]
    assert p["low_vix"] == p["high_vix"]
    assert p["low_vix"] == RegimeWeights(momentum=1.0, quality=1.0, value=1.0)


def test_weights_for_unknown_profile_raises() -> None:
    with pytest.raises(ValueError, match="unknown regime-weight profile"):
        weights_for("nope", as_of="2024-01-15")


def test_weights_for_equal_ignores_vix() -> None:
    weights, regime = weights_for("equal", as_of="2024-01-15", vix_df=None)
    assert weights == [1.0, 1.0, 1.0]
    assert regime == "low_vix"


def test_weights_for_fundamental_lean_returns_calm_when_vix_low() -> None:
    # 252+ days of calm VIX (~12), latest is low percentile.
    df = _vix([12.0] * 260)
    weights, regime = weights_for(
        "fundamental_lean", as_of=df.index[-1], vix_df=df, cutoff=0.80,
    )
    # Calm: low_vix weights = [0.6, 1.2, 1.2]
    assert weights == [0.6, 1.2, 1.2]
    assert regime == "low_vix"


def test_weights_for_fundamental_lean_returns_stress_when_vix_high() -> None:
    # 250 calm + 10 spike → latest is in top 20% of trailing 252d.
    values = [12.0] * 250 + [40.0] * 10
    df = _vix(values)
    weights, regime = weights_for(
        "fundamental_lean", as_of=df.index[-1], vix_df=df, cutoff=0.80,
    )
    assert weights == [1.0, 0.6, 0.6]
    assert regime == "high_vix"


def test_weights_for_asymmetric_profile_defaults_calm_without_vix() -> None:
    weights, regime = weights_for(
        "fundamental_lean", as_of="2024-01-15", vix_df=None,
    )
    assert weights == [0.6, 1.2, 1.2]
    assert regime == "low_vix"


def test_combine_with_zero_weight_skips_frame() -> None:
    a = _frame([("A", 1), ("B", 2), ("C", 3)])
    b = _frame([("A", 3), ("B", 2), ("C", 1)])
    # weights [1, 0] should skip frame b entirely; result is just frame a.
    out = combine([a, b], weights=[1.0, 0.0])
    # A is rank 1 in a, so it should win.
    assert out.iloc[0]["ticker"] == "A"
    assert out.iloc[-1]["ticker"] == "C"


def test_combine_with_weights_changes_ordering() -> None:
    """Two frames disagreeing on the winner: weights should shift who wins."""
    a = _frame([("A", 1), ("B", 2), ("C", 3)])  # A best
    b = _frame([("A", 3), ("B", 2), ("C", 1)])  # C best
    # Heavier weight on a → A wins.
    out_a = combine([a, b], weights=[3.0, 1.0])
    assert out_a.iloc[0]["ticker"] == "A"
    # Heavier weight on b → C wins.
    out_b = combine([a, b], weights=[1.0, 3.0])
    assert out_b.iloc[0]["ticker"] == "C"


def test_combine_weights_length_mismatch_raises() -> None:
    a = _frame([("A", 1)])
    b = _frame([("B", 1)])
    with pytest.raises(ValueError, match="weights length"):
        combine([a, b], weights=[1.0])


def test_combine_equal_weights_match_unweighted() -> None:
    a = _frame([("A", 1), ("B", 2), ("C", 3)])
    b = _frame([("A", 3), ("B", 2), ("C", 1)])
    out_w = combine([a, b], weights=[1.0, 1.0]).sort_values("ticker")
    out_u = combine([a, b]).sort_values("ticker")
    pd.testing.assert_series_equal(
        out_w["mean_normalized_rank"].reset_index(drop=True),
        out_u["mean_normalized_rank"].reset_index(drop=True),
        check_names=False,
    )
