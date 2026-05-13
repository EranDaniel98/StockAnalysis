"""Parser enrichment tests — exercises derived ratios + YoY growth.

The synthetic XBRL fixture below covers two filing dates spaced ~365d apart
so the YoY pass has something to match. We only fill the concepts the parser
actually consumes; the rest of the EDGAR JSON shape is irrelevant.
"""

from __future__ import annotations

from src.market_data.edgar.parser import parse_company_facts


def _fact(end: str, filed: str, val: float, form: str = "10-Q") -> dict:
    return {"end": end, "filed": filed, "val": val, "form": form}


def _facts_payload() -> dict:
    """Two filings: 2023-Q2 (filed 2023-08-01) and 2024-Q2 (filed 2024-08-01).

    Both 10-Q so the parser's same-source YoY match picks the right pair.
    Revenue grows 100→120 (+20%), net income 10→15 (+50%), and the balance
    sheet is fully reported in 2024 only so we can verify per-snapshot ratios.
    """
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [
                    _fact("2023-06-30", "2023-08-01", 100.0),
                    _fact("2024-06-30", "2024-08-01", 120.0),
                ]}},
                "NetIncomeLoss": {"units": {"USD": [
                    _fact("2023-06-30", "2023-08-01", 10.0),
                    _fact("2024-06-30", "2024-08-01", 15.0),
                ]}},
                "GrossProfit": {"units": {"USD": [
                    _fact("2024-06-30", "2024-08-01", 60.0),
                ]}},
                "OperatingIncomeLoss": {"units": {"USD": [
                    _fact("2024-06-30", "2024-08-01", 24.0),
                ]}},
                "EarningsPerShareDiluted": {"units": {"USD/shares": [
                    _fact("2023-06-30", "2023-08-01", 0.50),
                    _fact("2024-06-30", "2024-08-01", 0.75),
                ]}},
                "StockholdersEquity": {"units": {"USD": [
                    _fact("2024-06-30", "2024-08-01", 200.0),
                ]}},
                "Assets": {"units": {"USD": [
                    _fact("2024-06-30", "2024-08-01", 500.0),
                ]}},
                "AssetsCurrent": {"units": {"USD": [
                    _fact("2024-06-30", "2024-08-01", 150.0),
                ]}},
                "LiabilitiesCurrent": {"units": {"USD": [
                    _fact("2024-06-30", "2024-08-01", 75.0),
                ]}},
                "LongTermDebt": {"units": {"USD": [
                    _fact("2024-06-30", "2024-08-01", 60.0),
                ]}},
                "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
                    _fact("2024-06-30", "2024-08-01", 40.0),
                ]}},
                "NetCashProvidedByOperatingActivities": {"units": {"USD": [
                    _fact("2024-06-30", "2024-08-01", 30.0),
                ]}},
            }
        }
    }


def test_parser_emits_one_snapshot_per_filing():
    snapshots = parse_company_facts("TEST", _facts_payload())
    assert len(snapshots) == 2


def test_2024_snapshot_has_all_derived_ratios():
    snapshots = parse_company_facts("TEST", _facts_payload())
    snap_2024 = next(s for s in snapshots if s.valid_from.year == 2024)
    # 60/120 = 0.5
    assert snap_2024.gross_margin == 0.5
    # 24/120 = 0.2
    assert snap_2024.operating_margin == 0.2
    # 15/120 = 0.125
    assert snap_2024.profit_margin == 0.125
    # 15/200 = 0.075
    assert snap_2024.roe == 0.075
    # 15/500 = 0.03
    assert snap_2024.roa == 0.03
    # 150/75 = 2.0
    assert snap_2024.current_ratio == 2.0
    # 60/200 = 0.3
    assert snap_2024.debt_to_equity == 0.3


def test_yoy_growth_computed_on_second_filing():
    snapshots = parse_company_facts("TEST", _facts_payload())
    snap_2023 = next(s for s in snapshots if s.valid_from.year == 2023)
    snap_2024 = next(s for s in snapshots if s.valid_from.year == 2024)
    # 2023 is the first filing — no prior-year row, so YoY is None.
    assert snap_2023.revenue_growth_yoy is None
    assert snap_2023.earnings_growth_yoy is None
    # 2024 revenue 120 vs 100 = +20%
    assert snap_2024.revenue_growth_yoy is not None
    assert abs(snap_2024.revenue_growth_yoy - 0.20) < 1e-9
    # 2024 EPS 0.75 vs 0.50 = +50%
    assert snap_2024.earnings_growth_yoy is not None
    assert abs(snap_2024.earnings_growth_yoy - 0.50) < 1e-9


def test_valid_to_chained_to_next_filing():
    snapshots = parse_company_facts("TEST", _facts_payload())
    snap_2023 = next(s for s in snapshots if s.valid_from.year == 2023)
    snap_2024 = next(s for s in snapshots if s.valid_from.year == 2024)
    assert snap_2023.valid_to == snap_2024.valid_from
    # Most recent row leaves valid_to open.
    assert snap_2024.valid_to is None


def test_zero_denominator_returns_none():
    """Filing with zero equity should not blow up on roe/debt_to_equity."""
    payload = {
        "facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [_fact("2024-06-30", "2024-08-01", 100.0)]}},
            "NetIncomeLoss": {"units": {"USD": [_fact("2024-06-30", "2024-08-01", 10.0)]}},
            "StockholdersEquity": {"units": {"USD": [_fact("2024-06-30", "2024-08-01", 0.0)]}},
            "LongTermDebt": {"units": {"USD": [_fact("2024-06-30", "2024-08-01", 50.0)]}},
        }}
    }
    snapshots = parse_company_facts("TEST", payload)
    assert len(snapshots) == 1
    assert snapshots[0].roe is None
    assert snapshots[0].debt_to_equity is None


def test_sign_flip_makes_yoy_none():
    """Prior-year loss → current-year profit can't be expressed as percent
    growth meaningfully; parser should return None instead of a misleading number."""
    payload = {
        "facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [
                _fact("2023-06-30", "2023-08-01", 100.0),
                _fact("2024-06-30", "2024-08-01", 120.0),
            ]}},
            "NetIncomeLoss": {"units": {"USD": [
                _fact("2023-06-30", "2023-08-01", -5.0),
                _fact("2024-06-30", "2024-08-01", 8.0),
            ]}},
            "EarningsPerShareDiluted": {"units": {"USD/shares": [
                _fact("2023-06-30", "2023-08-01", -0.25),
                _fact("2024-06-30", "2024-08-01", 0.40),
            ]}},
        }}
    }
    snapshots = parse_company_facts("TEST", payload)
    snap_2024 = next(s for s in snapshots if s.valid_from.year == 2024)
    assert snap_2024.earnings_growth_yoy is None
    # Revenue stayed positive — growth is still computable.
    assert snap_2024.revenue_growth_yoy is not None
