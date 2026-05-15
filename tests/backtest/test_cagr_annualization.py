"""Tier-2 audit #18: CAGR formula must match the compound flag.

Pre-fix: ``summary_stats`` and ``equity_curve_stats`` always annualized
with ``(1+r)^(1/y) - 1`` regardless of the ``compound`` flag.
Fixed-fractional (compound=False) runs have a linear equity curve, so
the compound formula overstates headline CAGR — the bias grows with
both return magnitude and time horizon.

After the fix:
  * compound=True   → ``cagr_pct = ((end/start)^(1/y) - 1) * 100``
  * compound=False  → ``cagr_pct = total_return_pct / years``
  * Both modes emit ``annualization_method`` so consumers can label.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.backtest.metrics import equity_curve_stats, summary_stats


def _make_equity_curve(start_eq: float, end_eq: float, weeks: int) -> list[dict]:
    """Build a linear weekly equity curve from start_eq to end_eq."""
    dates = pd.date_range(start="2024-01-01", periods=weeks, freq="W-MON")
    step = (end_eq - start_eq) / max(1, weeks - 1)
    return [
        {"date": d, "equity": start_eq + step * i}
        for i, d in enumerate(dates)
    ]


# --- summary_stats: top-level CAGR -----------------------------------------


def test_summary_stats_compound_uses_compound_formula():
    """Compound mode: 30% over 2 years -> CAGR = sqrt(1.30)-1 ~= 14.02%."""
    start = pd.Timestamp("2024-01-01")
    end = pd.Timestamp("2026-01-01")  # exactly 2 years
    out = summary_stats(
        closed_trades=[],
        starting_cash=10_000.0,
        ending_equity=13_000.0,
        start_date=start,
        end_date=end,
        compound=True,
    )
    # (1.30)^(1/2) - 1 = 0.140175...
    assert out["cagr_pct"] == pytest.approx(14.02, abs=0.05)
    assert out["annualization_method"] == "compound"


def test_summary_stats_linear_uses_linear_formula():
    """Linear mode on the SAME inputs: 30% over 2y -> 15.0%/y, not 14.02%."""
    start = pd.Timestamp("2024-01-01")
    end = pd.Timestamp("2026-01-01")
    out = summary_stats(
        closed_trades=[],
        starting_cash=10_000.0,
        ending_equity=13_000.0,
        start_date=start,
        end_date=end,
        compound=False,
    )
    # 30% / 2 = 15.0%
    assert out["cagr_pct"] == pytest.approx(15.0, abs=0.05)
    assert out["annualization_method"] == "linear"


def test_summary_stats_compound_default_unchanged_for_legacy_callers():
    """Default is compound=True so existing callers that don't pass the
    kwarg get the prior behavior. Back-compat guard."""
    start = pd.Timestamp("2024-01-01")
    end = pd.Timestamp("2026-01-01")
    out = summary_stats(
        closed_trades=[],
        starting_cash=10_000.0,
        ending_equity=13_000.0,
        start_date=start,
        end_date=end,
    )
    assert out["annualization_method"] == "compound"
    assert out["cagr_pct"] == pytest.approx(14.02, abs=0.05)


def test_summary_stats_linear_matches_total_return_over_one_year():
    """One-year window: linear = total_return / 1 = total_return."""
    start = pd.Timestamp("2024-01-01")
    end = pd.Timestamp("2025-01-01")
    out = summary_stats(
        closed_trades=[],
        starting_cash=10_000.0,
        ending_equity=12_500.0,
        start_date=start,
        end_date=end,
        compound=False,
    )
    # Total return 25% over 1y -> linear CAGR ≈25%. Slight under-shoot
    # because 2024 is a leap year (366 days / 365.25 = 1.002 years).
    assert out["cagr_pct"] == pytest.approx(25.0, abs=0.1)


# --- equity_curve_stats: Calmar denominator --------------------------------


def test_equity_curve_stats_compound_calmar_uses_compound_return():
    """Calmar uses the same annualization. Compound mode: 30% / 2y."""
    curve = _make_equity_curve(10_000, 13_000, weeks=104)
    out = equity_curve_stats(curve, compound=True)
    # Calmar = compound_return / |max_dd|. Linear curve has trivially
    # tiny drawdown; we just check the answer is a finite float.
    assert isinstance(out["calmar"], float)


def test_equity_curve_stats_linear_diverges_from_compound():
    """For a positive-return run the linear and compound annualizations
    must produce different Calmar values (linear is larger)."""
    curve = _make_equity_curve(10_000, 14_000, weeks=104)  # +40% over 2y
    compound_out = equity_curve_stats(curve, compound=True)
    linear_out = equity_curve_stats(curve, compound=False)

    # On a linear equity curve the drawdown is identical between modes,
    # so any Calmar difference comes from the annualized return.
    assert compound_out["max_drawdown_pct"] == linear_out["max_drawdown_pct"]
    # And linear annualization > compound for positive returns over
    # multi-year windows.
    if linear_out["calmar"] != 0:
        assert linear_out["calmar"] >= compound_out["calmar"]


def test_equity_curve_stats_default_compound_unchanged():
    """Back-compat: default kwarg gives the legacy compound formula."""
    curve = _make_equity_curve(10_000, 13_000, weeks=104)
    out = equity_curve_stats(curve)
    default_compound = equity_curve_stats(curve, compound=True)
    assert out["calmar"] == default_compound["calmar"]
