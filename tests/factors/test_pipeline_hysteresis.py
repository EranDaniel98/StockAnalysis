"""Pipeline hysteresis tests.

Pin the invariant: a held name with composite rank just outside the
top-N stays in when the bonus is large enough, and gets booted when
its rank drifts past the bonus envelope.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from src.factors.pipeline import FactorPicksResult, run_factor_picks


class _FakeLoader:
    def __init__(self, sectors: dict[str, str]) -> None:
        self._sectors = sectors

    def lookup_sector(self, ticker: str, as_of) -> str | None:
        return self._sectors.get(ticker)

    def coverage(self) -> dict[str, int]:
        return {t: 1 for t in self._sectors}


def _make_factor_frame(tickers: list[str], offset: int = 0) -> pd.DataFrame:
    return pd.DataFrame([
        {"ticker": t, "rank": i + 1 + offset, "raw": -i - offset, "z_score": 0.0}
        for i, t in enumerate(tickers)
    ])


@pytest.fixture
def fake_pipeline_30():
    """30-name fake universe — composite ranks 1..30 in order T00..T29."""
    tickers = [f"T{i:02d}" for i in range(30)]
    prices = {
        t: pd.DataFrame(
            {"Close": [100.0]},
            index=[pd.Timestamp("2026-05-17")],
        )
        for t in tickers
    }
    sectors = {t: "Tech" for t in tickers}

    with patch("src.factors.pipeline._load_fundamentals_sync") as mock_loader, \
         patch("src.storage.universe_loader.load_pit_sp500_with_prices") as mock_universe, \
         patch("src.data.sector_cache.get_sectors") as mock_sectors, \
         patch("src.factors.momentum.momentum_12_1") as mock_mom, \
         patch("src.factors.quality.quality_factor") as mock_qual, \
         patch("src.factors.value.value_factor") as mock_val:
        mock_universe.return_value = (tickers, prices)
        mock_loader.return_value = _FakeLoader(sectors)
        mock_sectors.return_value = sectors
        mock_mom.return_value = _make_factor_frame(tickers)
        mock_qual.return_value = _make_factor_frame(tickers, offset=0)
        mock_val.return_value = _make_factor_frame(tickers, offset=0)
        yield tickers


def test_hysteresis_zero_is_baseline(fake_pipeline_30) -> None:
    """bonus=0.0 must produce identical selection to no previous_longs."""
    baseline = run_factor_picks(
        as_of=pd.Timestamp("2026-05-17"), top_n=5, snapshot_id=None,
        max_sector_pct=None,
    )
    with_zero = run_factor_picks(
        as_of=pd.Timestamp("2026-05-17"), top_n=5, snapshot_id=None,
        max_sector_pct=None,
        hysteresis_bonus=0.0,
        previous_longs=["T10", "T20"],
    )
    assert list(baseline.top_n["ticker"]) == list(with_zero.top_n["ticker"])


def test_hysteresis_keeps_held_name_just_outside_top_n(fake_pipeline_30) -> None:
    """A previously-held T06 (rank 7) gets a 0.75*5=4 slot bonus → effective
    rank 3 → stays in the top-5."""
    result = run_factor_picks(
        as_of=pd.Timestamp("2026-05-17"), top_n=5, snapshot_id=None,
        max_sector_pct=None,
        hysteresis_bonus=0.75,
        previous_longs=["T06"],  # composite rank 7 (0-indexed: T00 is rank 1)
    )
    assert "T06" in set(result.top_n["ticker"])


def test_hysteresis_evicts_held_name_past_envelope(fake_pipeline_30) -> None:
    """A held name with rank 20 is past the bonus envelope (top-5 + 4 = 9).
    Even with a generous 0.75 bonus, it should be evicted."""
    result = run_factor_picks(
        as_of=pd.Timestamp("2026-05-17"), top_n=5, snapshot_id=None,
        max_sector_pct=None,
        hysteresis_bonus=0.75,
        previous_longs=["T19"],
    )
    assert "T19" not in set(result.top_n["ticker"])


def test_hysteresis_with_no_previous_longs_is_baseline(fake_pipeline_30) -> None:
    baseline = run_factor_picks(
        as_of=pd.Timestamp("2026-05-17"), top_n=5, snapshot_id=None,
        max_sector_pct=None,
    )
    no_priors = run_factor_picks(
        as_of=pd.Timestamp("2026-05-17"), top_n=5, snapshot_id=None,
        max_sector_pct=None,
        hysteresis_bonus=0.75,
        previous_longs=[],
        previous_shorts=[],
    )
    assert list(baseline.top_n["ticker"]) == list(no_priors.top_n["ticker"])


def test_hysteresis_short_side_keeps_held_short(fake_pipeline_30) -> None:
    """Held shorts get the symmetric bonus — pushed FURTHER down so they
    remain in the bottom-N pick."""
    # Composite rank 24 (T23) is just outside the bottom-5 (T25..T29).
    # With a 0.75*5=4 slot bonus, effective rank becomes 28 → stays as short.
    result = run_factor_picks(
        as_of=pd.Timestamp("2026-05-17"), top_n=5, snapshot_id=None,
        max_sector_pct=None,
        long_short=True, short_n=5,
        hysteresis_bonus=0.75,
        previous_shorts=["T23"],
    )
    assert "T23" in set(result.shorts["ticker"])
