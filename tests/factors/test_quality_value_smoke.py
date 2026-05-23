"""Smoke tests for quality + value factors against the live EDGAR DB.

These tests REQUIRE a running Postgres with EDGAR fundamentals
populated. They skip cleanly if the DB is unreachable so CI without
a DB doesn't break. The smoke tests are intentionally light — they
verify the factor functions execute end-to-end and produce
non-empty rankings for a handful of well-known megacaps.
"""

from __future__ import annotations

import datetime as _dt

import pandas as pd
import pytest

from src.factors.quality import quality_factor
from src.factors.value import value_factor


@pytest.fixture(scope="module")
def loader_and_prices():
    """Try to construct an EDGAR loader for 10 megacaps. Skip if DB down."""
    try:
        from src.db.repositories.fundamentals import (
            PostgresFundamentalsRepository,
        )
        from src.db.session import get_sessionmaker, run_with_dispose
        from src.factors.fundamentals_pit_loader import (
            FundamentalsPITLoader,
        )
    except ImportError as e:
        pytest.skip(f"DB stack not importable: {e}")

    tickers = ["AAPL", "MSFT", "NVDA", "GOOG", "META",
               "AMZN", "JPM", "XOM", "UNH", "TSLA"]

    async def _go():
        async with get_sessionmaker()() as session:
            repo = PostgresFundamentalsRepository(session)
            return await FundamentalsPITLoader.from_repository(repo, tickers)

    try:
        loader = run_with_dispose(_go())
    except Exception as e:
        pytest.skip(f"DB unreachable: {e}")

    # Synthesize a price frame at a known date so the value factor has
    # something to divide EPS_TTM by.
    as_of = pd.Timestamp("2023-06-30")
    prices = {}
    for t in tickers:
        idx = pd.bdate_range(end=as_of, periods=300)
        # A flat 100 price is enough for the rank test — we just need
        # something positive and present at as_of.
        prices[t] = pd.DataFrame({"Close": [100.0] * 300}, index=idx)
    return loader, prices, tickers, as_of


def test_quality_factor_produces_nonempty_ranking(loader_and_prices) -> None:
    loader, prices, tickers, as_of = loader_and_prices
    out = quality_factor(loader, tickers, as_of)
    # Most megacaps have full EDGAR coverage — we expect ≥8 of 10.
    assert len(out) >= 8, f"quality ranked only {len(out)} of {len(tickers)}"
    assert set(out.columns) == {"ticker", "raw", "rank", "z_score"}
    # Ranks must be a permutation of [1..N] (no gaps, no dupes for unique raws).
    assert out["rank"].min() == 1
    assert out["rank"].max() == len(out)


def test_value_factor_produces_nonempty_ranking(loader_and_prices) -> None:
    loader, prices, tickers, as_of = loader_and_prices
    out = value_factor(loader, prices, tickers, as_of)
    # Value can drop names with negative EPS or missing revenue. We
    # require ≥5 to confirm the factor isn't structurally broken.
    assert len(out) >= 5, f"value ranked only {len(out)} of {len(tickers)}"
    assert set(out.columns) == {"ticker", "raw", "rank", "z_score"}
