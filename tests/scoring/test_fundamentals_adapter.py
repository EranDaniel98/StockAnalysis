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


def test_adapter_skips_pe_when_no_eps_ttm():
    """Without a real TTM EPS from the loader the adapter must NOT compute
    pe_trailing from latest-quarter × 4 — that heuristic systematically
    miscounts for any non-steady-state company."""
    snap = _snap(
        "X", datetime(2024, 1, 1, tzinfo=timezone.utc),
        eps_diluted=2.0,  # quarterly only — no TTM yet
    )
    out = snapshot_to_analyzer_dict(snap, price=80.0)
    assert "pe_trailing" not in out


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


# --------------------------- loader TTM EPS ---------------------------


def _quarterly(ticker: str, dt: datetime, eps: float | None) -> FundamentalSnapshot:
    return _snap(ticker, dt, source="edgar_10q", eps_diluted=eps)


def test_compute_eps_ttm_sums_last_four_quarters():
    """Strict TTM = sum of 4 most-recent quarterly EPS values strictly ≤ as_of."""
    rows = [
        _quarterly("AAPL", datetime(2023, 5, 1, tzinfo=timezone.utc), 1.00),
        _quarterly("AAPL", datetime(2023, 8, 1, tzinfo=timezone.utc), 1.20),
        _quarterly("AAPL", datetime(2023, 11, 1, tzinfo=timezone.utc), 1.30),
        _quarterly("AAPL", datetime(2024, 2, 1, tzinfo=timezone.utc), 1.50),
        _quarterly("AAPL", datetime(2024, 5, 1, tzinfo=timezone.utc), 1.70),  # excluded
    ]
    loader = FundamentalsPITLoader(rows)
    # as_of after Q4 filing but before Q5: TTM = 1.20 + 1.30 + 1.50 + 1.00 = 5.00
    # (4 most recent ≤ as_of: 2023-05, 2023-08, 2023-11, 2024-02)
    ttm = loader.compute_eps_ttm("AAPL", datetime(2024, 4, 1, tzinfo=timezone.utc))
    assert ttm is not None
    assert abs(ttm - 5.00) < 1e-9


def test_compute_eps_ttm_returns_none_when_fewer_than_four_quarters():
    rows = [
        _quarterly("AAPL", datetime(2023, 5, 1, tzinfo=timezone.utc), 1.00),
        _quarterly("AAPL", datetime(2023, 8, 1, tzinfo=timezone.utc), 1.20),
        _quarterly("AAPL", datetime(2023, 11, 1, tzinfo=timezone.utc), 1.30),
    ]
    loader = FundamentalsPITLoader(rows)
    assert loader.compute_eps_ttm("AAPL", datetime(2024, 1, 1, tzinfo=timezone.utc)) is None


def test_compute_eps_ttm_excludes_10k_rows():
    """10-Ks report annual EPS — including them would double-count the year."""
    rows = [
        _quarterly("AAPL", datetime(2023, 5, 1, tzinfo=timezone.utc), 1.00),
        _quarterly("AAPL", datetime(2023, 8, 1, tzinfo=timezone.utc), 1.20),
        _quarterly("AAPL", datetime(2023, 11, 1, tzinfo=timezone.utc), 1.30),
        _snap("AAPL", datetime(2024, 1, 31, tzinfo=timezone.utc),
              source="edgar_10k", eps_diluted=5.00),  # annual — must be excluded
    ]
    loader = FundamentalsPITLoader(rows)
    # Only 3 quarterlies → returns None even though a 10-K is present.
    assert loader.compute_eps_ttm("AAPL", datetime(2024, 2, 15, tzinfo=timezone.utc)) is None


def test_compute_eps_ttm_skips_quarters_with_none_eps():
    rows = [
        _quarterly("AAPL", datetime(2023, 5, 1, tzinfo=timezone.utc), 1.00),
        _quarterly("AAPL", datetime(2023, 8, 1, tzinfo=timezone.utc), None),  # missing
        _quarterly("AAPL", datetime(2023, 11, 1, tzinfo=timezone.utc), 1.30),
        _quarterly("AAPL", datetime(2024, 2, 1, tzinfo=timezone.utc), 1.50),
    ]
    loader = FundamentalsPITLoader(rows)
    # 3 usable quarters, not 4 → None.
    assert loader.compute_eps_ttm("AAPL", datetime(2024, 4, 1, tzinfo=timezone.utc)) is None


def test_lookup_dict_auto_injects_eps_ttm():
    rows = [
        _quarterly("AAPL", datetime(2023, 5, 1, tzinfo=timezone.utc), 1.00),
        _quarterly("AAPL", datetime(2023, 8, 1, tzinfo=timezone.utc), 1.20),
        _quarterly("AAPL", datetime(2023, 11, 1, tzinfo=timezone.utc), 1.30),
        _quarterly("AAPL", datetime(2024, 2, 1, tzinfo=timezone.utc), 1.50),
    ]
    loader = FundamentalsPITLoader(rows)
    out = loader.lookup_dict(
        "AAPL", datetime(2024, 4, 1, tzinfo=timezone.utc), price=50.0,
    )
    # TTM = 5.0; PE = 50 / 5 = 10
    assert out["pe_trailing"] == 10.0
    assert "eps_ttm" not in out  # internal hint must not leak


def test_lookup_dict_caller_eps_ttm_overlay_wins():
    """When the caller supplies eps_ttm explicitly, that value beats the
    loader's auto-computed one. Lets tests pin specific TTM values."""
    rows = [
        _quarterly("AAPL", datetime(2023, 5, 1, tzinfo=timezone.utc), 1.00),
        _quarterly("AAPL", datetime(2023, 8, 1, tzinfo=timezone.utc), 1.20),
        _quarterly("AAPL", datetime(2023, 11, 1, tzinfo=timezone.utc), 1.30),
        _quarterly("AAPL", datetime(2024, 2, 1, tzinfo=timezone.utc), 1.50),
    ]
    loader = FundamentalsPITLoader(rows)
    out = loader.lookup_dict(
        "AAPL", datetime(2024, 4, 1, tzinfo=timezone.utc),
        price=50.0,
        overlay={"eps_ttm": 2.5},
    )
    # Caller-supplied TTM wins: PE = 50 / 2.5 = 20
    assert out["pe_trailing"] == 20.0
