"""yfinance numeric-field coercion contract.

Regression for the BILL TypeError caught in the in-flight sweep battery
(2026-05-15). yfinance returned ``info["trailingPE"] = "Infinity"`` —
a string sentinel for "P/E undefined because earnings are negative".
The fundamental analyzer's ``pe > 0`` comparison then exploded with
``TypeError: '>' not supported between instances of 'str' and 'int'``,
silently dropping BILL from every Monday's scoring after 2024-05-20
(visible only after the score-ticker exception log was promoted from
debug to warning in commit 9345a74).

After this fix every numeric field passes through ``_coerce_numeric``
at the boundary, so downstream analyzers can rely on float-or-None.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

from src.data.fundamentals import FundamentalsFetcher, _coerce_numeric


# --- _coerce_numeric -------------------------------------------------------


def test_passes_through_real_numbers():
    assert _coerce_numeric(12.5) == 12.5
    assert _coerce_numeric(0) == 0.0
    assert _coerce_numeric(-3) == -3.0


def test_drops_string_infinity_keystone():
    """yfinance's quirkiest value. Caught in production on BILL."""
    assert _coerce_numeric("Infinity") is None
    assert _coerce_numeric("infinity") is None
    assert _coerce_numeric("-Infinity") is None


def test_drops_string_nan_and_empty():
    assert _coerce_numeric("NaN") is None
    assert _coerce_numeric("nan") is None
    assert _coerce_numeric("") is None
    assert _coerce_numeric("   ") is None
    assert _coerce_numeric("None") is None
    assert _coerce_numeric("null") is None


def test_drops_float_nan_and_inf():
    """Numeric NaN / Inf are no more useful than string sentinels — they
    still break > / <= comparisons unpredictably. Treat the same."""
    assert _coerce_numeric(float("nan")) is None
    assert _coerce_numeric(float("inf")) is None
    assert _coerce_numeric(float("-inf")) is None


def test_parses_numeric_strings():
    """Some yfinance values arrive as legitimate numeric strings.
    Parse them, return float."""
    assert _coerce_numeric("12.5") == 12.5
    assert _coerce_numeric("  -3  ") == -3.0


def test_drops_arbitrary_strings():
    assert _coerce_numeric("hello") is None
    assert _coerce_numeric("--") is None


def test_drops_other_types():
    assert _coerce_numeric([1, 2]) is None
    assert _coerce_numeric({"x": 1}) is None


# --- FundamentalsFetcher.fetch end-to-end ----------------------------------


def _stub_cache():
    cache = MagicMock()
    cache.get = MagicMock(return_value=None)
    cache.set = MagicMock()
    return cache


def _stub_config():
    cfg = MagicMock()
    cfg.get = MagicMock(return_value=10)
    return cfg


def test_bill_string_infinity_pe_is_coerced_to_none():
    """The BILL regression. yfinance returns ``trailingPE='Infinity'``;
    after the fix the fundamentals dict carries ``pe_trailing=None`` so
    downstream analyzers' ``pe > 0`` comparison short-circuits cleanly."""
    info = {
        "trailingPE": "Infinity",
        "sector": "Technology",
        "industry": "Software",
        "longName": "Bill.com Holdings",
        "marketCap": 5_000_000_000,
        "profitMargins": -0.15,
    }
    fetcher = FundamentalsFetcher(_stub_config(), _stub_cache())
    with patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.info = info
        fundamentals = fetcher.fetch("BILL")

    assert fundamentals is not None
    # The keystone assertion: 'Infinity' became None, not the string.
    assert fundamentals["pe_trailing"] is None
    # Other fields preserved correctly.
    assert fundamentals["market_cap"] == 5_000_000_000.0
    assert fundamentals["profit_margin"] == -0.15
    assert fundamentals["sector"] == "Technology"


def test_nan_field_coerced_to_none():
    """yfinance regularly returns NaN for missing analyst price targets
    on stocks with thin coverage. Same coercion path."""
    info = {
        "trailingPE": 15.0,
        "sector": "Technology",
        "targetMeanPrice": float("nan"),
        "targetHighPrice": "NaN",
    }
    fetcher = FundamentalsFetcher(_stub_config(), _stub_cache())
    with patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.info = info
        fundamentals = fetcher.fetch("FOO")

    assert fundamentals["target_mean_price"] is None
    assert fundamentals["target_high_price"] is None


def test_downstream_analyzer_does_not_explode_on_string_infinity():
    """End-to-end safety: even if the upstream coercion ever regresses,
    the analyzer's ``pe is not None and pe > 0`` guard MUST not crash
    on a 'Infinity' string. This is the suspenders half of
    belt+suspenders — the analyzer coerces on access via
    ``src.data.numeric.coerce_numeric`` so the comparison short-circuits
    cleanly even when an unsanitized dict reaches it."""
    from src.scoring.analyzers import fundamental as f_mod

    cfg = MagicMock()
    # _score_growth/health/profitability call config.get("fundamental_filters", default={})
    # and then .get(...) on the returned object; return a real dict so
    # filter lookups don't blow up before we even reach the coercion paths.
    cfg.get = MagicMock(return_value={
        "min_revenue_growth_pct": 10,
        "min_roe_pct": 10,
        "min_profit_margin_pct": 5,
        "max_pe_ratio": 50,
        "max_debt_to_equity": 2.0,
        "min_current_ratio": 1.0,
    })

    malformed = {
        "pe_trailing": "Infinity",       # string that bypassed coercion
        "pe_forward": "NaN",             # also poisoned
        "peg_ratio": "",                  # empty string
        "pb_ratio": 2.5,                 # legitimate value, must score
        "ev_to_ebitda": float("inf"),    # numeric inf
        "revenue_growth": "null",
        "roe": float("nan"),
        "debt_to_equity": "Infinity",
        "free_cash_flow": "None",
        "dividend_yield": "NaN",
        "sector": "Technology",
    }
    result = f_mod.analyze(malformed, cfg)
    assert isinstance(result, dict)
    # The one legitimate value (pb_ratio=2.5) must still register a
    # valuation score; everything else short-circuits to None and is
    # excluded from the category mean.
    assert result["scores"]["valuation"] is not None
    assert 0 <= result["score"] <= 100
