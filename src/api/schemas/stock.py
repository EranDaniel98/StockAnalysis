"""Schemas for the /api/stocks per-ticker deep-dive endpoint.

A "stock detail" composes:
  - the most recent ScanResultItem this ticker appeared in (the trade plan
    + breakdown the engine produced),
  - which scan run that came from (strategy, when),
  - a short OHLCV history for charting entry/stop/target overlays.

The ScanResultItem schema is reused as-is — the page wants exactly the
same fields the engine emits, so there's no narrowing here.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from src.api.schemas.scan import ScanResultItem


class OHLCBar(BaseModel):
    """One trading day for the chart. Volume is optional — most chart
    libraries don't need it for the entry/stop/target overlay view."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None


class StockDetail(BaseModel):
    ticker: str
    latest_recommendation: ScanResultItem | None = Field(
        default=None,
        description=(
            "Engine's most recent recommendation row for this ticker, or "
            "null if it has never appeared in a stored scan_run."
        ),
    )
    scan_run_id: str | None = None
    scan_strategy: str | None = None
    scan_timestamp: datetime | None = None
    history: list[OHLCBar] = Field(
        default_factory=list,
        description=(
            "Recent OHLC bars for charting. Window is controlled by the "
            "endpoint's `history_days` query param (default 120)."
        ),
    )
