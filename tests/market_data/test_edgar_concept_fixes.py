"""EDGAR concept-map correctness (Tier-1 audit #9).

Covers D#5 (total_debt aggregation) and D#6 (free_cash_flow vs OCF).

D#5: `total_debt` used to include `DebtCurrent` in the candidate list
and let first-match win, so a filer reporting only DebtCurrent had that
under-reported number emitted as total_debt. Now `total_debt` is
`LongTermDebt + DebtCurrent` when at least one component is present,
None when neither is reported.

D#6: `free_cash_flow` used to map to NetCashProvidedByOperatingActivities
only — OCF as a proxy. The downstream fundamental analyzer's
"FCF > 0 -> bullish" rule then scored CapEx-heavy filers as cash-positive
when their true FCF was negative. Now `free_cash_flow = OCF - CapEx`
when CapEx is reported, with a logged warning when it isn't.
"""

from __future__ import annotations

from typing import Any

from src.market_data.edgar.parser import (
    _compute_fcf,
    _sum_optional_components,
    parse_company_facts,
)


# --- _sum_optional_components ---------------------------------------------


def test_sum_components_returns_none_when_all_missing():
    assert _sum_optional_components(None, None) is None


def test_sum_components_passes_through_single_value():
    """A filer that reports only LT debt or only current debt yields
    that value as total_debt — not a None that would hide it."""
    assert _sum_optional_components(1_000_000.0, None) == 1_000_000.0
    assert _sum_optional_components(None, 250_000.0) == 250_000.0


def test_sum_components_aggregates_both():
    """The keystone D#5 assertion: when both components are reported,
    total_debt is the sum, NOT first-match. Previously a filer reporting
    LT=$2B and current=$500M had total_debt=$2B (first match wins on
    reverse-priority iteration); now it's $2.5B."""
    assert _sum_optional_components(2_000_000_000.0, 500_000_000.0) == 2_500_000_000.0


def test_sum_components_ignores_non_numeric():
    """Defensive: a malformed value in the dict must not crash the
    snapshot construction for the entire filing."""
    assert _sum_optional_components(1000.0, "not a number") == 1000.0


# --- _compute_fcf ----------------------------------------------------------


def test_fcf_returns_none_when_ocf_missing():
    assert _compute_fcf(None, 500.0) is None


def test_fcf_subtracts_positive_capex_from_ocf():
    """D#6 keystone: a CapEx-heavy filer must have FCF = OCF - CapEx,
    not OCF on its own. Previously OCF=$1B + CapEx=$1.2B yielded FCF=$1B
    (-> analyzer scored 'FCF positive'); now it yields -$200M ('negative
    FCF', the correct bearish signal)."""
    fcf = _compute_fcf(ocf=1_000_000_000.0, capex=1_200_000_000.0)
    assert fcf == -200_000_000.0


def test_fcf_falls_back_to_ocf_when_capex_missing(caplog):
    """When CapEx is absent the function falls back to OCF as a proxy
    but logs a warning so misses are visible in operator logs."""
    import logging
    caplog.set_level(logging.WARNING, logger="src.market_data.edgar.parser")
    fcf = _compute_fcf(ocf=500_000_000.0, capex=None, ticker="AAPL", filed="2023-09-30")
    assert fcf == 500_000_000.0
    assert any(
        "CapEx missing" in r.message and "AAPL" in r.message
        for r in caplog.records
    )


def test_fcf_handles_negative_capex_as_outflow():
    """Some filers report CapEx with an explicit negative sign on the
    statement (it's a cash outflow). Take the absolute value so we
    always SUBTRACT capex from OCF, never add it."""
    fcf = _compute_fcf(ocf=1_000_000_000.0, capex=-300_000_000.0)
    assert fcf == 700_000_000.0


# --- parse_company_facts end-to-end ---------------------------------------


def _facts(concept: str, val: float, *, end: str = "2023-09-30",
           filed: str = "2023-11-03", form: str = "10-K") -> dict[str, Any]:
    return {
        concept: {
            "units": {
                "USD": [
                    {"end": end, "val": val, "filed": filed, "form": form, "accn": "x"},
                ]
            }
        }
    }


def test_filer_with_only_long_term_debt():
    """A filer reporting only LongTermDebt should produce total_debt
    equal to that value (no current debt to add)."""
    payload = {"facts": {"us-gaap": {
        **_facts("Revenues", 100_000_000.0),
        **_facts("LongTermDebt", 50_000_000.0),
        **_facts("NetCashProvidedByOperatingActivities", 20_000_000.0),
    }}}
    snaps = parse_company_facts("TEST", payload)
    assert len(snaps) == 1
    assert snaps[0].total_debt == 50_000_000.0


def test_filer_with_only_current_debt_does_not_pretend_to_total():
    """D#5 specific: a filer reporting ONLY DebtCurrent (not LT) used
    to have that number emitted as total_debt — under-reporting. Now
    it's still surfaced via the current_debt summation, but at least
    we know we're not missing the LT portion silently. This test pins
    the new behavior: total_debt = current_debt when LT is absent."""
    payload = {"facts": {"us-gaap": {
        **_facts("Revenues", 100_000_000.0),
        **_facts("DebtCurrent", 10_000_000.0),
        **_facts("NetCashProvidedByOperatingActivities", 20_000_000.0),
    }}}
    snaps = parse_company_facts("TEST", payload)
    assert len(snaps) == 1
    # total_debt is 10M (the only debt component reported), NOT something
    # higher that pretended LT was also reported. The honest-reporting
    # contract is: total_debt reflects what was actually disclosed.
    assert snaps[0].total_debt == 10_000_000.0


def test_filer_with_both_components_sums():
    """D#5 keystone: LT + DebtCurrent must SUM, not first-match."""
    payload = {"facts": {"us-gaap": {
        **_facts("Revenues", 100_000_000.0),
        **_facts("LongTermDebt", 80_000_000.0),
        **_facts("DebtCurrent", 20_000_000.0),
        **_facts("NetCashProvidedByOperatingActivities", 30_000_000.0),
    }}}
    snaps = parse_company_facts("TEST", payload)
    assert len(snaps) == 1
    assert snaps[0].total_debt == 100_000_000.0  # 80M + 20M


def test_fcf_subtracts_capex_at_filing_level():
    """D#6 end-to-end: a filing with OCF=$1B and CapEx=$300M produces
    a FundamentalSnapshot with free_cash_flow=$700M (true FCF), NOT
    $1B (OCF-as-proxy)."""
    payload = {"facts": {"us-gaap": {
        **_facts("Revenues", 5_000_000_000.0),
        **_facts("NetCashProvidedByOperatingActivities", 1_000_000_000.0),
        **_facts("PaymentsToAcquirePropertyPlantAndEquipment", 300_000_000.0),
    }}}
    snaps = parse_company_facts("TEST", payload)
    assert len(snaps) == 1
    assert snaps[0].free_cash_flow == 700_000_000.0


def test_fcf_falls_back_to_ocf_when_capex_absent():
    """A filing without a CapEx tag still produces a free_cash_flow row
    (OCF as proxy) — analyzer keeps a value to score against, and the
    parser logs the proxy at WARNING."""
    payload = {"facts": {"us-gaap": {
        **_facts("Revenues", 1_000_000.0),
        **_facts("NetCashProvidedByOperatingActivities", 500_000_000.0),
        # No PaymentsToAcquirePropertyPlantAndEquipment
    }}}
    snaps = parse_company_facts("TEST", payload)
    assert len(snaps) == 1
    assert snaps[0].free_cash_flow == 500_000_000.0
