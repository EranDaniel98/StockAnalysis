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
from datetime import date, datetime, timezone
from typing import Any

from src.contracts.entities.fundamentals import FundamentalSnapshot, FundamentalsSource
from src.market_data.edgar.concept_map import (
    CONCEPT_MAP,
    DERIVED_CONCEPTS,
    EXPECTED_UNIT_BY_FIELD,
)

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


def _duration_days(fact: dict[str, Any]) -> int | None:
    """Span of a duration fact in days, or None for instant (balance-sheet)
    facts, which carry only ``end``."""
    start, end = fact.get("start"), fact.get("end")
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except (ValueError, TypeError):
        return None


def _period_ok(fact: dict[str, Any]) -> bool:
    """Accept instants (no duration) and the single duration matching the
    fact's form — one quarter for a 10-Q, one year for a 10-K. Rejects the
    year-to-date rows a 10-Q double-reports under the same concept+filing,
    which is what made eps_diluted (summed into a TTM) ambiguous."""
    d = _duration_days(fact)
    if d is None:
        return True  # instant concept — no period ambiguity
    if _form_to_source(fact.get("form", "")) == "edgar_10k":
        return 350 <= d <= 380
    return 80 <= d <= 100  # one fiscal quarter


def _pick_concept_facts(
    us_gaap: dict[str, Any], concepts: list[str], *,
    expected_unit: str = "USD",
) -> list[dict[str, Any]]:
    """Merge facts across all matching concepts in priority order.

    Companies change tagging conventions across filing eras (e.g. AAPL
    used SalesRevenueNet pre-2019, then switched to
    RevenueFromContractWithCustomerExcludingAssessedTax under ASC 606).
    Both need to contribute to the merged timeline, so we walk EVERY
    concept in the list, dedupe by `filed` date with higher-priority
    concepts winning ties.

    Tier-2 #14: ``expected_unit`` pins which XBRL unit bucket we may
    read. Pre-fix this function did
    ``units.get("USD") or units.get("USD/shares") or units.get("shares")``
    which silently accepted the first non-empty bucket. For EPS that
    meant a filer whose USD/shares bucket was empty (rare but real)
    would have its raw share count read as EPS — producing a nonsense
    "diluted EPS = 1,000,000,000" row in the fundamentals timeline.
    Now the function reads ONLY the expected bucket; if it's empty,
    the field stays None (honest "no data").
    """
    # filed -> (fact, concept_prio, end). Per filing keep the fact whose
    # period END is latest — the filing's own reporting period, not a
    # prior-year comparative carried in the same filing — breaking ties by
    # concept priority. _period_ok first drops the YTD/annual durations a
    # 10-Q double-reports, which otherwise corrupted eps_diluted (audit fix).
    best: dict[str, tuple[dict[str, Any], int, str]] = {}
    for prio, c in enumerate(concepts):
        block = us_gaap.get(c)
        if not block:
            continue
        units = block.get("units", {})
        bucket = units.get(expected_unit) or []
        if not bucket and units:
            # Diagnostic: an unexpected unit bucket is present but the
            # expected one isn't. Pre-fix we'd have grabbed the wrong
            # bucket; now we just skip. Debug-level — operators chasing
            # missing data can grep for this.
            logger.debug(
                "EDGAR concept %s has units %s but expected '%s' — skipped",
                c, list(units.keys()), expected_unit,
            )
        for fact in bucket:
            filed = fact.get("filed")
            if not filed or not _period_ok(fact):
                continue
            end = fact.get("end", "")
            cur = best.get(filed)
            if cur is None or end > cur[2] or (end == cur[2] and prio < cur[1]):
                best[filed] = (fact, prio, end)
    return [v[0] for v in best.values()]


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
        expected_unit = EXPECTED_UNIT_BY_FIELD.get(field, "USD")
        facts = _pick_concept_facts(us_gaap, concepts, expected_unit=expected_unit)
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
    n_derived_eps = 0
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
        long_term_debt = fields.get("long_term_debt", (None, ""))[0]
        current_debt = fields.get("current_debt", (None, ""))[0]
        cash = fields.get("total_cash", (None, ""))[0]
        ocf = fields.get("operating_cash_flow", (None, ""))[0]
        capex = fields.get("capex", (None, ""))[0]
        eps_diluted = fields.get("eps_diluted", (None, ""))[0]
        # Derive EPS when the filer doesn't tag it directly (e.g. HSY stopped
        # tagging EarningsPerShareDiluted after 2010). net_income and the share
        # count for THIS filing's period both pass _period_ok, so for a 10-Q
        # this yields a discrete-quarter EPS and for a 10-K an annual EPS — the
        # exact granularity compute_eps_ttm's roll expects. Approximate: the
        # share count drifts with buybacks across the TTM terms, and period-end
        # shares are a proxy when weighted-average-diluted isn't tagged.
        diluted_shares = fields.get("diluted_shares", (None, ""))[0]
        if eps_diluted is None and net_income is not None and diluted_shares:
            try:
                shares = float(diluted_shares)
                if shares > 0:
                    eps_diluted = float(net_income) / shares
                    n_derived_eps += 1
            except (TypeError, ValueError):
                pass
        operating_income = fields.get("operating_income", (None, ""))[0]
        current_assets = fields.get("current_assets", (None, ""))[0]
        current_liabilities = fields.get("current_liabilities", (None, ""))[0]

        # Tier-1 audit #9: total_debt sums LT + current when at least one is
        # present. None means "we genuinely don't know"; previously a filer
        # who only reported DebtCurrent had that under-reported value
        # emitted as total_debt.
        total_debt = _sum_optional_components(long_term_debt, current_debt)

        # Tier-1 audit #9: free_cash_flow = OCF - CapEx when capex is known.
        # When capex is missing we fall back to OCF as a proxy but log a
        # warning so the downstream analyzer's "FCF > 0" branch doesn't
        # silently include CapEx-heavy filers as cash-generative.
        free_cash_flow = _compute_fcf(ocf, capex, ticker=ticker, filed=filed_str)

        # Derived ratios — each guards on a non-zero divisor to avoid blowing up on
        # filings where the numerator is reported but the divisor is missing/zero.
        gross_margin_pct = _safe_ratio(gross, revenue)
        profit_margin_pct = _safe_ratio(net_income, revenue)
        operating_margin_pct = _safe_ratio(operating_income, revenue)
        roe = _safe_ratio(net_income, equity)
        roa = _safe_ratio(net_income, assets)
        debt_to_equity = _safe_ratio(total_debt, equity)
        current_ratio = _safe_ratio(current_assets, current_liabilities)

        snapshots.append(
            FundamentalSnapshot(
                ticker=ticker,
                valid_from=_parse_filed(filed_str),
                valid_to=None,  # second pass sets this
                source=source,
                revenue=float(revenue) if revenue is not None else None,
                eps_diluted=float(eps_diluted) if eps_diluted is not None else None,
                gross_margin=gross_margin_pct,
                operating_margin=operating_margin_pct,
                profit_margin=profit_margin_pct,
                roe=roe,
                roa=roa,
                debt_to_equity=debt_to_equity,
                current_ratio=current_ratio,
                free_cash_flow=free_cash_flow,
                total_cash=float(cash) if cash is not None else None,
                total_debt=total_debt,
            )
        )

    if n_derived_eps:
        logger.info(
            "%s: derived eps_diluted = net_income/shares for %d filing(s) "
            "lacking a direct EPS tag", ticker, n_derived_eps,
        )

    # Sort once by filing date so chain + YoY passes can rely on temporal order.
    snapshots.sort(key=lambda s: s.valid_from)

    # Second pass: chain valid_to + compute YoY growth fields.
    #
    # YoY: for each snapshot we look ~365d back (window 300-430d to absorb
    # quarter-shift drift around filings that move a few weeks between years).
    # When we find a matching prior-year snapshot with non-zero revenue/net
    # income, we compute the percentage delta. Quarterly filings (10-Q) match
    # to prior 10-Q; annuals (10-K) match to prior 10-K. Same-source matching
    # avoids comparing TTM to a quarter.
    chained: list[FundamentalSnapshot] = []
    for i, snap in enumerate(snapshots):
        updates: dict[str, object] = {}
        if i + 1 < len(snapshots):
            updates["valid_to"] = snapshots[i + 1].valid_from
        rev_yoy, eps_yoy = _compute_yoy(snap, snapshots[:i])
        if rev_yoy is not None:
            updates["revenue_growth_yoy"] = rev_yoy
        if eps_yoy is not None:
            updates["earnings_growth_yoy"] = eps_yoy
        chained.append(snap.model_copy(update=updates) if updates else snap)
    return chained


def _safe_ratio(num: object, denom: object) -> float | None:
    if num is None or denom in (None, 0):
        return None
    try:
        return float(num) / float(denom)
    except (TypeError, ZeroDivisionError):
        return None


def _sum_optional_components(*values: object) -> float | None:
    """Sum components that may be None. Returns None only when EVERY
    component is None (i.e. nothing was reported); a single non-None
    value yields itself. Used by total_debt = LT + current_debt where a
    bank/REIT may report only one side (Tier-1 audit #9 / D#5)."""
    floats: list[float] = []
    for v in values:
        if v is None:
            continue
        try:
            floats.append(float(v))
        except (TypeError, ValueError):
            continue
    if not floats:
        return None
    return sum(floats)


def _compute_fcf(
    ocf: object, capex: object, *, ticker: str = "", filed: str = ""
) -> float | None:
    """True free cash flow = OCF - CapEx.

    CapEx is reported as a positive cash outflow on the EDGAR statement
    of cash flows (the negative sign is implicit — paying for assets is
    a cash outflow). We subtract it from OCF to yield FCF: positive
    means cash generated after reinvestment.

    Falls back to OCF as a proxy when capex is missing, with a logged
    warning so the downstream analyzer's "FCF > 0" path doesn't silently
    misclassify CapEx-heavy filers. Tier-1 audit #9 / D#6.
    """
    if ocf is None:
        return None
    try:
        ocf_f = float(ocf)
    except (TypeError, ValueError):
        return None
    if capex is None:
        logger.warning(
            "CapEx missing for %s (filed %s); falling back to OCF as FCF proxy",
            ticker, filed,
        )
        return ocf_f
    try:
        capex_f = float(capex)
    except (TypeError, ValueError):
        logger.warning(
            "CapEx unparseable for %s (filed %s): %r; falling back to OCF",
            ticker, filed, capex,
        )
        return ocf_f
    # CapEx on the cash-flow statement: EDGAR conventionally reports the
    # outflow as a POSITIVE number (the negative sign is implicit in the
    # statement section). Subtract to get FCF. Some filers report capex
    # as negative — accept both signs by taking the absolute value, since
    # FCF should never count capex as a cash inflow.
    return ocf_f - abs(capex_f)


def _compute_yoy(
    current: FundamentalSnapshot, prior: list[FundamentalSnapshot]
) -> tuple[float | None, float | None]:
    """Match `current` to a same-source filing roughly 365d earlier and return
    (revenue_growth_yoy, earnings_growth_yoy). Returns (None, None) when no
    suitable prior-year row exists."""
    if not prior:
        return None, None
    target_delta_days = 365
    window_lo, window_hi = 300, 430
    same_source = [
        p for p in prior
        if p.source == current.source
        and window_lo <= (current.valid_from - p.valid_from).days <= window_hi
    ]
    if not same_source:
        return None, None
    # Pick the row closest to exactly 365 days back.
    prior_row = min(
        same_source,
        key=lambda p: abs((current.valid_from - p.valid_from).days - target_delta_days),
    )
    rev_yoy = _pct_change(current.revenue, prior_row.revenue)
    eps_yoy = _pct_change(current.eps_diluted, prior_row.eps_diluted)
    return rev_yoy, eps_yoy


def _pct_change(current: float | None, prior: float | None) -> float | None:
    """Percentage change as a decimal (0.10 = +10%). Returns None when prior
    is zero or sign-flips (cannot interpret as growth)."""
    if current is None or prior is None or prior == 0:
        return None
    if (current >= 0) != (prior >= 0):
        # Sign flip — yoy growth is ambiguous (from loss to profit or vice versa)
        return None
    return (current - prior) / abs(prior)
