"""Portfolio endpoints.

Read-only views on top of the Alpaca paper account. The Alpaca SDK is sync;
wrap each call in `asyncio.to_thread` so we don't block the event loop.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.execution.alpaca import AlpacaClient, AlpacaClientError

logger = logging.getLogger(__name__)
router = APIRouter()


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
