"""XBRL concept → FundamentalSnapshot field map.

Companies tag the same metric differently across filings (us-gaap:Revenues
vs us-gaap:SalesRevenueNet vs RevenueFromContractWithCustomerExcludingAssessedTax),
so we try multiple concept names per field and take the first one that has
data. This list is seeded from the most-common us-gaap tags and will need
curation as we add more tickers.

The unit fields ("USD", "USD/shares", "pure") tell the parser how to
interpret the value. EDGAR returns multiple unit groups per concept; we
prefer USD over USD/shares over pure.
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
        ],
    ),
    # --- profitability ---
    ("gross_margin", ["GrossProfit"]),  # need revenue to compute margin
    # net income drives earnings_growth_yoy
    ("eps_diluted", ["EarningsPerShareDiluted"]),
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
    "operating_cash_flow": ["NetCashProvidedByOperatingActivities"],
    # Capital expenditures. EDGAR reports as a positive cash outflow;
    # subtract from OCF (positive number) to get FCF (positive = cash
    # generated AFTER reinvestment). Two common tags cover ~all filers.
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
}
