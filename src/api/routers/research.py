"""/api/research -- read-only views over local research forward-paper books.

These are the virtual momentum books from
scripts/research/trend_forward_paper.py (the default broad book and its
--book <name> variants, e.g. the AI book). Each persists state to
reports/trend_forward_paper_<book>_state.json (the default book has no
suffix). This router reads that JSON and projects it for the UI. It never
writes and never touches Alpaca -- these books are deliberately isolated
from the live shipped-config validation run.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.api.schemas.research import (
    ForwardBookHolding,
    ForwardBookMark,
    ForwardBookResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()

REPORTS_DIR = Path("reports")

# How many recent mark-to-market rows to return for the vs-SPY sparkline.
# The book marks once per trading day; a quarter is ~63 rows.
_HISTORY_TAIL = 180

_RISK_NOTE = (
    "~2x-beta bull bet; backtested -38% max drawdown; downside protection "
    "UNTESTED (the trend never broke in-sample). Local paper only, no "
    "broker. This forward run exists to watch exactly that downside."
)


def _state_path(book: str) -> Path:
    """default book → trend_forward_paper_state.json; named book →
    trend_forward_paper_<book>_state.json. Matches the CLI's STATE_PATH."""
    suffix = "" if book == "default" else f"_{book}"
    return REPORTS_DIR / f"trend_forward_paper{suffix}_state.json"


def _coerce_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # drop NaN


def _build_holdings(state: dict) -> list[ForwardBookHolding]:
    holdings: dict = state.get("holdings", {})
    if not holdings:
        return []
    # Book equity for weight %: cash + mark of every holding.
    equity = float(state.get("cash", 0.0))
    marks: dict[str, float] = {}
    for t, h in holdings.items():
        last = _coerce_float(h.get("last_px")) or _coerce_float(h.get("entry_px")) or 0.0
        marks[t] = last
        equity += float(h.get("shares", 0.0)) * last

    out: list[ForwardBookHolding] = []
    for t, h in holdings.items():
        entry = _coerce_float(h.get("entry_px"))
        last = marks[t]
        since = ((last / entry - 1.0) * 100.0) if entry else None
        mtm = float(h.get("shares", 0.0)) * last
        weight = (mtm / equity * 100.0) if equity > 0 else None
        out.append(ForwardBookHolding(
            ticker=t,
            mom_rank=h.get("mom_rank"),
            mom_raw=_coerce_float(h.get("mom_raw")),
            mom_z=_coerce_float(h.get("mom_z")),
            entry_px=entry or 0.0,
            last_px=last,
            entry_date=h.get("entry_date"),
            since_entry_pct=round(since, 2) if since is not None else None,
            weight_pct=round(weight, 2) if weight is not None else None,
        ))
    # Selection order: by momentum rank (the sole criterion), unranked last.
    out.sort(key=lambda h: h.mom_rank if h.mom_rank is not None else 10**9)
    return out


@router.get("/{book}", response_model=ForwardBookResponse)
def get_forward_book(book: str) -> ForwardBookResponse:
    """Read one forward-paper book's state. ``book`` is the --book name
    (use 'default' for the original suffix-less broad book)."""
    path = _state_path(book)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No forward book '{book}' (expected {path.name}). "
                   "Initialize it with scripts.research.trend_forward_paper.",
        )
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to read {path.name}: {e}",
        )

    params = state.get("params", {})
    history = state.get("history", []) or []
    last = history[-1] if history else {}
    marks = [
        ForwardBookMark(
            date=row["date"],
            equity=float(row.get("equity", 0.0)),
            ret_pct=_coerce_float(row.get("ret_pct")),
            spy_ret_pct=_coerce_float(row.get("spy_ret_pct")),
            excess_vs_spy_pct=_coerce_float(row.get("excess_vs_spy_pct")),
        )
        for row in history[-_HISTORY_TAIL:]
    ]

    return ForwardBookResponse(
        book=state.get("book", book),
        strategy=state.get("strategy", "trend12_1_broad_top20_hold"),
        universe_file=Path(state.get("universe_file", "")).name,
        universe_n=int(state.get("universe_n", 0)),
        top_n=int(params.get("top_n", 0)),
        rebalance_days=int(params.get("rebalance_days", 0)),
        cost_bps=float(params.get("cost_bps", 0.0)),
        start_date=state.get("start_date", ""),
        baseline_equity=float(state.get("baseline_equity", 0.0)),
        last_rebalance=state.get("last_rebalance"),
        last_marked=state.get("last_marked"),
        equity=float(last.get("equity", state.get("baseline_equity", 0.0))),
        cash=float(state.get("cash", 0.0)),
        ret_pct=_coerce_float(last.get("ret_pct")),
        spy_ret_pct=_coerce_float(last.get("spy_ret_pct")),
        excess_vs_spy_pct=_coerce_float(last.get("excess_vs_spy_pct")),
        n_holdings=len(state.get("holdings", {})),
        holdings=_build_holdings(state),
        history=marks,
        risk_note=_RISK_NOTE,
    )
