"""yfinance-backed sector cache tests.

The cache file is JSON on disk, so we just point the cache_path at a
tmp_path and assert the cache file content + which tickers triggered
a network fetch.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from src.data.sector_cache import (
    DEFAULT_TTL_DAYS,
    _is_fresh,
    get_sectors,
    lookup_sector,
)


def test_fresh_row_skips_fetch(tmp_path: Path) -> None:
    cache_path = tmp_path / "sectors.json"
    cache_path.write_text(json.dumps({
        "AAPL": {
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "fetched_at": date.today().isoformat(),
        }
    }), encoding="utf-8")

    with patch("src.data.sector_cache._fetch_one") as mock_fetch:
        result = get_sectors(["AAPL"], cache_path=cache_path)

    mock_fetch.assert_not_called()
    assert result == {"AAPL": "Technology"}


def test_stale_row_triggers_refresh(tmp_path: Path) -> None:
    cache_path = tmp_path / "sectors.json"
    stale_date = (date.today() - timedelta(days=DEFAULT_TTL_DAYS + 5)).isoformat()
    cache_path.write_text(json.dumps({
        "AAPL": {
            "sector": "OldSector",
            "industry": "OldIndustry",
            "fetched_at": stale_date,
        }
    }), encoding="utf-8")

    with patch("src.data.sector_cache._fetch_one") as mock_fetch:
        mock_fetch.return_value = {
            "sector": "Technology", "industry": "Consumer Electronics",
        }
        result = get_sectors(["AAPL"], cache_path=cache_path)

    mock_fetch.assert_called_once_with("AAPL")
    assert result == {"AAPL": "Technology"}
    written = json.loads(cache_path.read_text())
    assert written["AAPL"]["sector"] == "Technology"
    assert written["AAPL"]["fetched_at"] == date.today().isoformat()


def test_cache_miss_triggers_fetch_and_writes_back(tmp_path: Path) -> None:
    cache_path = tmp_path / "sectors.json"
    assert not cache_path.exists()

    with patch("src.data.sector_cache._fetch_one") as mock_fetch:
        mock_fetch.return_value = {
            "sector": "Energy", "industry": "Oil & Gas E&P",
        }
        result = get_sectors(["OXY"], cache_path=cache_path)

    mock_fetch.assert_called_once_with("OXY")
    assert result == {"OXY": "Energy"}
    written = json.loads(cache_path.read_text())
    assert written["OXY"]["sector"] == "Energy"
    assert written["OXY"]["industry"] == "Oil & Gas E&P"


def test_max_fetches_caps_network_calls(tmp_path: Path) -> None:
    cache_path = tmp_path / "sectors.json"
    tickers = ["A", "B", "C", "D"]

    fetched = []

    def _record(t):
        fetched.append(t)
        return {"sector": "Tech", "industry": ""}

    with patch("src.data.sector_cache._fetch_one", side_effect=_record):
        result = get_sectors(tickers, cache_path=cache_path, max_fetches=2)

    # Only the first 2 should have been fetched. Remaining tickers
    # silently drop out of the result and will be retried next call.
    assert len(fetched) == 2
    assert len(result) == 2
    assert set(result.values()) == {"Tech"}


def test_refresh_forces_fetch_even_when_fresh(tmp_path: Path) -> None:
    cache_path = tmp_path / "sectors.json"
    cache_path.write_text(json.dumps({
        "AAPL": {
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "fetched_at": date.today().isoformat(),
        }
    }), encoding="utf-8")

    with patch("src.data.sector_cache._fetch_one") as mock_fetch:
        mock_fetch.return_value = {"sector": "Technology", "industry": ""}
        get_sectors(["AAPL"], cache_path=cache_path, refresh=True)

    mock_fetch.assert_called_once_with("AAPL")


def test_fetch_failure_does_not_pollute_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "sectors.json"

    with patch("src.data.sector_cache._fetch_one", return_value=None):
        result = get_sectors(["DEAD"], cache_path=cache_path)

    assert result == {}
    if cache_path.exists():
        # An empty cache file is fine; the contract is that the failed
        # ticker isn't written as a negative row so it gets re-attempted.
        assert "DEAD" not in json.loads(cache_path.read_text())


def test_malformed_cache_file_returns_empty(tmp_path: Path) -> None:
    cache_path = tmp_path / "sectors.json"
    cache_path.write_text("this is not json", encoding="utf-8")

    with patch("src.data.sector_cache._fetch_one") as mock_fetch:
        mock_fetch.return_value = {"sector": "Energy", "industry": ""}
        result = get_sectors(["OXY"], cache_path=cache_path)

    # We didn't crash on the malformed file; we just treated it as
    # empty and re-fetched.
    assert result == {"OXY": "Energy"}


def test_cache_non_dict_returns_empty(tmp_path: Path) -> None:
    cache_path = tmp_path / "sectors.json"
    cache_path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")

    with patch("src.data.sector_cache._fetch_one") as mock_fetch:
        mock_fetch.return_value = None
        result = get_sectors(["AAPL"], cache_path=cache_path)

    assert result == {}


def test_lookup_sector_returns_string(tmp_path: Path) -> None:
    cache_path = tmp_path / "sectors.json"
    cache_path.write_text(json.dumps({
        "AAPL": {
            "sector": "Technology", "industry": "",
            "fetched_at": date.today().isoformat(),
        }
    }), encoding="utf-8")

    assert lookup_sector("AAPL", cache_path=cache_path) == "Technology"


def test_lookup_sector_returns_none_on_miss(tmp_path: Path) -> None:
    cache_path = tmp_path / "sectors.json"
    with patch("src.data.sector_cache._fetch_one", return_value=None):
        assert lookup_sector("DEAD", cache_path=cache_path) is None


def test_tickers_uppercased_before_lookup(tmp_path: Path) -> None:
    cache_path = tmp_path / "sectors.json"
    cache_path.write_text(json.dumps({
        "AAPL": {
            "sector": "Technology", "industry": "",
            "fetched_at": date.today().isoformat(),
        }
    }), encoding="utf-8")

    with patch("src.data.sector_cache._fetch_one") as mock_fetch:
        result = get_sectors(["aapl"], cache_path=cache_path)

    mock_fetch.assert_not_called()
    assert result == {"AAPL": "Technology"}


def test_is_fresh_honors_ttl_days() -> None:
    fresh = {"fetched_at": date.today().isoformat()}
    stale = {"fetched_at": (date.today() - timedelta(days=100)).isoformat()}
    missing = {}
    bogus = {"fetched_at": "not-a-date"}

    assert _is_fresh(fresh, 30) is True
    assert _is_fresh(stale, 30) is False
    assert _is_fresh(missing, 30) is False
    assert _is_fresh(bogus, 30) is False
