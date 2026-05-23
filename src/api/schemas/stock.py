"""Schemas for the /api/stocks per-ticker endpoint.

After the factor-pipeline migration the endpoint only returns OHLC bars —
the FE's stock detail page reads recommendation context from the factor
``basketItem`` instead of an inline ``ScanResultItem`` envelope.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


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
    history: list[OHLCBar] = Field(
        default_factory=list,
        description=(
            "Recent OHLC bars for charting. Window is controlled by the "
            "endpoint's `history_days` query param (default 120)."
        ),
    )
