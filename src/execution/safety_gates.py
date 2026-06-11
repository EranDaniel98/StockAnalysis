"""Real-money safety gates — checked at the broker-client boundary.

Review items #1 and #2. ``TradingSafetyGate`` is the single object every
order submission consults. It owns the trading_enabled kill switch and
the four circuit breakers (daily P&L floor, drawdown halt, open-position
count cap, max notional per order). Failing any check raises
``TradingHaltedError`` — the broker-client refuses the submission and the
operator sees a loud log line.

Design:
  * Kill switch is read from config OR the ``STOCKNEW_TRADING_ENABLED``
    env var. The env var wins for per-session overrides without editing
    the checked-in YAML.
  * Circuit-breaker thresholds live in ``config/settings.yaml`` under
    ``trading.circuit_breakers``. Zero disables a check.
  * ``check_pre_submit(...)`` is the one call sites hit. Returns None
    on pass, raises on fail.

This module deliberately depends only on dataclasses + config — no
Alpaca SDK, no DB. The gate is testable in isolation.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class TradingHaltedError(Exception):
    """Raised when an order submission is refused by a safety gate.

    The exception's args carry the operator-readable refusal reason so
    the broker-client log shows exactly which gate tripped. We use a
    distinct exception type (not AlpacaClientError) so the caller can
    distinguish "system refused" from "Alpaca rejected".
    """


_ENV_OVERRIDE = "STOCKNEW_TRADING_ENABLED"


def _env_trading_enabled() -> bool | None:
    """Parse the trading-enabled env var.

    Returns True if the var is set to a truthy value, False if explicitly
    falsy, None if unset. Caller falls back to config when None.
    """
    raw = os.environ.get(_ENV_OVERRIDE)
    if raw is None:
        return None
    raw = raw.strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off", ""}:
        return False
    return None


@dataclass(frozen=True)
class CircuitBreakerThresholds:
    """Frozen snapshot of the configured circuit-breaker thresholds.

    Loaded from ``config.trading.circuit_breakers`` at session start;
    held constant for the run so a mid-session config edit doesn't
    silently relax the gates.
    """

    max_daily_loss_pct: float = 0.0
    """Refuse new entries when session P&L pct is below (i.e. more
    negative than) this. Pass 0.0 to disable. Expected negative value
    e.g. -0.02 = -2%."""

    max_drawdown_halt_pct: float = 0.0
    """Refuse new entries when trailing drawdown from session peak is
    below this. 0.0 disables."""

    max_open_positions: int = 0
    """Refuse new entries if currently-open position count meets or
    exceeds this. 0 disables."""

    max_order_value_usd: float = 0.0
    """Refuse a single submission whose notional value exceeds this.
    0.0 disables."""

    @classmethod
    def from_config(cls, config, *, live: bool = False) -> "CircuitBreakerThresholds":
        """``live=True`` overlays ``trading.live.circuit_breakers`` on the
        base block — live money gets its own (tighter) caps without
        forking the paper config."""
        cb = dict(
            config.get("trading", "circuit_breakers", default={})
            if config is not None else {}
        )
        if live:
            overlay = (
                config.get("trading", "live", "circuit_breakers", default={})
                if config is not None else {}
            ) or {}
            cb.update(overlay)
        return cls(
            max_daily_loss_pct=float(cb.get("max_daily_loss_pct", 0.0) or 0.0),
            max_drawdown_halt_pct=float(cb.get("max_drawdown_halt_pct", 0.0) or 0.0),
            max_open_positions=int(cb.get("max_open_positions", 0) or 0),
            max_order_value_usd=float(cb.get("max_order_value_usd", 0.0) or 0.0),
        )


@dataclass
class SessionState:
    """Mutable snapshot of session-level state the gate checks against.

    Populated from the Alpaca account at session start, then updated by
    the operator between submissions if the same gate instance is
    reused for a batch. We keep it mutable on purpose — circuit breakers
    that read frozen open-of-session numbers would miss intra-session
    drawdown.
    """

    starting_equity: float
    """Account equity at the moment the session opened. Drawdown / daily-
    loss percentages are computed against this anchor."""

    current_equity: float
    """Latest account equity. Caller refreshes between submissions if
    available; otherwise stays at starting_equity for the run."""

    peak_equity: float
    """Maximum equity observed this session. Drawdown = (peak - current)
    / starting_equity. Defaults to ``starting_equity`` if no later
    refresh has happened."""

    open_position_count: int
    """Number of currently-open positions at the broker. Refreshed
    before each submission attempt."""


class TradingSafetyGate:
    """Refuse order submissions that fail a safety gate.

    Held by ``AlpacaClient``; called once per ``submit_*`` invocation.
    Stateless w.r.t. the broker — all state comes from caller-supplied
    ``SessionState``.
    """

    def __init__(
        self,
        *,
        trading_enabled: bool,
        thresholds: CircuitBreakerThresholds,
    ) -> None:
        self._trading_enabled = bool(trading_enabled)
        self._thresholds = thresholds

    @classmethod
    def from_config(cls, config, *, live: bool = False) -> "TradingSafetyGate":
        """Build a gate from the project config + env override.

        Env var wins: STOCKNEW_TRADING_ENABLED=1 forces enabled even if
        the YAML says false; =0 forces disabled. Unset → use YAML.
        ``live=True`` applies the trading.live circuit-breaker overlay.
        """
        env = _env_trading_enabled()
        if env is not None:
            enabled = env
            source = f"env({_ENV_OVERRIDE})"
        else:
            enabled = bool(
                config.get("trading", "trading_enabled", default=False)
                if config is not None else False
            )
            source = "config(trading.trading_enabled)"
        logger.info(
            "safety_gate: trading_enabled=%s (source=%s)", enabled, source,
        )
        return cls(
            trading_enabled=enabled,
            thresholds=CircuitBreakerThresholds.from_config(config, live=live),
        )

    @property
    def trading_enabled(self) -> bool:
        return self._trading_enabled

    @property
    def thresholds(self) -> CircuitBreakerThresholds:
        return self._thresholds

    def check_pre_submit(
        self,
        *,
        ticker: str,
        notional_usd: float,
        session: SessionState,
        score_valid: bool = True,
    ) -> None:
        """Run every gate. Raise TradingHaltedError on the first failure.

        Order of checks matters: cheapest / most-fundamental first so we
        fail loudly on the obvious problem (kill switch) before computing
        drawdown.

        ``score_valid`` propagates the upstream analyzer-validity flag
        (review item #3). False refuses the order whether BUY or SELL —
        a broken pipeline must not close real positions any more than
        it should open them.
        """
        if not self._trading_enabled:
            raise TradingHaltedError(
                f"trading_enabled is False — refusing {ticker} submission. "
                f"Set trading.trading_enabled: true in config OR export "
                f"{_ENV_OVERRIDE}=1 for the session."
            )
        if not score_valid:
            raise TradingHaltedError(
                f"score_valid=False for {ticker} — refusing submission. "
                f"Upstream analyzer pipeline reported an error; a broken "
                f"score must not trigger entries OR exits. Re-run the "
                f"scan after fixing the analyzer fault."
            )

        t = self._thresholds
        if t.max_order_value_usd > 0 and notional_usd > t.max_order_value_usd:
            raise TradingHaltedError(
                f"order value ${notional_usd:,.2f} exceeds max_order_value_usd "
                f"${t.max_order_value_usd:,.2f} — refusing {ticker} submission."
            )

        if t.max_open_positions > 0 and session.open_position_count >= t.max_open_positions:
            raise TradingHaltedError(
                f"open positions {session.open_position_count} >= "
                f"max_open_positions {t.max_open_positions} — refusing "
                f"{ticker} submission."
            )

        if t.max_daily_loss_pct < 0 and session.starting_equity > 0:
            day_pnl_pct = (session.current_equity - session.starting_equity) / session.starting_equity
            if day_pnl_pct < t.max_daily_loss_pct:
                raise TradingHaltedError(
                    f"session P&L {day_pnl_pct*100:+.2f}% breached "
                    f"max_daily_loss_pct {t.max_daily_loss_pct*100:+.2f}% — "
                    f"halting; refusing {ticker} submission."
                )

        if t.max_drawdown_halt_pct < 0 and session.starting_equity > 0:
            # Drawdown is measured against the session peak, not opening
            # equity — protects against giving back a session gain.
            dd_pct = (session.current_equity - session.peak_equity) / session.starting_equity
            if dd_pct < t.max_drawdown_halt_pct:
                raise TradingHaltedError(
                    f"session drawdown from peak {dd_pct*100:+.2f}% breached "
                    f"max_drawdown_halt_pct {t.max_drawdown_halt_pct*100:+.2f}% "
                    f"— halting; refusing {ticker} submission."
                )
