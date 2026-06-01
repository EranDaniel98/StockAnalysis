"""
Alpaca paper-trading client wrapper.
Thin layer over alpaca-py that always uses paper=True and surfaces the
operations the scanner needs: account info, positions, bracket orders,
and order history for reconciliation.
"""

import os
import logging
from datetime import datetime, timezone, timedelta, date

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
    GetOrdersRequest,
    GetPortfolioHistoryRequest,
)
from alpaca.trading.enums import OrderSide, OrderClass, TimeInForce, QueryOrderStatus

from src.execution.safety_gates import (
    SessionState,
    TradingHaltedError,
    TradingSafetyGate,
)

logger = logging.getLogger(__name__)

# Alpaca client_order_id constraints:
#   - max 128 chars
#   - charset is permissive; alphanumerics + `-_.` are universally accepted
#   - duplicate-detection window is ~24h across open and recent orders
_COID_MAX_LEN = 128


class AlpacaClientError(Exception):
    pass


class AlpacaDuplicateOrderError(AlpacaClientError):
    """Raised when Alpaca rejects a submission because client_order_id is
    already in use. Idempotent retry path: caller should treat as 'already
    submitted' rather than re-attempting with a new id."""


def make_client_order_id(
    strategy: str, ticker: str, as_of: date | None = None,
    *, retry_suffix: str = "",
) -> str:
    """Build the deterministic client_order_id used for idempotent submits.

    Same (strategy, ticker, date) -> same id, so a sweep re-run or RPC
    retry within the day collides on Alpaca's duplicate-id check and is
    rejected rather than double-filling. If we ever need to allow same-day
    re-entry (e.g. after a stop-out OR after flatten+rebuild), pass an
    explicit ``retry_suffix`` to make the coid unique.

    Alpaca remembers client_order_ids forever (even across cancelled
    orders), so after a flatten_paper run the same-day re-submission
    MUST pass a retry_suffix or all entries are rejected as dupes.
    """
    if as_of is None:
        as_of = datetime.now(timezone.utc).date()
    suffix = f"-{retry_suffix}" if retry_suffix else ""
    coid = f"sn-{strategy}-{ticker}-{as_of.isoformat()}{suffix}"
    if len(coid) > _COID_MAX_LEN:
        # Truncate strategy first to preserve ticker + date which carry the
        # uniqueness signal we care about.
        budget = _COID_MAX_LEN - len(f"sn--{ticker}-{as_of.isoformat()}{suffix}")
        coid = f"sn-{strategy[:budget]}-{ticker}-{as_of.isoformat()}{suffix}"
    return coid


def _is_duplicate_coid_error(err: APIError) -> bool:
    """Best-effort detection of duplicate client_order_id rejection.

    Alpaca returns 422 with a message that mentions 'client_order_id' on
    duplicate; older endpoints have used 409. Match both rather than rely
    on a single shape.
    """
    try:
        status = err.status_code
    except Exception:
        status = None
    if status not in (409, 422):
        return False
    msg = ""
    try:
        msg = (err.message or "").lower()
    except Exception:
        try:
            msg = str(err).lower()
        except Exception:
            pass
    return "client_order_id" in msg or "already exists" in msg or "duplicate" in msg


class AlpacaClient:
    """Paper-only Alpaca trading client.

    Holds a ``TradingSafetyGate`` instance that every order submission
    consults before the broker call (review items #1, #2, #3). Build the
    client with ``safety_gate=TradingSafetyGate.from_config(config)`` to
    enforce the kill switch + circuit breakers; the default gate refuses
    every submission (fail-closed).
    """

    def __init__(
        self,
        api_key=None,
        api_secret=None,
        *,
        safety_gate: TradingSafetyGate | None = None,
        paper: bool = True,
    ):
        """Build a client for the Alpaca PAPER endpoint (default) or LIVE.

        Defense in depth on the live-trading boundary:

        * ``paper=True`` (default) reads ALPACA_PAPER_API_KEY / SECRET
          (or the legacy ALPACA_API_KEY / SECRET as fallback). The
          client hits Alpaca's paper endpoint. Suitable for the default
          ``paper_trade_factor_picks`` flow.
        * ``paper=False`` is the LIVE endpoint and requires THREE things
          to all be true at construction time:
              1. ``paper=False`` passed explicitly (no env-var override),
              2. ALPACA_LIVE_API_KEY + ALPACA_LIVE_API_SECRET set (NOT
                 the same env vars as paper, so an operator who only
                 has paper keys configured cannot accidentally hit live),
              3. ALPACA_LIVE_TRADING_CONFIRMED=1 in the environment
                 (a separate consent toggle that survives a key swap).
          Missing any one raises. The check sits at construction so a
          single line of "paper=False" can't reach Alpaca without all
          three boxes ticked.
        """
        if not paper:
            # Live mode — every gate must be lit. This is intentionally
            # noisy to fail loud rather than fail open.
            if os.getenv("ALPACA_LIVE_TRADING_CONFIRMED") != "1":
                raise AlpacaClientError(
                    "Live trading requires ALPACA_LIVE_TRADING_CONFIRMED=1 in "
                    "the environment. This is a deliberate hurdle — flip it "
                    "ONLY in a session where you intend to place live orders."
                )
            api_key = api_key or os.getenv("ALPACA_LIVE_API_KEY")
            api_secret = api_secret or os.getenv("ALPACA_LIVE_API_SECRET")
            if not api_key or not api_secret:
                raise AlpacaClientError(
                    "Live mode requires ALPACA_LIVE_API_KEY and "
                    "ALPACA_LIVE_API_SECRET (distinct from the paper keys) "
                    "so a single env-var leak cannot route paper traffic "
                    "to live."
                )
            logger.warning(
                "AlpacaClient: LIVE MODE — real-money orders. The kill "
                "switch + circuit breakers are your last line of defense."
            )
        else:
            # Paper mode — prefer the explicit PAPER env vars, fall back
            # to legacy ALPACA_API_KEY for compat. If an operator has
            # accidentally set ALPACA_LIVE_API_KEY *only*, refuse rather
            # than silently grabbing it.
            api_key = (
                api_key
                or os.getenv("ALPACA_PAPER_API_KEY")
                or os.getenv("ALPACA_API_KEY")
            )
            api_secret = (
                api_secret
                or os.getenv("ALPACA_PAPER_API_SECRET")
                or os.getenv("ALPACA_API_SECRET")
            )
            if not api_key or not api_secret:
                raise AlpacaClientError(
                    "Paper mode requires ALPACA_PAPER_API_KEY + "
                    "ALPACA_PAPER_API_SECRET (or the legacy ALPACA_API_KEY / "
                    "ALPACA_API_SECRET) in .env. Get them from "
                    "https://app.alpaca.markets/paper/dashboard/overview"
                )
        self._client = TradingClient(api_key, api_secret, paper=paper)
        self._paper = paper
        # Fail-closed default: a client built without an explicit gate
        # refuses every submission. The caller MUST build a gate from the
        # project config (or pass an explicit `trading_enabled=True` one
        # for tests) for any order to go through. This keeps a script
        # that forgot to wire the gate from accidentally trading.
        if safety_gate is None:
            from src.execution.safety_gates import CircuitBreakerThresholds

            safety_gate = TradingSafetyGate(
                trading_enabled=False,
                thresholds=CircuitBreakerThresholds(),
            )
            logger.warning(
                "AlpacaClient built without a safety gate — defaulting to "
                "fail-closed (trading_enabled=False). Pass safety_gate="
                "TradingSafetyGate.from_config(config) to enable trading."
            )
        self._safety_gate = safety_gate

    @property
    def safety_gate(self) -> TradingSafetyGate:
        return self._safety_gate

    @property
    def is_paper(self) -> bool:
        """True when this client points at Alpaca's paper endpoint."""
        return self._paper

    def _build_session_state(self) -> SessionState:
        """Snapshot the live account for the safety gate.

        Called on every submission so the circuit breakers always see
        fresh equity + position-count numbers from Alpaca, not a stale
        cache. Kept private — callers go through ``submit_*``.
        """
        acct = self.get_account()
        equity = float(acct.get("equity") or 0.0)
        positions = self.get_positions()
        # Starting / peak default to current on a fresh session; an
        # operator wrapper (paper_trade_service) can refine peak across
        # a multi-submission batch by passing its own SessionState.
        return SessionState(
            starting_equity=equity,
            current_equity=equity,
            peak_equity=equity,
            open_position_count=len(positions),
        )

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

    def get_portfolio_history(self, period: str = "1M", timeframe: str = "1D"):
        """Equity curve from Alpaca's portfolio history.

        ``period`` accepts Alpaca's shorthand: 1D / 1W / 1M / 3M / 6M / 1A
        (1A = 1 year). ``timeframe`` must be coarser than ``period``;
        Alpaca rejects intraday timeframes on multi-month windows, so we
        cap at 1H for periods <= 1M and force 1D otherwise.

        Returns the parallel arrays alpaca-py already exposes plus a
        coerced datetime list so callers don't have to multiply
        timestamps by 1000 themselves.
        """
        if period.upper() not in {"1D", "1W"} and timeframe == "1H":
            timeframe = "1D"
        req = GetPortfolioHistoryRequest(
            period=period.upper(),
            timeframe=timeframe,
        )
        h = self._client.get_portfolio_history(req)
        # alpaca-py returns epoch SECONDS (not ms) for portfolio history.
        timestamps = [int(t) for t in (h.timestamp or [])]
        equities = [float(v) for v in (h.equity or [])]
        pnl = [float(v) for v in (h.profit_loss or [])]
        pnl_pct = [
            (float(v) * 100) if v is not None else None
            for v in (h.profit_loss_pct or [])
        ]
        return {
            "timestamps": timestamps,
            "equity": equities,
            "profit_loss": pnl,
            "profit_loss_pct": pnl_pct,
            "base_value": float(h.base_value) if h.base_value is not None else None,
            "timeframe": h.timeframe,
            "period": period.upper(),
        }

    # -- Positions -------------------------------------------------------

    def get_positions(self):
        """Return list of dicts mirroring portfolio.yaml holdings format.

        When ``STOCKNEW_USE_REAL_COST_BASIS=1`` is set, ``avg_price`` and
        the derived ``unrealized_pnl`` / ``unrealized_pnl_pct`` are
        overridden from ``config/real_holdings.yaml`` for any ticker
        present in that file. Overridden rows gain
        ``cost_basis_source="real_holdings"`` so consumers can flag the
        provenance. See ``src.portfolio.cost_basis`` for details.
        """
        from src.portfolio.cost_basis import apply_if_enabled

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
        return apply_if_enabled(out)

    # -- Orders ----------------------------------------------------------

    def submit_bracket_order(
        self,
        ticker,
        qty,
        take_profit_price,
        stop_loss_price,
        side="buy",
        client_order_id: str | None = None,
        *,
        score_valid: bool = True,
        session_state: SessionState | None = None,
    ):
        """
        Submit a bracket market order. Returns the parent order ID.

        Bracket orders on Alpaca require whole-share qty (no fractional).
        Caller should int() qty before passing.

        Direction-specific level invariants (enforced):
          * Long (side='buy'):  stop_loss < take_profit. Stop is BELOW
            the entry; TP is ABOVE. The children are sells (close long).
          * Short (side='sell'): stop_loss > take_profit. Stop is ABOVE
            the entry; TP is BELOW. The children are buys (cover short).

        `client_order_id` is required for real-money idempotency: pass a
        deterministic id (see `make_client_order_id`) so retries collide
        on Alpaca's duplicate check instead of double-filling. Duplicates
        raise `AlpacaDuplicateOrderError`.

        Safety gates run BEFORE the broker call:
          * ``score_valid=False`` refuses outright (review item #3).
          * ``session_state`` (or a fresh broker snapshot if omitted) is
            checked against the configured circuit breakers (review #2).
          * The trading_enabled kill switch is consulted (review #1).
        Any failure raises ``TradingHaltedError``.
        """
        if qty < 1:
            raise AlpacaClientError(
                f"Bracket orders require qty >= 1 whole share (got {qty} for {ticker})"
            )

        # Direction-specific invariant: shorts must have stop ABOVE TP,
        # longs the reverse. Catches the most common foot-gun where a
        # caller flips the side without flipping the prices.
        if side == "buy" and take_profit_price <= stop_loss_price:
            raise AlpacaClientError(
                f"Long bracket on {ticker}: take_profit ({take_profit_price}) "
                f"must be > stop_loss ({stop_loss_price})"
            )
        if side == "sell" and take_profit_price >= stop_loss_price:
            raise AlpacaClientError(
                f"Short bracket on {ticker}: take_profit ({take_profit_price}) "
                f"must be < stop_loss ({stop_loss_price})"
            )

        # Estimate notional for the order-value gate. Bracket entries
        # are market orders so we don't have a limit price; use the TP
        # leg as a *minimum* notional estimate. Real fill notional may
        # be a few percent off but max_order_value_usd is a coarse cap.
        notional = float(qty) * float(take_profit_price)
        session = session_state or self._build_session_state()
        self._safety_gate.check_pre_submit(
            ticker=ticker,
            notional_usd=notional,
            session=session,
            score_valid=score_valid,
        )

        req = MarketOrderRequest(
            symbol=ticker,
            qty=int(qty),
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(take_profit_price, 2)),
            stop_loss=StopLossRequest(stop_price=round(stop_loss_price, 2)),
            client_order_id=client_order_id,
        )
        try:
            order = self._client.submit_order(req)
        except APIError as e:
            if _is_duplicate_coid_error(e):
                raise AlpacaDuplicateOrderError(
                    f"duplicate client_order_id for {ticker}: {client_order_id}"
                ) from e
            raise
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

    def submit_market_order(
        self,
        ticker,
        qty,
        side="buy",
        client_order_id: str | None = None,
        *,
        score_valid: bool = True,
        session_state: SessionState | None = None,
        reference_price: float | None = None,
    ):
        """Plain market order — used for fractional close-outs and SELL recommendations.

        See `submit_bracket_order` for idempotency semantics; same rules apply.

        Safety gates apply equally to BUY and SELL (review item #3): a
        broken-analyzer SELL must not close a real position any more than
        a broken-analyzer BUY should open one. ``reference_price`` lets
        the order-value gate compute notional for a market order (which
        has no limit price); pass last known close. If omitted, the
        order-value gate is skipped for this submission.
        """
        notional = float(qty) * float(reference_price) if reference_price else 0.0
        if not reference_price:
            # notional=0 makes the order-value circuit breaker (max_order_value_usd)
            # a no-op for this submission. Surface it so a skipped gate is never
            # silent -- the caller passes reference_price for closes/resizes to keep
            # the cap live.
            logger.warning(
                "order-value gate SKIPPED for %s %s %s sh: no reference_price "
                "(notional=0, max_order_value_usd not enforced on this order)",
                side, qty, ticker,
            )
        session = session_state or self._build_session_state()
        self._safety_gate.check_pre_submit(
            ticker=ticker,
            notional_usd=notional,
            session=session,
            score_valid=score_valid,
        )

        req = MarketOrderRequest(
            symbol=ticker,
            qty=qty,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            client_order_id=client_order_id,
        )
        try:
            order = self._client.submit_order(req)
        except APIError as e:
            if _is_duplicate_coid_error(e):
                raise AlpacaDuplicateOrderError(
                    f"duplicate client_order_id for {ticker}: {client_order_id}"
                ) from e
            raise
        return {
            "order_id": str(order.id),
            "client_order_id": order.client_order_id,
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

    def get_order_by_coid(self, client_order_id: str):
        """Look up an Alpaca order by its client_order_id.

        Returns a dict mirroring `get_orders` shape, or None if Alpaca
        has no record of that COID. Used by the idempotent submit path
        (review M1): on retry, we ask Alpaca whether the original
        submission actually landed before deciding whether to resubmit.

        Alpaca's REST endpoint is GET /v2/orders:by_client_order_id; in
        alpaca-py it's `TradingClient.get_order_by_client_id`. A 404
        means "Alpaca never received this order" and the caller can
        safely resubmit; any other API error propagates.
        """
        try:
            o = self._client.get_order_by_client_id(client_order_id)
        except APIError as e:
            # 404 path — alpaca-py raises APIError with status 404 when
            # the COID is unknown. Treat as "not at Alpaca".
            status = getattr(e, "status_code", None)
            if status == 404:
                return None
            raise
        if o is None:
            return None
        return {
            "order_id": str(o.id),
            "client_order_id": o.client_order_id,
            "ticker": o.symbol,
            "qty": float(o.qty) if o.qty else 0,
            "filled_qty": float(o.filled_qty) if o.filled_qty else 0,
            "filled_price": float(o.filled_avg_price) if o.filled_avg_price else None,
            "side": str(o.side),
            "status": str(o.status),
            "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
        }

    def get_clock(self):
        clock = self._client.get_clock()
        return {
            "is_open": bool(clock.is_open),
            "next_open": clock.next_open.isoformat() if clock.next_open else None,
            "next_close": clock.next_close.isoformat() if clock.next_close else None,
        }
