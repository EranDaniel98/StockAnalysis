"""Tier-2 audit #14: EDGAR parser must honor XBRL unit semantics.

Pre-fix ``_pick_concept_facts`` walked unit buckets in order:
    ``units.get("USD") or units.get("USD/shares") or units.get("shares") or []``

For EPS (expected unit = USD/shares), if the USD bucket was missing
(common — EPS isn't USD-denominated) the USD/shares bucket won, which
is correct.

BUT if BOTH USD and USD/shares were missing and ``shares`` was
populated (a filer's share count masquerading as eps_diluted), the
parser silently emitted a "diluted EPS = 1.5 billion" row into the
fundamentals timeline. Every downstream PEG / P/E score that touched
that ticker was poisoned.

After: ``expected_unit`` per field. The parser reads ONLY that bucket;
unexpected buckets are skipped with a debug log.
"""

from __future__ import annotations

from src.market_data.edgar.parser import _pick_concept_facts


def _block(unit_to_facts: dict[str, list[dict]]) -> dict:
    """Wrap unit-bucketed facts in the shape EDGAR returns."""
    return {"units": unit_to_facts}


def _fact(value, filed: str = "2024-03-01") -> dict:
    return {"val": value, "filed": filed, "form": "10-K"}


def test_picks_expected_usd_bucket():
    """Default expected_unit='USD' reads the USD bucket only."""
    us_gaap = {
        "Revenues": _block({
            "USD": [_fact(100_000_000)],
        }),
    }
    facts = _pick_concept_facts(us_gaap, ["Revenues"])  # default USD
    assert len(facts) == 1
    assert facts[0]["val"] == 100_000_000


def test_picks_usd_per_shares_bucket_when_requested():
    """EPS has expected_unit='USD/shares'. The parser reads that bucket
    and ignores any USD-denominated fact for the same concept."""
    us_gaap = {
        "EarningsPerShareDiluted": _block({
            "USD/shares": [_fact(2.5)],
            "USD": [_fact(99_999_999)],  # malformed but present — must NOT win
        }),
    }
    facts = _pick_concept_facts(
        us_gaap, ["EarningsPerShareDiluted"], expected_unit="USD/shares",
    )
    assert len(facts) == 1
    assert facts[0]["val"] == 2.5


def test_skips_concept_when_expected_unit_missing():
    """The keystone: if a concept has ONLY a wrong-unit bucket
    populated, the parser MUST skip it. Pre-fix it would have grabbed
    the wrong value. After: empty result, field stays None upstream."""
    us_gaap = {
        "EarningsPerShareDiluted": _block({
            "shares": [_fact(1_500_000_000)],  # share count, not EPS!
        }),
    }
    facts = _pick_concept_facts(
        us_gaap, ["EarningsPerShareDiluted"], expected_unit="USD/shares",
    )
    assert facts == []


def test_walks_multiple_concepts_in_priority_order():
    """Behavior preserved from pre-fix: when a high-priority concept is
    present at a filed date, it wins over a low-priority concept on the
    same date. Lower-priority concepts still contribute on dates where
    high-priority is absent."""
    us_gaap = {
        "Revenues": _block({
            "USD": [_fact(100, filed="2024-03-01")],
        }),
        "SalesRevenueNet": _block({
            "USD": [
                _fact(50, filed="2024-03-01"),     # collides with Revenues
                _fact(80, filed="2023-12-01"),     # unique date
            ],
        }),
    }
    facts = _pick_concept_facts(
        us_gaap, ["Revenues", "SalesRevenueNet"],
    )
    by_filed = {f["filed"]: f["val"] for f in facts}
    # 2024-03-01 was reported by both → Revenues (higher priority) wins.
    assert by_filed["2024-03-01"] == 100
    # 2023-12-01 only reported by SalesRevenueNet → its value lands.
    assert by_filed["2023-12-01"] == 80


def test_pre_fix_eps_corruption_no_longer_happens():
    """End-to-end reproducer of the #14 bug. A filing with a populated
    'shares' bucket and empty USD/shares for the EPS concept used to
    leak the share count into the fundamentals timeline as EPS. After
    the fix, the value is dropped and the field stays absent."""
    us_gaap = {
        "EarningsPerShareDiluted": _block({
            "USD/shares": [],  # empty — the real EPS is missing
            "shares": [_fact(1_234_567_890)],  # malformed share count
            "USD": [],
        }),
    }
    facts = _pick_concept_facts(
        us_gaap, ["EarningsPerShareDiluted"], expected_unit="USD/shares",
    )
    # Empty: parser correctly refuses to read the share count as EPS.
    assert facts == []
