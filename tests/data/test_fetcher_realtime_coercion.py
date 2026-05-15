"""yfinance fast_info coercion at the realtime-price boundary.

Sister regression to the fundamentals/BILL fix. The hunter found:

* ``src/data/fetcher.py:fetch_realtime_price`` was returning raw
  fast_info values via ``getattr(info, "last_price", None)`` with no
  coercion.
* ``src/execution/bootstrap_service.py:71-77`` then did
  ``current_px <= 0`` and ``shares * current_px`` on the uncoerced
  value. A yfinance fast_info string sentinel ('Infinity', 'NaN', ...)
  would crash the bootstrap position-sizing loop and prevent the paper
  account from matching portfolio.yaml.

After this fix, every numeric field in the fast_info dict is
``float | None`` regardless of what yfinance returned.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.data.fetcher import DataFetcher


def _stub_config():
    cfg = MagicMock()
    cfg.get = MagicMock(return_value=10)
    return cfg


def _stub_cache():
    cache = MagicMock()
    cache.get = MagicMock(return_value=None)
    cache.set = MagicMock()
    return cache


def _fast_info(**fields):
    """Build a fake yfinance.fast_info object using attribute access."""
    return SimpleNamespace(**fields)


def test_realtime_string_infinity_coerced_to_none():
    """The BILL class on the realtime side. fast_info returns
    last_price='Infinity'; downstream bootstrap_service.py does
    ``current_px <= 0`` which exploded with TypeError pre-fix.
    Coercion at the boundary makes it None instead."""
    fetcher = DataFetcher(_stub_config(), _stub_cache())
    fake = _fast_info(
        last_price="Infinity",
        previous_close=150.0,
        open=151.5,
        day_high=152.0,
        day_low=149.0,
        last_volume=1_000_000,
        market_cap=5_000_000_000,
    )
    with patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.fast_info = fake
        rt = fetcher.fetch_realtime_price("BILL")

    assert rt is not None
    assert rt["last_price"] is None
    # Other fields preserved as floats.
    assert rt["previous_close"] == 150.0
    assert rt["open"] == 151.5
    assert rt["market_cap"] == 5_000_000_000.0


def test_realtime_nan_coerced_to_none():
    """float('nan') from fast_info also short-circuits to None."""
    fetcher = DataFetcher(_stub_config(), _stub_cache())
    fake = _fast_info(
        last_price=float("nan"),
        previous_close="NaN",
        open=None,
        day_high=None,
        day_low=None,
        last_volume=None,
        market_cap=None,
    )
    with patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.fast_info = fake
        rt = fetcher.fetch_realtime_price("FOO")

    assert rt["last_price"] is None
    assert rt["previous_close"] is None


def test_realtime_normal_numbers_pass_through():
    """Healthy fast_info round-trip — every field a real float."""
    fetcher = DataFetcher(_stub_config(), _stub_cache())
    fake = _fast_info(
        last_price=125.50,
        previous_close=124.00,
        open=124.10,
        day_high=126.00,
        day_low=123.50,
        last_volume=2_500_000,
        market_cap=10_000_000_000,
    )
    with patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.fast_info = fake
        rt = fetcher.fetch_realtime_price("AAPL")

    assert rt == {
        "last_price": 125.50,
        "previous_close": 124.00,
        "open": 124.10,
        "day_high": 126.00,
        "day_low": 123.50,
        "last_volume": 2_500_000.0,
        "market_cap": 10_000_000_000.0,
    }


def test_realtime_bootstrap_comparison_does_not_crash():
    """End-to-end: ``current_px <= 0`` (the exact bootstrap site that
    blew up) must short-circuit cleanly when fast_info returned a
    string sentinel."""
    fetcher = DataFetcher(_stub_config(), _stub_cache())
    fake = _fast_info(
        last_price="Infinity",
        previous_close=None,
        open=None,
        day_high=None,
        day_low=None,
        last_volume=None,
        market_cap=None,
    )
    with patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.fast_info = fake
        rt = fetcher.fetch_realtime_price("BILL")

    current_px = rt.get("last_price") if rt else None
    # The exact bootstrap guard at bootstrap_service.py:72.
    assert (current_px is None or current_px <= 0)
