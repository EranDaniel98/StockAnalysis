"""Tier-2 audit #13: screener cache key must include the full filter dict.

Pre-fix: ``cache_key = f"screener_finviz_{sector_filter or 'all'}"``
discriminated only on sector. Two scans run with different ``markets.*``
config — different min_cap, min_volume, min_price, exchanges — would
collide on the same cache entry and silently return yesterday's
filter set.

After:
  * Cache key is ``screener_finviz_v2_{sector}_{hash(filters)}``.
  * Hash covers the FULL materialized filters_dict + max_stage1 cap.
  * ``v2_`` prefix auto-expires legacy entries written before #13.
"""

from __future__ import annotations

from src.data.screener import _make_screener_cache_key


def test_same_inputs_produce_same_key():
    """Stability sanity: hashing is deterministic."""
    k1 = _make_screener_cache_key("all", {"Market Cap.": "+Large (over $10bln)"}, 500)
    k2 = _make_screener_cache_key("all", {"Market Cap.": "+Large (over $10bln)"}, 500)
    assert k1 == k2


def test_different_filters_produce_different_keys():
    """The keystone: changing min_cap (which maps to a different
    'Market Cap.' bucket) MUST change the cache key."""
    k_large = _make_screener_cache_key(
        "all", {"Market Cap.": "+Large (over $10bln)"}, 500
    )
    k_small = _make_screener_cache_key(
        "all", {"Market Cap.": "+Small (over $300mln)"}, 500
    )
    assert k_large != k_small


def test_different_exchanges_produce_different_keys():
    """Exchange filter influences the result → must influence key."""
    k_nyse = _make_screener_cache_key(
        "all", {"Exchange": "NYSE"}, 500
    )
    k_nasdaq = _make_screener_cache_key(
        "all", {"Exchange": "NASDAQ"}, 500
    )
    assert k_nyse != k_nasdaq


def test_different_max_stage1_produces_different_key():
    """The max_stage1 cap influences which tickers come back. A scan
    capped at 50 must not share a cache entry with one capped at 500."""
    k_cap_50 = _make_screener_cache_key("all", {}, 50)
    k_cap_500 = _make_screener_cache_key("all", {}, 500)
    assert k_cap_50 != k_cap_500


def test_filter_dict_key_order_does_not_matter():
    """JSON sort_keys=True: dict iteration order can't change the key.
    Two equal filter sets must collapse to the same cache key
    regardless of how the keys are inserted."""
    k_ab = _make_screener_cache_key(
        "all",
        {"Market Cap.": "+Large (over $10bln)", "Exchange": "NYSE"},
        500,
    )
    k_ba = _make_screener_cache_key(
        "all",
        {"Exchange": "NYSE", "Market Cap.": "+Large (over $10bln)"},
        500,
    )
    assert k_ab == k_ba


def test_cache_key_uses_v2_prefix():
    """The v2_ prefix is what auto-expires legacy entries on first
    read. Pin the prefix so a future refactor doesn't silently strip
    it (which would un-fix the bug for existing caches)."""
    key = _make_screener_cache_key("all", {}, 500)
    assert key.startswith("screener_finviz_v2_")


def test_sector_filter_segregates_keys():
    """Same filter dict + different sector_filter still produces
    different keys — sector is part of the prefix, not the hash, so
    operators reading the cache can see sector at a glance."""
    k_all = _make_screener_cache_key("all", {"Exchange": "NYSE"}, 500)
    k_tech = _make_screener_cache_key("technology", {"Exchange": "NYSE"}, 500)
    assert k_all != k_tech
    assert "all" in k_all
    assert "technology" in k_tech
