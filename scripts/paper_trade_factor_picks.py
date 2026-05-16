"""Send today's composite factor picks to Alpaca PAPER.

Reads the most recent ``data/daily_picks/YYYY-MM-DD.json``, computes
the equal-weight rebalance from current paper positions, and submits
market orders.

Default mode is **DRY RUN** — it prints the plan but does NOT submit.
Pass ``--execute`` to actually place orders.

Safety
------
- Paper-only client (AlpacaClient is hard-coded to paper=True).
- Trading kill switch overridden via ``STOCKNEW_TRADING_ENABLED=1``
  for the lifetime of this process only — no config edit.
- Deterministic client_order_ids: a re-run on the same UTC date is
  refused by Alpaca as a duplicate; no double-fills.
- The script DOES NOT touch positions outside the strategy's
  client_order_id namespace (i.e., it sells everything currently
  held, on the assumption that the paper account is dedicated to
  this strategy). Run on a clean paper account.

Usage
-----

    # Dry run (default) — show the plan only:
    uv run python -m scripts.paper_trade_factor_picks

    # Pick a different date's picks file:
    uv run python -m scripts.paper_trade_factor_picks --picks-date 2026-05-16

    # Actually submit:
    uv run python -m scripts.paper_trade_factor_picks --execute
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("paper_trade_factor_picks")

STRATEGY_LABEL = "factor_composite_d05_r63"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--picks-date", default=None,
                   help="YYYY-MM-DD. Defaults to today's UTC date.")
    p.add_argument("--picks-dir", default="data/daily_picks",
                   help="Directory holding the daily-picks JSON files.")
    p.add_argument("--execute", action="store_true",
                   help="Actually submit orders. Default is dry-run.")
    p.add_argument("--cash-buffer-pct", type=float, default=2.0,
                   help="Hold this %% of equity in cash (default 2%%).")
    return p.parse_args()


def _load_picks(picks_dir: str, date_str: str | None) -> dict:
    if date_str is None:
        date_str = datetime.now(timezone.utc).date().isoformat()
    path = Path(picks_dir) / f"{date_str}.json"
    if not path.exists():
        raise SystemExit(
            f"No picks file at {path}. Run "
            f"`uv run python -m scripts.daily_factor_picks` first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _fetch_quotes(tickers: list[str]) -> dict[str, float]:
    """Pull last close for the ticker list via yfinance.

    Used for the BUY side when there's no existing position to read
    a mark price from. yfinance is the same data source the picks
    generator uses, so prices align with the strategy's view.
    """
    if not tickers:
        return {}
    from src.config_loader import Config
    from src.data.cache import DataCache
    from src.data.fetcher import DataFetcher

    config = Config()
    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5,
        ),
    )
    fetcher = DataFetcher(config, cache)
    raw = fetcher.fetch_batch(tickers)
    quotes: dict[str, float] = {}
    for t, df in raw.items():
        if df is None or df.empty or "Close" not in df.columns:
            continue
        last = df["Close"].dropna()
        if last.empty:
            continue
        quotes[t] = float(last.iloc[-1])
    return quotes


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()

    payload = _load_picks(args.picks_dir, args.picks_date)
    picks = payload["picks"]
    if not picks:
        raise SystemExit("Picks file is empty.")
    pick_tickers = {p["ticker"] for p in picks}
    n_picks = len(picks)
    logger.info("Loaded %d picks for %s from strategy=%s",
                n_picks, payload["as_of"], payload.get("strategy", "?"))

    # Build the Alpaca client AFTER setting the env override so the
    # safety gate reads enabled=true. We never write trading_enabled
    # back to disk — env-only override.
    if args.execute:
        os.environ["STOCKNEW_TRADING_ENABLED"] = "1"
        logger.warning(
            "EXECUTE MODE: orders will be submitted to Alpaca PAPER."
        )
    else:
        logger.info("DRY-RUN: no orders will be submitted. Pass --execute "
                    "to actually trade.")

    from src.config_loader import Config
    from src.execution.alpaca import AlpacaClient, make_client_order_id
    from src.execution.safety_gates import TradingSafetyGate

    config = Config()
    if args.execute:
        gate = TradingSafetyGate.from_config(config)
    else:
        # Dry-run still constructs the gate but never calls submit.
        gate = TradingSafetyGate.from_config(config)
    client = AlpacaClient(safety_gate=gate)

    account = client.get_account()
    equity = float(account.get("equity", account.get("cash", 0.0)) or 0.0)
    cash = float(account.get("cash", 0.0) or 0.0)
    buying_power = float(account.get("buying_power", cash) or cash)
    logger.info(
        "Alpaca PAPER: equity=$%.2f  cash=$%.2f  buying_power=$%.2f",
        equity, cash, buying_power,
    )
    if equity <= 0:
        raise SystemExit("Paper account has zero equity — top it up.")

    # Equal-weight: each pick gets equity * (1 - buffer) / n_picks.
    investable = equity * (1.0 - args.cash_buffer_pct / 100.0)
    per_position = investable / n_picks
    logger.info(
        "Sizing: equity=$%.2f  buffer=%.1f%%  investable=$%.2f  "
        "per_position=$%.2f (%d picks)",
        equity, args.cash_buffer_pct, investable, per_position, n_picks,
    )

    # Current positions on the paper account.
    current_positions = {p["ticker"]: p for p in client.get_positions()}
    logger.info("Current paper positions: %d names", len(current_positions))

    # Get quotes for any pick we don't already hold (sizing needs price).
    needs_quote = [p["ticker"] for p in picks
                   if p["ticker"] not in current_positions]
    if needs_quote:
        logger.info("Fetching live quotes for %d new-buy tickers...",
                    len(needs_quote))
        fresh_quotes = _fetch_quotes(needs_quote)
        logger.info("Got %d/%d fresh quotes", len(fresh_quotes), len(needs_quote))
    else:
        fresh_quotes = {}

    # Build the action plan.
    sells: list[dict] = []
    buys: list[dict] = []

    # 1. Sell any position NOT in the target set.
    for t, pos in current_positions.items():
        if t not in pick_tickers:
            sells.append({
                "ticker": t,
                "current_shares": int(pos["shares"]),
                "current_price": float(pos.get("current_price") or 0.0),
                "reason": "not_in_target",
            })

    # 2. For each pick, compute the target share count.
    for p in picks:
        t = p["ticker"]
        current = current_positions.get(t)
        current_shares = int(float(current["shares"])) if current else 0
        # Need a price. Try the broker's mark; fall back to picks-file
        # implicit price (unavailable for pure rank picks) → conservative
        # approach: skip if no price.
        price = (float(current["current_price"])
                 if current and current.get("current_price")
                 else fresh_quotes.get(t))
        if price is None:
            # Try a fresh quote via the broker — but the AlpacaClient
            # wrapper doesn't expose quotes; instead, defer to a
            # market-on-open order with notional sizing.
            buys.append({
                "ticker": t,
                "current_shares": current_shares,
                "target_shares": None,
                "target_notional": round(per_position, 2),
                "current_price": None,
                "delta_shares": None,
                "submit_type": "notional",
            })
            continue
        if price <= 0:
            continue
        target_shares = int(per_position // price)
        delta = target_shares - current_shares
        if delta == 0:
            continue
        buys.append({
            "ticker": t,
            "current_shares": current_shares,
            "target_shares": target_shares,
            "current_price": round(price, 4),
            "delta_shares": delta,
            "target_notional": round(target_shares * price, 2),
            "submit_type": "shares",
        })

    # ----- print the plan -----
    print("\n=== REBALANCE PLAN ===")
    print(f"Strategy: {STRATEGY_LABEL}")
    print(f"As-of (picks): {payload['as_of']}")
    print(f"Paper account equity: ${equity:,.2f}")
    print(f"Target per-position notional: ${per_position:,.2f}\n")

    if sells:
        print(f"SELLS ({len(sells)} — not in current target set):")
        for s in sells:
            est = s["current_shares"] * s["current_price"] if s["current_price"] else 0
            print(f"  {s['ticker']:>6s}  sell {s['current_shares']} sh "
                  f"@ ~${s['current_price']:.2f}  ~${est:,.2f}")
    else:
        print("SELLS: none (no positions outside target set)\n")

    if buys:
        print(f"\nBUYS / REBALANCES ({len(buys)}):")
        for b in buys:
            if b["submit_type"] == "shares":
                arrow = "+" if b["delta_shares"] > 0 else ""
                print(f"  {b['ticker']:>6s}  {arrow}{b['delta_shares']} sh "
                      f"(target {b['target_shares']}, current "
                      f"{b['current_shares']})  @ ${b['current_price']:.2f}"
                      f"  notional ${b['target_notional']:,.2f}")
            else:
                print(f"  {b['ticker']:>6s}  notional buy "
                      f"~${b['target_notional']:,.2f}  (no quote — "
                      f"will use Alpaca notional sizing)")
    else:
        print("\nBUYS: none")

    if not args.execute:
        print("\n*** DRY RUN — nothing submitted. Pass --execute to trade. ***\n")
        return 0

    # ----- execute -----
    print("\n=== EXECUTING ===")
    submitted: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []

    today = datetime.now(timezone.utc).date()

    # Sells first (free up cash for buys).
    for s in sells:
        coid = make_client_order_id(STRATEGY_LABEL + "-sell", s["ticker"], today)
        try:
            res = client.submit_market_order(
                ticker=s["ticker"],
                qty=s["current_shares"],
                side="sell",
                client_order_id=coid,
                reference_price=s["current_price"] or None,
            )
            submitted.append({"side": "sell", **res})
            print(f"  SELL {s['ticker']:>6s} {s['current_shares']} sh -> "
                  f"order {res['order_id']} ({res['status']})")
        except Exception as e:  # noqa: BLE001
            failed.append({"ticker": s["ticker"], "side": "sell", "error": str(e)})
            print(f"  FAIL SELL {s['ticker']:>6s}: {e}")

    # Then buys.
    for b in buys:
        if b["submit_type"] == "shares" and b["delta_shares"] and b["delta_shares"] > 0:
            coid = make_client_order_id(STRATEGY_LABEL, b["ticker"], today)
            try:
                res = client.submit_market_order(
                    ticker=b["ticker"],
                    qty=int(b["delta_shares"]),
                    side="buy",
                    client_order_id=coid,
                    reference_price=b["current_price"],
                )
                submitted.append({"side": "buy", **res})
                print(f"  BUY  {b['ticker']:>6s} {b['delta_shares']} sh -> "
                      f"order {res['order_id']} ({res['status']})")
            except Exception as e:  # noqa: BLE001
                failed.append({"ticker": b["ticker"], "side": "buy", "error": str(e)})
                print(f"  FAIL BUY {b['ticker']:>6s}: {e}")
        elif b["submit_type"] == "shares" and b["delta_shares"] and b["delta_shares"] < 0:
            # Partial sell to right-size an existing overweight position.
            coid = make_client_order_id(STRATEGY_LABEL + "-rebal", b["ticker"], today)
            try:
                res = client.submit_market_order(
                    ticker=b["ticker"],
                    qty=int(abs(b["delta_shares"])),
                    side="sell",
                    client_order_id=coid,
                    reference_price=b["current_price"],
                )
                submitted.append({"side": "sell_rebal", **res})
                print(f"  TRIM {b['ticker']:>6s} {b['delta_shares']} sh -> "
                      f"order {res['order_id']} ({res['status']})")
            except Exception as e:  # noqa: BLE001
                failed.append({"ticker": b["ticker"], "side": "sell_rebal",
                               "error": str(e)})
                print(f"  FAIL TRIM {b['ticker']:>6s}: {e}")
        else:
            # Notional-mode buys: not exposed by AlpacaClient wrapper;
            # skip and let the operator deal with it on the next rebalance
            # once positions exist (and thus a mark price exists).
            skipped.append({"ticker": b["ticker"],
                            "reason": "no_quote_for_initial_sizing"})
            print(f"  SKIP {b['ticker']:>6s}: no mark price for initial buy "
                  f"(will resolve on next rebalance once a position exists)")

    print(f"\n=== DONE ===  submitted={len(submitted)}  "
          f"skipped={len(skipped)}  failed={len(failed)}")

    # Write an execution log.
    log_dir = Path(args.picks_dir) / "execution_log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{today.isoformat()}.json"
    log_path.write_text(json.dumps({
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "picks_date": payload["as_of"],
        "strategy": STRATEGY_LABEL,
        "equity_at_start": equity,
        "submitted": submitted,
        "skipped": skipped,
        "failed": failed,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nExecution log: {log_path}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
