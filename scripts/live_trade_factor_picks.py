"""Send today's composite factor picks to Alpaca LIVE (real money).

Thin wrapper over ``scripts.paper_trade_factor_picks`` — identical plan
building, sizing, and pre-trade gates (drift, kill switch, LLM sanity),
but pointed at the LIVE endpoint with the trading.live circuit-breaker
overlay. Dormant until the forward-paper review (~2026-08-27) passes;
see docs/railway_deploy.md for the pre-funding checklist.

Activation requires ALL of (checked at AlpacaClient construction):
  1. ALPACA_LIVE_API_KEY + ALPACA_LIVE_API_SECRET in the environment
     (distinct from the paper keys),
  2. ALPACA_LIVE_TRADING_CONFIRMED=1,
  3. this script (paper=False is never set anywhere else).

Live-specific restrictions on top of the paper flow:
  - every ``--override-*`` flag and ``--skip-sanity`` is refused outright
    — live money has no gate bypasses; fix the gate or don't trade,
  - ``config/settings.yaml`` must define a ``trading.live`` block so the
    tighter live circuit breakers are explicit, never defaulted.

Usage
-----

    # Dry run (default) -- plan + gates against the live account, no orders:
    uv run python -m scripts.live_trade_factor_picks

    # Actually submit (funded account, post-checklist only):
    uv run python -m scripts.live_trade_factor_picks --execute
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv()

_FORBIDDEN_FLAGS = (
    "--override-drift",
    "--override-kill-switch",
    "--override-sanity-errors",
    "--skip-sanity",
)


def main() -> int:
    bad = [f for f in _FORBIDDEN_FLAGS if f in sys.argv[1:]]
    if bad:
        raise SystemExit(
            f"live trading refuses {', '.join(bad)}: gate overrides are "
            f"paper-only. If a gate is blocking live execution, that IS "
            f"the system working — investigate the gate, don't bypass it."
        )

    from src.config_loader import Config

    if not Config().get("trading", "live", default=None):
        raise SystemExit(
            "config/settings.yaml has no trading.live block. Live execution "
            "requires the live circuit-breaker overlay to be explicit "
            "(max_order_value_usd, max_open_positions, ...) — refusing to "
            "run on paper-sized caps."
        )

    from scripts.paper_trade_factor_picks import main as _trade_main

    return _trade_main(paper=False)


if __name__ == "__main__":
    sys.exit(main())
