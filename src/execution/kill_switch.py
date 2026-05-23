"""Live α kill switch — refuse new entries when 60d rolling α vs SPY < threshold.

Added 2026-05-23 after live paper logged -11.2% α vs SPY over 90d on d03 with no
hard stop wired in.

Mechanics
---------
The rolling window resets when the live strategy label changes. We track
``(strategy_label, started_at)`` in ``data/live_strategy_state.json``; if a
caller asks ``rollover_if_changed("factor_composite_d05_r63")`` and the file
holds a different label (or no file exists), we write a new state pinned to
today's UTC date and treat the kill-switch window as just-restarted.

This is deliberate: the prior strategy's equity curve is contaminated. There's
no honest way to use it. Until ``--lookback-days`` trading days have elapsed
post-rollover, the gate reports ``warming_up`` and lets trading proceed.

Output schema (``reports/kill_switch.json``)
--------------------------------------------
- ``status``: ``ok`` | ``warming_up`` | ``triggered`` | ``unavailable``
- ``strategy_label``: the label the state file records
- ``strategy_started_at``: ISO date the current strategy began
- ``trading_days_in_window``: how many post-rollover trading days we have
- ``alpha_pct``: trailing-window α (paper return − SPY return), null until full window
- ``threshold_pct``: the trigger threshold (e.g., -8.0)
- ``message``: human-readable summary
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

STATE_FILE = Path("data/live_strategy_state.json")
REPORT_FILE = Path("reports/kill_switch.json")

# Default thresholds. Caller can override.
DEFAULT_LOOKBACK_TRADING_DAYS = 60
DEFAULT_ALPHA_THRESHOLD_PCT = -8.0


@dataclass(frozen=True)
class StrategyState:
    label: str
    started_at: str  # ISO date YYYY-MM-DD


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def load_state() -> Optional[StrategyState]:
    if not STATE_FILE.exists():
        return None
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return StrategyState(label=payload["strategy_label"],
                             started_at=payload["started_at"])
    except (json.JSONDecodeError, KeyError, OSError) as e:
        logger.warning("kill_switch state file unreadable, treating as missing: %s", e)
        return None


def _save_state(state: StrategyState) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({
            "strategy_label": state.label,
            "started_at": state.started_at,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }, indent=2),
        encoding="utf-8",
    )


def rollover_if_changed(current_label: str) -> StrategyState:
    """Ensure state matches ``current_label``; rewrite with today's date if not.

    Called by ``paper_trade_factor_picks.py`` right before order submission.
    Idempotent within the same UTC date for the same label.
    """
    existing = load_state()
    if existing is not None and existing.label == current_label:
        return existing
    new_state = StrategyState(label=current_label, started_at=_today_iso())
    _save_state(new_state)
    if existing is None:
        logger.info("kill_switch: initialized state for %s as_of %s",
                    new_state.label, new_state.started_at)
    else:
        logger.info("kill_switch: strategy rollover %s → %s, window resets to %s",
                    existing.label, new_state.label, new_state.started_at)
    return new_state


def _trading_days_between(start_iso: str, end_iso: str) -> int:
    """Approximate trading-day count using pandas business-day arithmetic.

    Sufficient for the gate — we don't need market-calendar precision because
    the threshold (60 trading days) is loose by design.
    """
    import pandas as pd

    bd = pd.bdate_range(start=start_iso, end=end_iso)
    return max(0, len(bd) - 1)  # exclusive of start


def _aligned_window_alpha(
    state: StrategyState,
    lookback_trading_days: int,
) -> Optional[dict]:
    """Compute paper return − SPY return over the post-rollover window.

    Returns ``None`` when Alpaca creds or yfinance are unavailable. The caller
    should treat ``None`` as ``status=unavailable`` rather than ``triggered``.
    """
    import pandas as pd

    try:
        from src.execution.alpaca import AlpacaClient, AlpacaClientError
    except ImportError as e:
        logger.warning("kill_switch: alpaca-py not importable: %s", e)
        return None
    try:
        client = AlpacaClient()
    except AlpacaClientError as e:
        logger.info("kill_switch: Alpaca not configured: %s", e)
        return None

    # Period selection: ask for at least 3M of equity, then trim post-rollover.
    # Alpaca's period shorthand caps at 1A; the kill switch never needs more
    # than ~3 months of history.
    period = "3M" if lookback_trading_days <= 63 else "6M"
    try:
        hist = client.get_portfolio_history(period=period, timeframe="1D")
    except Exception as e:
        logger.warning("kill_switch: portfolio_history failed: %s", e)
        return None

    timestamps = hist.get("timestamps") or []
    equities = hist.get("equity") or []
    if not timestamps or len(equities) != len(timestamps):
        return None

    paper = pd.DataFrame({
        "ts": pd.to_datetime(timestamps, unit="s", utc=True).tz_convert("UTC"),
        "equity": equities,
    })
    paper["date"] = paper["ts"].dt.date.astype(str)
    paper = paper[paper["equity"] > 0]
    if paper.empty:
        return None

    started_at = state.started_at
    # First eligible row: on or after strategy_start.
    paper = paper[paper["date"] >= started_at].reset_index(drop=True)
    if len(paper) < 2:
        return None

    # SPY series for the same date range. We use yfinance directly to avoid
    # dragging in DataFetcher's caching for a single-ticker / short-window call.
    try:
        import yfinance as yf
        spy_period = "6mo" if lookback_trading_days <= 63 else "1y"
        spy = yf.Ticker("SPY").history(period=spy_period, auto_adjust=True)
    except Exception as e:
        logger.warning("kill_switch: yfinance SPY fetch failed: %s", e)
        return None
    if spy is None or spy.empty:
        return None
    if isinstance(spy.index, pd.DatetimeIndex) and spy.index.tz is not None:
        spy.index = spy.index.tz_convert("UTC").tz_localize(None)
    spy = spy.reset_index().rename(columns={"Date": "ts", "Close": "close"})
    spy["date"] = spy["ts"].dt.date.astype(str)
    spy = spy[spy["date"] >= started_at].reset_index(drop=True)
    if spy.empty:
        return None

    paper_start_eq = float(paper["equity"].iloc[0])
    paper_end_eq = float(paper["equity"].iloc[-1])
    spy_start_px = float(spy["close"].iloc[0])
    spy_end_px = float(spy["close"].iloc[-1])
    if paper_start_eq <= 0 or spy_start_px <= 0:
        return None

    paper_ret_pct = (paper_end_eq / paper_start_eq - 1) * 100
    spy_ret_pct = (spy_end_px / spy_start_px - 1) * 100
    alpha_pct = paper_ret_pct - spy_ret_pct

    return {
        "paper_return_pct": round(paper_ret_pct, 2),
        "spy_return_pct": round(spy_ret_pct, 2),
        "alpha_pct": round(alpha_pct, 2),
        "trading_days_in_window": len(paper) - 1,
    }


def evaluate(
    current_label: str,
    *,
    lookback_trading_days: int = DEFAULT_LOOKBACK_TRADING_DAYS,
    threshold_pct: float = DEFAULT_ALPHA_THRESHOLD_PCT,
) -> dict:
    """Run the gate. Side effect: rolls over state if label changed.

    Returns the payload that will be written to ``reports/kill_switch.json``.
    """
    state = rollover_if_changed(current_label)
    base = {
        "strategy_label": state.label,
        "strategy_started_at": state.started_at,
        "threshold_pct": threshold_pct,
        "lookback_trading_days": lookback_trading_days,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    days_elapsed = _trading_days_between(state.started_at, _today_iso())
    if days_elapsed < lookback_trading_days:
        return {
            **base,
            "status": "warming_up",
            "trading_days_in_window": days_elapsed,
            "alpha_pct": None,
            "message": (
                f"{days_elapsed}/{lookback_trading_days} trading days since "
                f"strategy started {state.started_at}. Kill switch inactive."
            ),
        }

    snap = _aligned_window_alpha(state, lookback_trading_days)
    if snap is None:
        return {
            **base,
            "status": "unavailable",
            "trading_days_in_window": days_elapsed,
            "alpha_pct": None,
            "message": (
                "Could not compute α — Alpaca creds missing, portfolio history "
                "empty, or yfinance failed. Gate inactive."
            ),
        }

    alpha = snap["alpha_pct"]
    triggered = alpha < threshold_pct
    return {
        **base,
        "status": "triggered" if triggered else "ok",
        "trading_days_in_window": snap["trading_days_in_window"],
        "alpha_pct": alpha,
        "paper_return_pct": snap["paper_return_pct"],
        "spy_return_pct": snap["spy_return_pct"],
        "message": (
            f"Live α {alpha:+.2f}% vs threshold {threshold_pct:+.2f}% over "
            f"{snap['trading_days_in_window']} trading days since "
            f"{state.started_at}."
        ),
    }


def write_report(payload: dict) -> Path:
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return REPORT_FILE
