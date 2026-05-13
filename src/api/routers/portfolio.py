"""Portfolio endpoints.

Read-only views on top of the Alpaca paper account. The Alpaca SDK is sync;
wrap each call in `asyncio.to_thread` so we don't block the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.execution.alpaca import AlpacaClient, AlpacaClientError

logger = logging.getLogger(__name__)
router = APIRouter()


class EquityPoint(BaseModel):
    timestamp: int
    """Epoch seconds. Frontend converts to a Date for display."""
    equity: float
    profit_loss: float
    profit_loss_pct: float | None = None


class PortfolioHistory(BaseModel):
    period: str
    timeframe: str
    base_value: float | None = None
    points: list[EquityPoint] = Field(default_factory=list)


class AccountSummary(BaseModel):
    account_number: str
    status: str
    equity: float
    cash: float
    buying_power: float
    portfolio_value: float
    long_market_value: float
    pattern_day_trader: bool


class Position(BaseModel):
    ticker: str
    shares: float
    avg_price: float
    current_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0


class PortfolioStatus(BaseModel):
    account: AccountSummary
    positions: list[Position]
    n_positions: int = Field(ge=0)


def _build_client() -> AlpacaClient:
    try:
        return AlpacaClient()
    except AlpacaClientError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("", response_model=PortfolioStatus)
async def get_portfolio() -> PortfolioStatus:
    """Live snapshot: account fields + current positions."""
    client = _build_client()
    account = await asyncio.to_thread(client.get_account)
    positions = await asyncio.to_thread(client.get_positions)
    return PortfolioStatus(
        account=AccountSummary(**account),
        positions=[Position(**p) for p in positions],
        n_positions=len(positions),
    )


@router.get("/positions", response_model=list[Position])
async def get_positions() -> list[Position]:
    client = _build_client()
    positions = await asyncio.to_thread(client.get_positions)
    return [Position(**p) for p in positions]


@router.get("/account", response_model=AccountSummary)
async def get_account() -> AccountSummary:
    client = _build_client()
    account = await asyncio.to_thread(client.get_account)
    return AccountSummary(**account)


_PERIOD_VALUES = ("1D", "1W", "1M", "3M", "6M", "1A")
_TIMEFRAME_VALUES = ("1Min", "5Min", "15Min", "1H", "1D")


@router.get("/history", response_model=PortfolioHistory)
async def get_history(
    period: Literal["1D", "1W", "1M", "3M", "6M", "1A"] = Query(default="1M"),
    timeframe: Literal["1Min", "5Min", "15Min", "1H", "1D"] = Query(default="1D"),
) -> PortfolioHistory:
    """Equity curve from Alpaca's portfolio history.

    ``period`` is Alpaca's window shorthand (1D / 1W / 1M / 3M / 6M / 1A).
    ``timeframe`` is the bar size; intraday timeframes are silently
    downgraded to 1D for windows > 1W (Alpaca rejects them otherwise).
    """
    client = _build_client()
    raw = await asyncio.to_thread(client.get_portfolio_history, period, timeframe)
    points = [
        EquityPoint(
            timestamp=ts,
            equity=eq,
            profit_loss=pl,
            profit_loss_pct=plp,
        )
        for ts, eq, pl, plp in zip(
            raw["timestamps"],
            raw["equity"],
            raw["profit_loss"],
            raw["profit_loss_pct"],
        )
    ]
    return PortfolioHistory(
        period=raw["period"],
        timeframe=raw["timeframe"],
        base_value=raw["base_value"],
        points=points,
    )
