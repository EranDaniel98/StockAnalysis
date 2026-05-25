"""Pipeline ``run_factor_picks(long_short=True)`` tests.

Exercises the integration of bottom-N selection with the sector-cap
selector and no-overlap invariant. The actual fundamentals + price
load is mocked at the loader boundary so the test doesn't require
Postgres or yfinance.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from src.factors.pipeline import FactorPicksResult, run_factor_picks


class _FakeLoader:
    """Minimal stand-in for FundamentalsPITLoader."""

    def __init__(self, sectors: dict[str, str]) -> None:
        self._sectors = sectors

    def lookup_sector(self, ticker: str, as_of) -> str | None:
        return self._sectors.get(ticker)

    def coverage(self) -> dict[str, int]:
        return {t: 1 for t in self._sectors}


def _make_composite(tickers: list[str]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "ticker": t,
            "raw": -i,
            "rank": i + 1,
            "z_score": -i * 0.1,
            "mean_normalized_rank": i * 0.01,
        }
        for i, t in enumerate(tickers)
    ])


def _make_factor_frame(tickers: list[str], offset: int = 0) -> pd.DataFrame:
    return pd.DataFrame([
        {"ticker": t, "rank": i + 1 + offset, "raw": -i - offset, "z_score": 0.0}
        for i, t in enumerate(tickers)
    ])


@pytest.fixture
def fake_pipeline():
    """Patch the heavy I/O paths so we can test the long-short branching
    without hitting Postgres / yfinance."""
    tickers = [f"T{i:02d}" for i in range(20)]
    prices = {t: pd.DataFrame({"Close": [100.0]}, index=[pd.Timestamp("2026-05-17")])
              for t in tickers}
    sectors = {t: "Tech" if i % 2 == 0 else "Energy" for i, t in enumerate(tickers)}

    with patch("src.factors.pipeline._load_fundamentals_sync") as mock_loader, \
         patch("src.storage.universe_loader.load_pit_sp500_with_prices") as mock_universe, \
         patch("src.data.sector_cache.get_sectors") as mock_sectors, \
         patch("src.factors.momentum.momentum_12_1") as mock_mom, \
         patch("src.factors.quality.quality_factor") as mock_qual, \
         patch("src.factors.value.value_factor") as mock_val:
        mock_universe.return_value = (tickers, prices)
        mock_loader.return_value = _FakeLoader(sectors)
        mock_sectors.return_value = sectors
        # Make the three factors agree so the composite ordering is
        # deterministic.
        mock_mom.return_value = _make_factor_frame(tickers)
        mock_qual.return_value = _make_factor_frame(tickers, offset=0)
        mock_val.return_value = _make_factor_frame(tickers, offset=0)
        yield tickers


def test_long_short_emits_shorts(fake_pipeline) -> None:
    result = run_factor_picks(
        as_of=pd.Timestamp("2026-05-17"),
        top_n=4,
        snapshot_id=None,
        max_sector_pct=None,
        long_short=True,
    )
    assert isinstance(result, FactorPicksResult)
    assert not result.top_n.empty
    assert not result.shorts.empty
    # No overlap between longs and shorts.
    long_set = set(result.top_n["ticker"])
    short_set = set(result.shorts["ticker"])
    assert long_set.isdisjoint(short_set)


def test_long_only_emits_empty_shorts(fake_pipeline) -> None:
    result = run_factor_picks(
        as_of=pd.Timestamp("2026-05-17"),
        top_n=4,
        snapshot_id=None,
        max_sector_pct=None,
        long_short=False,
    )
    assert result.shorts.empty


def test_long_short_short_n_overrides_top_n(fake_pipeline) -> None:
    result = run_factor_picks(
        as_of=pd.Timestamp("2026-05-17"),
        top_n=4,
        short_n=2,
        snapshot_id=None,
        max_sector_pct=None,
        long_short=True,
    )
    assert len(result.top_n) == 4
    assert len(result.shorts) == 2


def test_long_short_shorts_are_worst_ranked(fake_pipeline) -> None:
    result = run_factor_picks(
        as_of=pd.Timestamp("2026-05-17"),
        top_n=4,
        snapshot_id=None,
        max_sector_pct=None,
        long_short=True,
    )
    # Shorts should be at the END of the composite (highest rank numbers).
    short_ranks = result.shorts["rank"].tolist()
    long_ranks = result.top_n["rank"].tolist()
    assert min(short_ranks) > max(long_ranks)
