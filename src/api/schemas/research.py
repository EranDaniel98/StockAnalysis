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
