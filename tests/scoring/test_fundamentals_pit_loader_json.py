"""Round-trip tests for FundamentalsPITLoader JSON serialization."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.contracts.entities.fundamentals import FundamentalSnapshot
from src.scoring.fundamentals_pit_loader import FundamentalsPITLoader


def _make_snap(
    ticker: str, valid_from: datetime, valid_to: datetime | None = None,
    *, source: str = "edgar_10q", pe_ratio: float | None = 20.0,
    eps_diluted: float | None = 1.5, sector: str | None = "Technology",
) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        ticker=ticker, valid_from=valid_from, valid_to=valid_to,
        source=source, pe_ratio=pe_ratio, pb_ratio=None, ps_ratio=None,
        ev_to_ebitda=None, revenue=None, revenue_growth_yoy=None,
        earnings_growth_yoy=None, eps_diluted=eps_diluted,
        gross_margin=None, operating_margin=None, profit_margin=None,
        roe=None, roa=None, debt_to_equity=None, current_ratio=None,
        free_cash_flow=None, total_cash=None, total_debt=None,
        dividend_yield=None, payout_ratio=None, sector=sector,
        industry=None, market_cap=None, name=None,
    )


def test_roundtrip_preserves_lookups(tmp_path: Path):
    vf1 = datetime(2024, 1, 15, tzinfo=timezone.utc)
    vf2 = datetime(2024, 4, 15, tzinfo=timezone.utc)
    snaps = [
        _make_snap("AAPL", vf1, source="edgar_10q", pe_ratio=25.0),
        _make_snap("AAPL", vf2, source="edgar_10q", pe_ratio=28.5),
        _make_snap("MSFT", vf1, source="edgar_10q", pe_ratio=30.0, sector="Technology"),
    ]
    original = FundamentalsPITLoader(snaps)

    cache_path = tmp_path / "fund_pit.json"
    original.to_json(cache_path)
    assert cache_path.exists()

    restored = FundamentalsPITLoader.from_json(cache_path)
    assert restored.tickers == {"AAPL", "MSFT"}

    # AAPL at as_of after vf2 should pick the newer snapshot (pe=28.5).
    aapl_late = restored.lookup("AAPL", datetime(2024, 6, 1, tzinfo=timezone.utc))
    assert aapl_late is not None
    assert aapl_late.pe_ratio == 28.5

    # AAPL at as_of between vf1 and vf2 picks the older snapshot.
    aapl_mid = restored.lookup("AAPL", datetime(2024, 3, 1, tzinfo=timezone.utc))
    assert aapl_mid is not None
    assert aapl_mid.pe_ratio == 25.0


def test_from_json_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        FundamentalsPITLoader.from_json(tmp_path / "does_not_exist.json")


def test_empty_loader_roundtrips(tmp_path: Path):
    original = FundamentalsPITLoader([])
    cache_path = tmp_path / "empty.json"
    original.to_json(cache_path)
    restored = FundamentalsPITLoader.from_json(cache_path)
    assert restored.tickers == set()


def test_valid_to_preserves_through_roundtrip(tmp_path: Path):
    vf = datetime(2024, 1, 15, tzinfo=timezone.utc)
    vt = datetime(2024, 4, 15, tzinfo=timezone.utc)
    snaps = [_make_snap("AAPL", vf, vt, pe_ratio=22.0)]
    original = FundamentalsPITLoader(snaps)
    cache_path = tmp_path / "fund.json"
    original.to_json(cache_path)
    restored = FundamentalsPITLoader.from_json(cache_path)
    # Lookup AFTER valid_to should return None.
    after_vt = restored.lookup("AAPL", datetime(2024, 5, 1, tzinfo=timezone.utc))
    assert after_vt is None
    # Lookup BETWEEN vf and vt should hit.
    in_window = restored.lookup("AAPL", datetime(2024, 3, 1, tzinfo=timezone.utc))
    assert in_window is not None
    assert in_window.pe_ratio == 22.0


def test_coverage_after_roundtrip(tmp_path: Path):
    vf = datetime(2024, 1, 15, tzinfo=timezone.utc)
    snaps = [
        _make_snap("A", vf), _make_snap("A", vf.replace(month=4)),
        _make_snap("B", vf),
    ]
    original = FundamentalsPITLoader(snaps)
    cache_path = tmp_path / "fund.json"
    original.to_json(cache_path)
    restored = FundamentalsPITLoader.from_json(cache_path)
    cov = restored.coverage()
    assert cov["A"] == 2
    assert cov["B"] == 1
