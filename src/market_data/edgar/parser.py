"""Parse EDGAR companyfacts JSON into typed FundamentalSnapshot rows.

The EDGAR JSON shape (excerpt):

    {
      "cik": 320193,
      "entityName": "Apple Inc.",
      "facts": {
        "us-gaap": {
          "Revenues": {
            "label": "Revenues",
            "description": "...",
            "units": {
              "USD": [
                {
                  "end": "2023-09-30",
                  "val": 383285000000,
                  "accn": "0000320193-23-000106",
                  "fy": 2023, "fp": "FY",
                  "form": "10-K",
                  "filed": "2023-11-03",
                  ...
                },
                ...
              ]
            }
          },
          ...
        }
      }
    }

Parsing strategy:
  1. For each FundamentalSnapshot field, walk CONCEPT_MAP's concept list and
     pick the first concept present in `facts.us-gaap`.
  2. For each fact, key by `(form, end)` and pick the latest `filed` date.
     Multiple amendments (10-Q/A) appear with the same end date — last
     filed wins.
  3. Group facts by `filed` date so we emit one FundamentalSnapshot per
     (ticker, filing) with all available fields filled in.
  4. `valid_from = filed`, `valid_to` is set in a second pass after sorting
     so each snapshot's valid_to = the next filed date for the same ticker.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from src.contracts.entities.fundamentals import FundamentalSnapshot, FundamentalsSource
from src.market_data.edgar.concept_map import CONCEPT_MAP, DERIVED_CONCEPTS

logger = logging.getLogger(__name__)


def _parse_filed(date_str: str) -> datetime:
    """EDGAR filing dates are YYYY-MM-DD strings, naive. Treat as UTC noon
    (avoids day-rollover ambiguity with the valid_to chaining)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.replace(hour=12, tzinfo=timezone.utc)


def _form_to_source(form: str) -> FundamentalsSource | None:
    """Map EDGAR form types to our typed source enum. Anything that isn't
    10-Q or 10-K (e.g. 8-K, S-1, 10-Q/A amendments) we skip — those don't
    have the comprehensive financial-statement disclosures."""
    form_norm = form.upper().strip()
    if form_norm == "10-K":
        return "edgar_10k"
    if form_norm == "10-Q":
        return "edgar_10q"
    return None


def _pick_concept_facts(
    us_gaap: dict[str, Any], concepts: list[str]
) -> list[dict[str, Any]]:
    """Merge facts across all matching concepts in priority order.

    Companies change tagging conventions across filing eras (e.g. AAPL
    used SalesRevenueNet pre-2019, then switched to
    RevenueFromContractWithCustomerExcludingAssessedTax under ASC 606).
    Both need to contribute to the merged timeline, so we walk EVERY
    concept in the list, dedupe by `filed` date with higher-priority
    concepts winning ties.
    """
    merged_by_filed: dict[str, dict[str, Any]] = {}
    # Walk in REVERSE priority order so high-priority concepts overwrite
    # lower-priority ones on duplicate filed dates.
    for c in reversed(concepts):
        block = us_gaap.get(c)
        if not block:
            continue
        units = block.get("units", {})
        usd = units.get("USD") or units.get("USD/shares") or units.get("shares") or []
        for fact in usd:
            filed = fact.get("filed")
            if filed:
                merged_by_filed[filed] = fact
    return list(merged_by_filed.values())


def _facts_by_filing(facts_list: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Key facts by `filed` date. When multiple amendments share a filed
    date (rare but possible), the LAST one in the iteration wins —
    EDGAR returns chronological order so that's the most recent amendment."""
    by_filed: dict[str, dict[str, Any]] = {}
    for fact in facts_list:
        filed = fact.get("filed")
        form = fact.get("form", "")
        # Skip non-10K/Q forms
        if _form_to_source(form) is None:
            continue
        if not filed:
            continue
        by_filed[filed] = fact
    return by_filed


def parse_company_facts(
    ticker: str,
    facts_json: dict[str, Any],
) -> list[FundamentalSnapshot]:
    """Convert one company's full EDGAR facts payload into a list of
    FundamentalSnapshot rows, one per 10-Q/10-K filing date.

    Each snapshot has the maximum number of typed fields we can fill from
    that filing. Concepts not reported in a given filing leave the field
    None — repository upserts handle the partial-row case fine.
    """
    us_gaap = facts_json.get("facts", {}).get("us-gaap", {})
    if not us_gaap:
        logger.warning("No us-gaap facts in EDGAR payload for %s", ticker)
        return []

    # Per-field, per-filed-date intermediate map:
    #   field_values[filed_date][field_name] = (value, form)
    field_values: dict[str, dict[str, tuple[Any, str]]] = defaultdict(dict)

    def _absorb(field: str, concepts: list[str]) -> None:
        facts = _pick_concept_facts(us_gaap, concepts)
        for filed, fact in _facts_by_filing(facts).items():
            val = fact.get("val")
            form = fact.get("form", "")
            if val is None:
                continue
            field_values[filed][field] = (val, form)

    for field, concepts in CONCEPT_MAP:
        _absorb(field, concepts)
    for field, concepts in DERIVED_CONCEPTS.items():
        _absorb(field, concepts)

    if not field_values:
        return []

    # Build FundamentalSnapshot per filed-date. Pick the form from the most
    # common form across that filing's fields (in practice they all agree).
    snapshots: list[FundamentalSnapshot] = []
    for filed_str, fields in sorted(field_values.items()):
        # Determine source from the dominant form across reported fields
        forms = [form for (_, form) in fields.values()]
        form = max(set(forms), key=forms.count) if forms else ""
        source = _form_to_source(form)
        if source is None:
            continue

        revenue = fields.get("revenue", (None, ""))[0]
        gross = fields.get("gross_margin", (None, ""))[0]
        net_income = fields.get("net_income", (None, ""))[0]
        equity = fields.get("stockholders_equity", (None, ""))[0]
        assets = fields.get("total_assets", (None, ""))[0]
        long_term_debt = fields.get("total_debt", (None, ""))[0]
        cash = fields.get("total_cash", (None, ""))[0]
        ocf = fields.get("free_cash_flow", (None, ""))[0]
        eps_diluted = fields.get("eps_diluted", (None, ""))[0]

        # Derived: gross_margin %, ROE, ROA, debt_to_equity
        gross_margin_pct: float | None = None
        if gross is not None and revenue not in (None, 0):
            try:
                gross_margin_pct = float(gross) / float(revenue)
            except (TypeError, ZeroDivisionError):
                gross_margin_pct = None
        roe: float | None = None
        if net_income is not None and equity not in (None, 0):
            try:
                roe = float(net_income) / float(equity)
            except (TypeError, ZeroDivisionError):
                roe = None
        roa: float | None = None
        if net_income is not None and assets not in (None, 0):
            try:
                roa = float(net_income) / float(assets)
            except (TypeError, ZeroDivisionError):
                roa = None
        debt_to_equity: float | None = None
        if long_term_debt is not None and equity not in (None, 0):
            try:
                debt_to_equity = float(long_term_debt) / float(equity)
            except (TypeError, ZeroDivisionError):
                debt_to_equity = None

        snapshots.append(
            FundamentalSnapshot(
                ticker=ticker,
                valid_from=_parse_filed(filed_str),
                valid_to=None,  # second pass sets this
                source=source,
                revenue=float(revenue) if revenue is not None else None,
                eps_diluted=float(eps_diluted) if eps_diluted is not None else None,
                gross_margin=gross_margin_pct,
                roe=roe,
                roa=roa,
                debt_to_equity=debt_to_equity,
                free_cash_flow=float(ocf) if ocf is not None else None,
                total_cash=float(cash) if cash is not None else None,
                total_debt=float(long_term_debt) if long_term_debt is not None else None,
            )
        )

    # Second pass: chain valid_to for each snapshot (= next snapshot's valid_from)
    chained: list[FundamentalSnapshot] = []
    for i, snap in enumerate(snapshots):
        if i + 1 < len(snapshots):
            chained.append(snap.model_copy(update={"valid_to": snapshots[i + 1].valid_from}))
        else:
            chained.append(snap)  # most recent: valid_to stays None
    return chained
