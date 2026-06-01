"""Snapshot the paper portfolio P&L vs SPY over the trailing window.

Writes ``reports/paper_vs_spy.json`` — the single live comparison file
the FE renders on ``/factors``. The file is overwritten on every run
(not date-stamped) because the UI only cares about "where do we stand
right now", not historical snapshots.

Failure modes are all graceful:
- Alpaca creds missing → writes status=not_configured so the FE shows a
  "configure paper trading" hint
- Alpaca returns no portfolio_history → status=no_history
- yfinance fetch fails → status=error with the message

Usage
-----

    uv run python -m scripts.paper_vs_spy_snapshot
    uv run python -m scripts.paper_vs_spy_snapshot --window 3M

The snapshot is read-only with respect to Alpaca; it does not place
orders.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("paper_vs_spy_snapshot")

OUTPUT_FILE = Path("reports/paper_vs_spy.json")

# Alpaca period shorthand → approximate calendar days. Used to pick a
# matching SPY window so the two P&Ls are comparable.
_PERIOD_TO_DAYS = {
    "1W": 7,
    "1M": 30,
    "3M": 90,
    "6M": 180,
    "1A": 365,
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--window", default="3M", choices=list(_PERIOD_TO_DAYS),
        help="Alpaca period shorthand (default 3M).",
    )
    return p.parse_args()


def _write(payload: dict) -> Path:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload.setdefault("generated_at_utc", datetime.now(timezone.utc).isoformat())
    OUTPUT_FILE.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8",
    )
    logger.info("Wrote %s (status=%s)", OUTPUT_FILE, payload.get("status"))
    return OUTPUT_FILE


def _spy_window(window_days: int) -> Optional[dict]:
    """Pull SPY prices for a window roughly matching ``window_days``.

    Returns ``{starting_price, current_price, return_pct}`` or None if the
    fetch returned nothing useful. SPY is a plain equity, so we route
    through the project's configured fetcher (Polygon = deterministic,
    not rate-limited) rather than calling yfinance directly.
    """
    from src.config_loader import Config
    from src.data.fetcher_factory import get_data_fetcher

    # Choose a period one band larger so we always have enough rows.
    period_map = {30: "3mo", 90: "6mo", 180: "1y", 365: "2y"}
    period = period_map.get(window_days, "1y")
    try:
        fetcher = get_data_fetcher(Config())
        df = fetcher.fetch_price_data("SPY", period=period)
    except Exception as e:
        logger.warning("SPY fetch failed: %s", e)
        return None
    if df is None or df.empty:
        return None

    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)

    if len(df) < 2:
        return None
    # The starting row is the close nearest window_days ago. Don't take
    # the very first row of the fetched series — that's older than the
    # paper window for "1y"/"2y" periods.
    cutoff = df.index[-1] - pd.Timedelta(days=window_days)
    eligible = df[df.index >= cutoff]
    if eligible.empty:
        return None
    starting = float(eligible["Close"].iloc[0])
    current = float(eligible["Close"].iloc[-1])
    if starting <= 0:
        return None
    return {
        "starting_price": round(starting, 2),
        "current_price": round(current, 2),
        "return_pct": round((current / starting - 1) * 100, 2),
    }


def _paper_window(period: str) -> Optional[dict]:
    """Pull Alpaca portfolio history for ``period``. None if creds missing.

    Builds the client with the fail-closed default safety gate — we
    never place orders from this snapshot script.
    """
    try:
        from src.execution.alpaca import AlpacaClient, AlpacaClientError
    except ImportError as e:
        logger.warning("alpaca-py not installed: %s", e)
        return None

    try:
        client = AlpacaClient()
    except AlpacaClientError as e:
        logger.info("Alpaca not configured: %s", e)
        return None

    try:
        hist = client.get_portfolio_history(period=period, timeframe="1D")
    except Exception as e:
        logger.warning("Alpaca portfolio_history failed: %s", e)
        return None

    equities = hist.get("equity") or []
    # Filter out zero/None entries — they appear before the account
    # first traded.
    equities = [e for e in equities if e is not None and e > 0]
    if len(equities) < 2:
        return None

    starting = float(equities[0])
    current = float(equities[-1])
    return {
        "starting_equity_usd": round(starting, 2),
        "current_equity_usd": round(current, 2),
        "pnl_usd": round(current - starting, 2),
        "return_pct": round((current / starting - 1) * 100, 2),
    }


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()
    window_days = _PERIOD_TO_DAYS[args.window]

    paper = _paper_window(args.window)
    if paper is None:
        # Distinguish "no creds" from "creds OK but no history" by
        # re-probing — if AlpacaClient instantiation fails it's the
        # not_configured case; if instantiation works but history is
        # empty it's no_history. The simplest heuristic: try one more
        # account call.
        status = "not_configured"
        message = (
            "ALPACA_API_KEY / ALPACA_API_SECRET not set, or the account "
            "returned no portfolio history. Set credentials in .env and "
            "re-run."
        )
        try:
            from src.execution.alpaca import AlpacaClient

            AlpacaClient().get_account()
            status = "no_history"
            message = (
                "Alpaca account is connected but portfolio_history is "
                "empty — likely a brand-new paper account with no trades "
                "yet. Run paper-trade orders to populate history."
            )
        except Exception:
            pass
        return 0 if _write({
            "status": status,
            "message": message,
            "window_days": window_days,
        }) else 1

    spy = _spy_window(window_days)
    if spy is None:
        _write({
            "status": "error",
            "message": "yfinance returned no SPY data for the window.",
            "window_days": window_days,
            "paper": paper,
        })
        return 0

    alpha_pct = round(paper["return_pct"] - spy["return_pct"], 2)
    _write({
        "status": "ok",
        "window_days": window_days,
        "paper": paper,
        "spy": spy,
        "alpha_pct": alpha_pct,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
