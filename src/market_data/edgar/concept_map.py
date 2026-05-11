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
    (
        "total_debt",
        [
            "LongTermDebt",
            "LongTermDebtNoncurrent",
            "DebtCurrent",  # combine with LongTermDebt at parser level
        ],
    ),
    # --- cash flow ---
    ("free_cash_flow", ["NetCashProvidedByOperatingActivities"]),
    # FCF strictly = OCF - CapEx, but EDGAR's CapEx concept varies more
    # widely than OCF. Phase 0 uses OCF as a proxy; Phase 4 can refine.
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
}
