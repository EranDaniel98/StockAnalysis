"""Tests for the shared universe + price loader."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from src.storage import universe_loader


def _make_tz_aware_price_frame() -> pd.DataFrame:
    idx = pd.bdate_range("2026-01-01", periods=10, tz="UTC")
    return pd.DataFrame({"Close": [100.0] * 10, "Volume": [1] * 10}, index=idx)


def test_normalize_tz_strips_timezone() -> None:
    df = _make_tz_aware_price_frame()
    out = universe_loader._normalize_tz(df)
    assert out.index.tz is None
    # Source was not mutated (defensive copy).
    assert df.index.tz is not None


def test_normalize_tz_no_op_on_naive() -> None:
    df = pd.DataFrame(
        {"Close": [1.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-01-01")]),
    )
    out = universe_loader._normalize_tz(df)
    assert out is df  # no copy required


def test_normalize_tz_handles_empty() -> None:
    assert universe_loader._normalize_tz(pd.DataFrame()).empty


def test_load_prices_drops_empty_and_normalizes_tz() -> None:
    raw = {
        "AAPL": _make_tz_aware_price_frame(),
        "EMPTY": pd.DataFrame(),
        "MSFT": _make_tz_aware_price_frame(),
    }
    fake_fetcher = MagicMock()
    fake_fetcher.fetch_batch.return_value = raw
    fake_config = MagicMock()
    fake_config.get.return_value = 24

    with patch.object(
        universe_loader, "_build_cache", return_value=MagicMock(),
    ), patch(
        "src.data.fetcher.DataFetcher", return_value=fake_fetcher,
    ):
        out = universe_loader.load_prices(["AAPL", "EMPTY", "MSFT"], config=fake_config)

    assert set(out.keys()) == {"AAPL", "MSFT"}
    for df in out.values():
        assert df.index.tz is None


def test_load_pit_sp500_with_prices_appends_extras() -> None:
    fake_config = MagicMock()
    fake_config.get_sp500_pit_tickers.return_value = ["AAPL", "MSFT"]
    fake_config.get.return_value = 24
    raw = {t: _make_tz_aware_price_frame() for t in ["AAPL", "MSFT", "ZZZZ"]}
    fake_fetcher = MagicMock()
    fake_fetcher.fetch_batch.return_value = raw

    with patch.object(
        universe_loader, "_build_cache", return_value=MagicMock(),
    ), patch(
        "src.data.fetcher.DataFetcher", return_value=fake_fetcher,
    ):
        universe, prices = universe_loader.load_pit_sp500_with_prices(
            pd.Timestamp("2026-05-17"),
            extra_tickers=["ZZZZ", "AAPL"],
            config=fake_config,
        )

    # AAPL appears once even though listed in both PIT and extras.
    assert universe == ["AAPL", "MSFT", "ZZZZ"]
    assert set(prices.keys()) == {"AAPL", "MSFT", "ZZZZ"}


def test_load_pit_sp500_raises_on_empty_universe() -> None:
    fake_config = MagicMock()
    fake_config.get_sp500_pit_tickers.return_value = []
    with pytest.raises(RuntimeError, match="universe is empty"):
        universe_loader.load_pit_sp500_with_prices(
            pd.Timestamp("2026-05-17"), config=fake_config,
        )
