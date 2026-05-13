"""Adapter + PIT loader tests.

The adapter is pure mapping (snapshot → dict), so tests pin the key names
the analyzer expects. The loader holds the in-memory PIT index and is
exercised through hand-built snapshot lists (no DB).
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.contracts.entities.fundamentals import FundamentalSnapshot
from src.scoring.fundamentals_adapter import snapshot_to_analyzer_dict
from src.scoring.fundamentals_pit_loader import FundamentalsPITLoader


def _snap(
    ticker: str,
    valid_from: datetime,
    valid_to: datetime | None = None,
    source: str = "edgar_10q",
    **kwargs,
) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        ticker=ticker,
        valid_from=valid_from,
        valid_to=valid_to,
        source=source,  # type: ignore[arg-type]
        **kwargs,
    )


# --------------------------- adapter ---------------------------


def test_adapter_none_snapshot_returns_overlay_only():
    out = snapshot_to_analyzer_dict(None, overlay={"sector": "Tech"})
    assert out == {"sector": "Tech"}


def test_adapter_skips_none_fields_so_analyzer_can_fallthrough():
    snap = _snap(
        "X", datetime(2024, 1, 1, tzinfo=timezone.utc),
        roe=0.15, profit_margin=0.10,
    )
    out = snapshot_to_analyzer_dict(snap)
    assert out["roe"] == 0.15
    assert out["profit_margin"] == 0.10
    # debt_to_equity wasn't set on the snap — it must be absent (not None) so
    # the analyzer's `fund.get('debt_to_equity')` returns None and the category
    # skips cleanly.
    assert "debt_to_equity" not in out
    assert "current_ratio" not in out


def test_adapter_renames_gross_margin_to_gross_margins():
    snap = _snap(
        "X", datetime(2024, 1, 1, tzinfo=timezone.utc),
        gross_margin=0.40,
    )
    out = snapshot_to_analyzer_dict(snap)
    # analyzer reads gross_margins (yfinance plural form)
    assert out["gross_margins"] == 0.40
    assert "gross_margin" not in out


def test_adapter_renames_yoy_to_growth_keys():
    snap = _snap(
        "X", datetime(2024, 1, 1, tzinfo=timezone.utc),
        revenue_growth_yoy=0.22,
        earnings_growth_yoy=0.55,
    )
    out = snapshot_to_analyzer_dict(snap)
    assert out["revenue_growth"] == 0.22
    assert out["earnings_growth"] == 0.55


def test_adapter_computes_pe_from_price_and_eps():
    snap = _snap(
        "X", datetime(2024, 1, 1, tzinfo=timezone.utc),
        eps_diluted=2.0,  # quarterly
    )
    # Quarterly EPS, no overlay → TTM approximation = 2 * 4 = 8
    out = snapshot_to_analyzer_dict(snap, price=80.0)
    assert out["pe_trailing"] == 10.0  # 80 / 8


def test_adapter_uses_eps_ttm_overlay_when_supplied():
    snap = _snap(
        "X", datetime(2024, 1, 1, tzinfo=timezone.utc),
        eps_diluted=2.0,
    )
    out = snapshot_to_analyzer_dict(snap, price=80.0, overlay={"eps_ttm": 10.0})
    assert out["pe_trailing"] == 8.0  # 80 / 10
    assert "eps_ttm" not in out  # the internal hint must not leak into analyzer dict


def test_adapter_overlay_wins_on_collision():
    snap = _snap(
        "X", datetime(2024, 1, 1, tzinfo=timezone.utc),
        sector="UnknownEDGAR",
    )
    out = snapshot_to_analyzer_dict(snap, overlay={"sector": "Technology"})
    assert out["sector"] == "Technology"


def test_adapter_skips_pe_when_eps_is_zero_or_missing():
    snap = _snap(
        "X", datetime(2024, 1, 1, tzinfo=timezone.utc),
        eps_diluted=0.0,
    )
    out = snapshot_to_analyzer_dict(snap, price=100.0)
    assert "pe_trailing" not in out


# --------------------------- loader ---------------------------


def test_loader_returns_none_for_uncovered_ticker():
    loader = FundamentalsPITLoader([])
    assert loader.lookup("AAPL", datetime(2024, 1, 1, tzinfo=timezone.utc)) is None


def test_loader_returns_none_when_as_of_predates_earliest():
    snap = _snap("AAPL", datetime(2024, 1, 1, tzinfo=timezone.utc))
    loader = FundamentalsPITLoader([snap])
    # as_of before any filing
    assert loader.lookup("AAPL", datetime(2023, 1, 1, tzinfo=timezone.utc)) is None


def test_loader_picks_row_whose_valid_interval_covers_as_of():
    s1 = _snap(
        "AAPL",
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        valid_to=datetime(2024, 4, 1, tzinfo=timezone.utc),
        revenue=100.0,
    )
    s2 = _snap(
        "AAPL",
        datetime(2024, 4, 1, tzinfo=timezone.utc),
        valid_to=None,
        revenue=120.0,
    )
    loader = FundamentalsPITLoader([s2, s1])  # unordered input — loader sorts
    # Mid-February: s1 still valid
    pick = loader.lookup("AAPL", datetime(2024, 2, 15, tzinfo=timezone.utc))
    assert pick is not None and pick.revenue == 100.0
    # Mid-June: s2 valid
    pick = loader.lookup("AAPL", datetime(2024, 6, 15, tzinfo=timezone.utc))
    assert pick is not None and pick.revenue == 120.0


def test_loader_prefers_higher_source_rank_at_same_as_of():
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    yf = _snap("AAPL", base, source="yfinance_snapshot", revenue=50.0)
    edgar = _snap("AAPL", base, source="edgar_10q", revenue=100.0)
    loader = FundamentalsPITLoader([yf, edgar])
    pick = loader.lookup("AAPL", datetime(2024, 2, 1, tzinfo=timezone.utc))
    assert pick is not None and pick.source == "edgar_10q"
    assert pick.revenue == 100.0


def test_loader_lookup_dict_includes_overlay():
    snap = _snap(
        "AAPL", datetime(2024, 1, 1, tzinfo=timezone.utc),
        roe=0.20,
    )
    loader = FundamentalsPITLoader([snap])
    out = loader.lookup_dict(
        "AAPL",
        datetime(2024, 2, 1, tzinfo=timezone.utc),
        overlay={"sector": "Technology"},
    )
    assert out["roe"] == 0.20
    assert out["sector"] == "Technology"


def test_loader_coverage_reports_per_ticker_row_count():
    s1 = _snap("AAPL", datetime(2024, 1, 1, tzinfo=timezone.utc))
    s2 = _snap("AAPL", datetime(2024, 4, 1, tzinfo=timezone.utc))
    s3 = _snap("MSFT", datetime(2024, 1, 1, tzinfo=timezone.utc))
    loader = FundamentalsPITLoader([s1, s2, s3])
    assert loader.coverage() == {"AAPL": 2, "MSFT": 1}


def test_loader_tz_naive_as_of_compares_safely():
    """A backtest schedule built from pd.date_range is tz-naive; the loader's
    rows are tz-aware. Mixing the two with `<` raises TypeError in stdlib —
    the loader must normalize first."""
    snap = _snap("AAPL", datetime(2024, 1, 1, tzinfo=timezone.utc))
    loader = FundamentalsPITLoader([snap])
    # naive datetime — must not blow up
    pick = loader.lookup("AAPL", datetime(2024, 2, 1))
    assert pick is not None
