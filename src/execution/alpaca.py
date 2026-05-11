"""
Alpaca paper-trading client wrapper.
Thin layer over alpaca-py that always uses paper=True and surfaces the
operations the scanner needs: account info, positions, bracket orders,
and order history for reconciliation.
"""

import os
import logging
from datetime import datetime, timezone, timedelta

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, OrderClass, TimeInForce, QueryOrderStatus

logger = logging.getLogger(__name__)


class AlpacaClientError(Exception):
    pass


class AlpacaClient:
    """Paper-only Alpaca trading client."""

    def __init__(self, api_key=None, api_secret=None):
        api_key = api_key or os.getenv("ALPACA_API_KEY")
        api_secret = api_secret or os.getenv("ALPACA_API_SECRET")
        if not api_key or not api_secret:
            raise AlpacaClientError(
                "ALPACA_API_KEY and ALPACA_API_SECRET must be set in .env "
                "(get them from https://app.alpaca.markets/paper/dashboard/overview)"
            )
        self._client = TradingClient(api_key, api_secret, paper=True)

    # -- Account ---------------------------------------------------------

    def get_account(self):
        """Return account dict with the fields we care about."""
        a = self._client.get_account()
        return {
            "account_number": a.account_number,
            "status": str(a.status),
            "equity": float(a.equity),
            "cash": float(a.cash),
            "buying_power": float(a.buying_power),
            "portfolio_value": float(a.portfolio_value),
            "long_market_value": float(a.long_market_value or 0),
            "pattern_day_trader": bool(a.pattern_day_trader),
        }

    # -- Positions -------------------------------------------------------

    def get_positions(self):
        """Return list of dicts mirroring portfolio.yaml holdings format."""
        positions = self._client.get_all_positions()
        out = []
        for p in positions:
            out.append({
                "ticker": p.symbol,
                "shares": float(p.qty),
                "avg_price": float(p.avg_entry_price),
                "current_price": float(p.current_price) if p.current_price else None,
                "market_value": float(p.market_value) if p.market_value else None,
                "unrealized_pnl": float(p.unrealized_pl) if p.unrealized_pl else 0.0,
                "unrealized_pnl_pct": float(p.unrealized_plpc) * 100 if p.unrealized_plpc else 0.0,
            })
        return out

    # -- Orders ----------------------------------------------------------

    def submit_bracket_order(self, ticker, qty, take_profit_price, stop_loss_price, side="buy"):
        """
        Submit a bracket market order. Returns the parent order ID.

        Bracket orders on Alpaca require whole-share qty (no fractional).
        Caller should int() qty before passing.
        """
        if qty < 1:
            raise AlpacaClientError(
                f"Bracket orders require qty >= 1 whole share (got {qty} for {ticker})"
            )
        req = MarketOrderRequest(
            symbol=ticker,
            qty=int(qty),
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(take_profit_price, 2)),
            stop_loss=StopLossRequest(stop_price=round(stop_loss_price, 2)),
        )
        order = self._client.submit_order(req)
        return {
            "order_id": str(order.id),
            "client_order_id": order.client_order_id,
            "status": str(order.status),
            "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
            "qty": int(qty),
            "ticker": ticker,
            "take_profit": round(take_profit_price, 2),
            "stop_loss": round(stop_loss_price, 2),
        }

    def submit_market_order(self, ticker, qty, side="buy"):
        """Plain market order — used for fractional close-outs and SELL recommendations."""
        req = MarketOrderRequest(
            symbol=ticker,
            qty=qty,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = self._client.submit_order(req)
        return {
            "order_id": str(order.id),
            "status": str(order.status),
            "qty": qty,
            "ticker": ticker,
        }

    def get_orders(self, status="all", after=None, limit=500):
        """
        Fetch orders. status: 'open', 'closed', 'all'.
        after: datetime to filter from (e.g. last 30 days).
        """
        status_map = {
            "open": QueryOrderStatus.OPEN,
            "closed": QueryOrderStatus.CLOSED,
            "all": QueryOrderStatus.ALL,
        }
        req = GetOrdersRequest(
            status=status_map.get(status, QueryOrderStatus.ALL),
            after=after,
            limit=limit,
        )
        orders = self._client.get_orders(filter=req)
        out = []
        for o in orders:
            out.append({
                "order_id": str(o.id),
                "client_order_id": o.client_order_id,
                "ticker": o.symbol,
                "qty": float(o.qty) if o.qty else 0,
                "filled_qty": float(o.filled_qty) if o.filled_qty else 0,
                "filled_price": float(o.filled_avg_price) if o.filled_avg_price else None,
                "side": str(o.side),
                "status": str(o.status),
                "order_class": str(o.order_class) if o.order_class else None,
                "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
                "filled_at": o.filled_at.isoformat() if o.filled_at else None,
                "legs": [str(leg.id) for leg in (o.legs or [])],
            })
        return out

    def get_closed_orders_since(self, days=90):
        after = datetime.now(timezone.utc) - timedelta(days=days)
        return self.get_orders(status="closed", after=after)

    def get_clock(self):
        clock = self._client.get_clock()
        return {
            "is_open": bool(clock.is_open),
            "next_open": clock.next_open.isoformat() if clock.next_open else None,
            "next_close": clock.next_close.isoformat() if clock.next_close else None,
        }
