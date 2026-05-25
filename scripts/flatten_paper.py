"""One-shot: close ALL Alpaca paper positions + cancel ALL open orders.

For clearing accumulated cruft (older strategy runs leaving stale
positions) before re-running paper_trade_factor_picks on a new
config (e.g. the d05 -> d03 concentration ship).

Hard paper-only. Asserts the underlying client is paper=True before
touching anything; refuses if it can't confirm.

Usage:
    uv run python -m scripts.flatten_paper          # dry-run
    uv run python -m scripts.flatten_paper --execute
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()
os.environ["STOCKNEW_TRADING_ENABLED"] = "1"  # process-scope only

from src.execution.alpaca import AlpacaClient  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("flatten_paper")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--execute", action="store_true",
                   help="Actually close positions + cancel orders. Default = dry-run.")
    args = p.parse_args()

    client = AlpacaClient()
    if not client.is_paper:
        logger.error("Client is NOT paper. Refusing to flatten a live account.")
        return 2

    positions = client.get_positions()
    orders = client.get_orders(status="open")

    logger.info("Paper account state:")
    logger.info("  %d open positions", len(positions))
    logger.info("  %d open orders", len(orders))

    if not positions and not orders:
        logger.info("Nothing to flatten.")
        return 0

    def _get(rec, key, default="?"):
        if isinstance(rec, dict):
            return rec.get(key, default)
        return getattr(rec, key, default)

    if not args.execute:
        n_longs = sum(1 for pos in positions if float(_get(pos, "shares", 0) or 0) > 0)
        n_shorts = len(positions) - n_longs
        logger.info("  longs=%d  shorts=%d", n_longs, n_shorts)
        for pos in sorted(positions, key=lambda p: -abs(float(_get(p, "market_value", 0) or 0))):
            logger.info(
                "  WOULD CLOSE  %-6s shares=%s mv=$%s pnl=%s%%",
                _get(pos, "ticker"), _get(pos, "shares"),
                _get(pos, "market_value"),
                _get(pos, "unrealized_pnl_pct"),
            )
        for o in orders[:10]:
            logger.info(
                "  WOULD CANCEL %-6s %s qty=%s",
                _get(o, "symbol"), _get(o, "side"), _get(o, "qty"),
            )
        if len(orders) > 10:
            logger.info("  ... and %d more open orders", len(orders) - 10)
        logger.info("Dry-run only. Pass --execute to actually flatten.")
        return 0

    # Cancel orders first so close_all_positions doesn't race with stops.
    underlying = client._client  # alpaca-py TradingClient
    if orders:
        logger.info("Cancelling all open orders...")
        underlying.cancel_orders()
        logger.info("  Cancelled.")

    if positions:
        logger.info("Closing all positions (market orders)...")
        responses = underlying.close_all_positions(cancel_orders=True)
        ok = sum(1 for r in responses if getattr(r, "status", 0) in (200, 207))
        logger.info("  Submitted close requests: %d (HTTP-ok: %d)", len(responses), ok)
        for r in responses[:5]:
            logger.info(
                "    %s: status=%s symbol=%s",
                getattr(r, "symbol", "?"),
                getattr(r, "status", "?"),
                getattr(r, "symbol", "?"),
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
