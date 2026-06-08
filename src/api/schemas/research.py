"""Schemas for /api/research -- local research forward-paper books.

These books (trend_forward_paper, and its --book variants like the AI
book) are LOCAL virtual books marked to live Polygon prices, fully
isolated from the live Alpaca shipped-config run. The API surfaces their
on-disk state files read-only so the UI can show holdings + vs-SPY track
without touching the broker.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ForwardBookHolding(BaseModel):
    """One equal-weight position in a momentum forward book. 'why' is the
    12-1 momentum rank -- the sole selection criterion (no fundamentals)."""
    ticker: str
    mom_rank: Optional[int] = None       # 1 = strongest 12-1 momentum
    mom_raw: Optional[float] = None       # trailing skip-1m return (1.0 = +100%)
    mom_z: Optional[float] = None
    entry_px: float
    last_px: float
    entry_date: Optional[str] = None
    since_entry_pct: Optional[float] = None  # last/entry - 1, in %
    weight_pct: Optional[float] = None       # mtm weight of book equity


class ForwardBookMark(BaseModel):
    """One daily mark-to-market row of the book vs SPY."""
    date: str
    equity: float
    ret_pct: Optional[float] = None
    spy_ret_pct: Optional[float] = None
    excess_vs_spy_pct: Optional[float] = None


class ForwardBookResponse(BaseModel):
    """A research forward-paper book's full read-only state."""
    book: str                      # "ai", "default", ...
    strategy: str
    universe_file: str
    universe_n: int
    top_n: int
    rebalance_days: int
    cost_bps: float
    start_date: str
    baseline_equity: float
    last_rebalance: Optional[str] = None
    last_marked: Optional[str] = None

    equity: float
    cash: float
    ret_pct: Optional[float] = None
    spy_ret_pct: Optional[float] = None
    excess_vs_spy_pct: Optional[float] = None

    n_holdings: int = Field(ge=0)
    holdings: list[ForwardBookHolding]
    history: list[ForwardBookMark]

    # The standing risk caveat baked into the CLI status print -- surfaced
    # so the UI shows it next to every number, not buried in a runbook.
    risk_note: str


class MomvalPick(BaseModel):
    """One name in the momentum-value (biggest-risers) book, with the
    EDGAR fundamentals + trailing return + grounded AI 'why' that justify it."""
    rank: Optional[int] = None
    ticker: str
    name: Optional[str] = None
    composite_z: Optional[float] = None
    mom_rank: Optional[int] = None
    val_rank: Optional[int] = None
    sector: Optional[str] = None
    # The grounded 'why to buy' so the book is not acted on blindly.
    why: Optional[str] = None
    trailing_12_1: Optional[float] = None
    # EDGAR point-in-time fundamentals (price-derived ratios are absent —
    # EDGAR carries no price). Fractions (0.31 = +31%), not percents.
    revenue_growth_yoy: Optional[float] = None
    earnings_growth_yoy: Optional[float] = None
    profit_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    debt_to_equity: Optional[float] = None
    dividend_yield: Optional[float] = None
    free_cash_flow: Optional[float] = None


class MomvalPicksResponse(BaseModel):
    """Daily picks of the momentum-value 'biggest-risers' book (read-only)."""
    strategy: str
    label: str
    as_of: str
    weights: dict[str, float]
    factors_used: list[str]
    universe_size: int
    top_n: int = Field(ge=0)
    horizon_note: str
    ai_model: Optional[str] = None
    picks: list[MomvalPick]
    generated_at: str
