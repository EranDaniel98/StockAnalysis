"""Fundamental snapshot — point-in-time aware."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

FundamentalsSource = Literal["yfinance_snapshot", "edgar_10q", "edgar_10k"]
"""Where this snapshot was sourced. PIT validity depends on the source:
- yfinance_snapshot: current-snapshot only (valid_from = fetch time, no history)
- edgar_10q / edgar_10k: PIT-correct, valid_from = filing date"""


class FundamentalSnapshot(BaseModel):
    """A point-in-time fundamentals record for a single ticker.

    Stored with (ticker, valid_from, source) as primary key. valid_to may be
    null on the most recent row; older rows have it set to the valid_from of
    the next snapshot.

    Fields are intentionally narrow — only what the scoring engine actually
    consumes. EDGAR's XBRL has ~20K tags; we map a handful into typed fields.
    """

    model_config = ConfigDict(frozen=True)

    ticker: str
    valid_from: datetime
    valid_to: Optional[datetime] = None
    source: FundamentalsSource

    # --- valuation ---
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    ps_ratio: Optional[float] = None
    ev_to_ebitda: Optional[float] = None

    # --- growth ---
    revenue: Optional[float] = None
    """In reporting currency (USD for US tickers)."""
    revenue_growth_yoy: Optional[float] = None
    earnings_growth_yoy: Optional[float] = None
    eps_diluted: Optional[float] = None

    # --- profitability ---
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    profit_margin: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None

    # --- balance sheet / health ---
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    free_cash_flow: Optional[float] = None
    total_cash: Optional[float] = None
    total_debt: Optional[float] = None

    # --- dividend ---
    dividend_yield: Optional[float] = None
    payout_ratio: Optional[float] = None

    # --- categorical ---
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    name: Optional[str] = None


class FundamentalPanel(BaseModel):
    """A panel of FundamentalSnapshot indexed by ticker. Returned by
    FundamentalsRepository.get_panel() for batch scoring."""

    model_config = ConfigDict(frozen=True)

    as_of: datetime
    snapshots: dict[str, FundamentalSnapshot] = Field(default_factory=dict)
