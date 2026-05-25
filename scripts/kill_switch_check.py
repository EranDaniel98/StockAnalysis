"""Daily live α kill-switch check.

Reads (or creates) ``data/live_strategy_state.json``, compares the trailing
60d paper α vs SPY to a -8% threshold, and writes the verdict to
``reports/kill_switch.json``. Exit code is non-zero when the gate is
``triggered`` so a wrapping pipeline can refuse to submit new orders.

Usage
-----

    uv run python -m scripts.kill_switch_check
    uv run python -m scripts.kill_switch_check --threshold-pct -12
    uv run python -m scripts.kill_switch_check --strategy-label factor_composite_d05_r63
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.execution.kill_switch import (
    DEFAULT_ALPHA_THRESHOLD_PCT,
    DEFAULT_LOOKBACK_TRADING_DAYS,
    evaluate,
    write_report,
)

# Must match scripts/paper_trade_factor_picks.py:STRATEGY_LABEL. Hard-coding
# rather than importing to keep this script independent of the live-trading
# entrypoint.
DEFAULT_STRATEGY_LABEL = "factor_composite_d05_r63"

logger = logging.getLogger("kill_switch_check")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser()
    p.add_argument("--strategy-label", default=DEFAULT_STRATEGY_LABEL,
                   help="Label that identifies the current live strategy. "
                        "When it differs from the state file, the rolling "
                        "window is reset to today.")
    p.add_argument("--threshold-pct", type=float,
                   default=DEFAULT_ALPHA_THRESHOLD_PCT,
                   help=(f"Trigger when {DEFAULT_LOOKBACK_TRADING_DAYS}d α "
                         f"drops below this (default {DEFAULT_ALPHA_THRESHOLD_PCT})."))
    p.add_argument("--lookback-trading-days", type=int,
                   default=DEFAULT_LOOKBACK_TRADING_DAYS)
    p.add_argument("--soft", action="store_true",
                   help="Always exit 0 even when triggered; just write the "
                        "report. Use during warm-up or when wiring this in "
                        "as advisory.")
    args = p.parse_args()

    payload = evaluate(
        args.strategy_label,
        lookback_trading_days=args.lookback_trading_days,
        threshold_pct=args.threshold_pct,
    )
    path = write_report(payload)
    status = payload["status"]
    marker = {
        "ok": "[OK]",
        "warming_up": "[WARMUP]",
        "triggered": "[TRIGGERED]",
        "unavailable": "[UNAVAIL]",
    }.get(status, f"[{status.upper()}]")
    print(f"{marker} kill_switch: {payload['message']}")
    print(f"       wrote {path}")

    if status == "triggered" and not args.soft:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
