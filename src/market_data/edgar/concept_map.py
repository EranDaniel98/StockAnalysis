"""XBRL concept → FundamentalSnapshot field map.

Companies tag the same metric differently across filings (us-gaap:Revenues
vs us-gaap:SalesRevenueNet vs RevenueFromContractWithCustomerExcludingAssessedTax),
so we try multiple concept names per field and take the first one that has
data. This list is seeded from the most-common us-gaap tags and will need
curation as we add more tickers.

Tier-2 audit #14: EXPECTED_UNIT_BY_FIELD pins which XBRL unit bucket
the parser may read for each field. Pre-fix the parser did
``units.get("USD") or units.get("USD/shares") or units.get("shares")``
which silently accepted any non-empty bucket. For EPS that meant a
filer whose USD/shares bucket was empty would have its raw share-count
read as EPS — producing a "diluted EPS = 1,000,000,000" row in the
fundamentals timeline. Per-field expected unit makes the parser refuse
the wrong bucket.
"""

from __future__ import annotations

# Each entry: (FundamentalSnapshot field name, [list of us-gaap concepts to try in order])
# Order matters: parser stops at the first concept that yields data.

CONCEPT_MAP: list[tuple[str, list[str]]] = [
    # --- top-line ---
    (
        "revenue",
        [
            "Revenues",
            "SalesRevenueNet",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            # Banks: true bank top-line netted of interest expense.
            # Coverage-pass fallback so BK/MS/NTRS/L get a revenue
            # number and downstream margin ratios are computable.
            "RevenuesNetOfInterestExpense",
            # Utilities (AES + co.)
            "RegulatedAndUnregulatedOperatingRevenue",
            "ElectricUtilityRevenue",
            # Oil & gas (parts of XOM/OXY etc.)
            "OilAndGasRevenue",
        ],
    ),
    # --- profitability ---
    ("gross_margin", ["GrossProfit"]),  # need revenue to compute margin
    # net income drives earnings_growth_yoy
    # REG / many REITs report EPS only under the continuing-ops tag, not
    # EarningsPerShareDiluted. The first match wins (in reversed-priority
    # walk), so EarningsPerShareDiluted still preempts the REIT fallback
    # when both are present (modern filers).
    (
        "eps_diluted",
        [
            "EarningsPerShareDiluted",
            "IncomeLossFromContinuingOperationsPerDilutedShare",
        ],
    ),
    # --- balance sheet ---
    ("total_cash", ["CashAndCashEquivalentsAtCarryingValue", "Cash"]),
    # Tier-1 audit #9 (D#5): `total_debt` used to include `DebtCurrent` in
    # the candidate list and let first-match win. A filer reporting only
    # `DebtCurrent` had that value emitted as total_debt — under-reporting
    # by an order of magnitude. Now the slot only accepts long-term debt
    # tags; the parser sums in `current_debt` (below) when reported, so
    # banks/REITs/etc. that disclose only short-term debt produce
    # total_debt=None (honest "we don't know") instead of a wrong number.
    (
        "long_term_debt",
        [
            "LongTermDebt",
            "LongTermDebtNoncurrent",
            # Capital-lease-inclusive aggregate used by DOW, APA, L.
            "LongTermDebtAndCapitalLeaseObligations",
            "LongTermBorrowings",
        ],
    ),
]


# Helper concepts we extract for downstream derived calculations but don't
# map directly to a FundamentalSnapshot field. The parser surfaces them in
# the same intermediate dict.
DERIVED_CONCEPTS: dict[str, list[str]] = {
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "stockholders_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "total_assets": ["Assets"],
    "operating_income": [
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeInterestExpenseInterestIncomeIncomeTaxesExtraordinaryItemsNoncontrollingInterestsNet",
        # Bank / financials surrogate: pre-tax continuing-ops income.
        # Not a pure operating measure (it includes interest income),
        # but it gives a comparable profitability signal for filers
        # (MS, BK, NTRS, L) that don't tag OperatingIncomeLoss at all.
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    # Tier-1 audit #9 (D#5): summed into total_debt at the parser level.
    "current_debt": [
        "DebtCurrent",
        "LongTermDebtCurrent",
        "ShortTermBorrowings",
    ],
    # Tier-1 audit #9 (D#6): operating cash flow is what EDGAR reports
    # directly. Used to be slotted under `free_cash_flow` which lied —
    # downstream analyzers scored stocks as "FCF-positive" when they were
    # actually OCF-positive but CapEx-heavy. Parser now subtracts capex
    # (below) so the FundamentalSnapshot.free_cash_flow column is TRUE
    # FCF when capex is available, falling back to OCF as a proxy with
    # a logged warning when capex is absent.
    # The "UsedIn" variant is the dominant tag in modern XBRL filings
    # (AAPL, MSFT, and the majority of S&P 500 names). Listing it FIRST
    # is what gives us FCF coverage at all — pre-fix the slot only had
    # `NetCashProvidedByOperatingActivities` and FCF was 0% universe-wide.
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    # Capital expenditures. EDGAR reports as a positive cash outflow;
    # subtract from OCF (positive number) to get FCF (positive = cash
    # generated AFTER reinvestment). Two common tags cover ~all filers.
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
}


# Tier-2 #14: which XBRL unit bucket the parser may read per field.
# A field missing from this map defaults to "USD" (most common). Any
# field listed here REQUIRES the named bucket — facts in other buckets
# are skipped with a debug log, NOT silently re-typed.
EXPECTED_UNIT_BY_FIELD: dict[str, str] = {
    # EPS is per-share, so the unit is USD per share.
    "eps_diluted": "USD/shares",
    # All other fields in CONCEPT_MAP + DERIVED_CONCEPTS are USD-denominated
    # quantities (revenue, debt, cash flow, equity, ...). Default applies.
}
