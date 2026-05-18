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
    p.add_argument("--skip-sanity", action="store_true",
                   help="Bypass the pre-trade LLM sanity gate. NOT RECOMMENDED "
                        "for live; the gate is what catches one-off catalysts "
                        "(M&A, takeover) before they land as orders.")
    p.add_argument("--sanity-mode", choices=("auto", "mock", "live"),
                   default="auto",
                   help="Sanity-check dispatch: auto (use live if key "
                        "available, else mock), mock (force rule-based), "
                        "live (force LLM and fail loudly without key).")
    p.add_argument("--order-style", choices=("bracket", "market"),
                   default="bracket",
                   help="bracket (default) attaches an ATR-based stop + "
                        "take-profit to every BUY. market submits naked "
                        "market orders (legacy behaviour, NOT recommended).")
    p.add_argument("--atr-multiplier", type=float, default=2.0,
                   help="Stop = entry - atr_multiplier * ATR14 (default 2.0).")
    p.add_argument("--risk-reward", type=float, default=3.0,
                   help="Take-profit = entry + RR * (entry - stop) (default 3.0).")
    p.add_argument("--confirm", action="store_true",
                   help="With --execute, force a Y/N prompt before submitting. "
                        "Strongly recommended interactively. Skipped in cron.")
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


def _fetch_quotes(
    tickers: list[str],
) -> tuple[dict[str, float], dict[str, "pd.DataFrame"]]:
    """Pull last close + OHLC history for the ticker list via yfinance.

    The OHLC frames are needed for ATR-based stop sizing on the BUY side.
    yfinance is the same data source the picks generator uses, so prices
    align with the strategy's view.

    Returns ``(quotes, ohlc_by_ticker)`` — quotes is last-close per ticker;
    ohlc_by_ticker holds the full DataFrame for ATR computation.
    """
    if not tickers:
        return {}, {}
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
    ohlc: dict[str, pd.DataFrame] = {}
    for t, df in raw.items():
        if df is None or df.empty or "Close" not in df.columns:
            continue
        last = df["Close"].dropna()
        if last.empty:
            continue
        quotes[t] = float(last.iloc[-1])
        ohlc[t] = df
    return quotes, ohlc


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
    logger.info("Loaded %d picks for %s from strategy=%s",
                len(picks), payload["as_of"], payload.get("strategy", "?"))

    # ─── Pre-trade LLM sanity gate ──────────────────────────────────────
    # Asymmetric trust: REJECT removes; CAUTION warns. SKIP (gate error)
    # is treated as REJECT — "when in doubt, don't trade".
    sanity_summary: dict = {"applied": False, "kept": [], "rejected": [],
                            "cautioned": [], "outcomes": {}}
    if not args.skip_sanity:
        from src.research_agent.sanity_gate import gate_picks_sync, is_available

        if args.sanity_mode == "live" and not is_available():
            raise SystemExit(
                "--sanity-mode=live requires ANTHROPIC_API_KEY. "
                "Either set the key or rerun with --sanity-mode=mock."
            )
        logger.info("Running sanity gate (mode=%s) on %d picks...",
                    args.sanity_mode, len(picks))
        result = gate_picks_sync(
            picks=picks, mode=args.sanity_mode, action="BUY",
        )
        sanity_summary = {
            "applied": True,
            "mode": args.sanity_mode,
            "kept": result.kept,
            "rejected": result.rejected,
            "cautioned": result.cautioned,
            "outcomes": {t: {
                "verdict": o.verdict,
                "reason": o.reason,
                "confidence": o.check.confidence if o.check else None,
                "model": o.check.model_used if o.check else None,
                "mocked": o.check.mocked if o.check else None,
            } for t, o in result.outcomes.items()},
        }
        if result.rejected:
            logger.warning(
                "Sanity gate REJECTED %d picks: %s",
                len(result.rejected), ", ".join(result.rejected),
            )
        if result.cautioned:
            logger.warning(
                "Sanity gate CAUTIONED %d picks (kept): %s",
                len(result.cautioned), ", ".join(result.cautioned),
            )
        picks = [p for p in picks if p["ticker"] in set(result.kept)]
        if not picks:
            raise SystemExit(
                "Sanity gate rejected every pick. Nothing to trade. "
                "Investigate the verdicts above; rerun with --skip-sanity "
                "only if you have a reason to override (you should not)."
            )
    else:
        logger.warning(
            "Sanity gate BYPASSED via --skip-sanity. Picks reach the "
            "broker unfiltered. This is the legacy behaviour and is "
            "NOT recommended for live trading."
        )

    pick_tickers = {p["ticker"] for p in picks}
    n_picks = len(picks)
    logger.info("Post-sanity: %d picks proceeding to rebalance plan", n_picks)

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

    # Get quotes + OHLC for any pick we don't already hold (sizing needs
    # price; ATR bracket sizing needs OHLC history).
    needs_quote = [p["ticker"] for p in picks
                   if p["ticker"] not in current_positions]
    if needs_quote:
        logger.info("Fetching live quotes for %d new-buy tickers...",
                    len(needs_quote))
        fresh_quotes, fresh_ohlc = _fetch_quotes(needs_quote)
        logger.info("Got %d/%d fresh quotes", len(fresh_quotes), len(needs_quote))
    else:
        fresh_quotes, fresh_ohlc = {}, {}

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

    # 2. For each pick, compute the target share count + bracket levels.
    from src.execution.risk_sizing import (
        atr_bracket_levels, percentage_bracket_levels,
    )

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
            # The script REFUSES notional sizing for live orders when
            # bracket mode is required — bracket orders need a known
            # qty + price for stop/TP. Surface the gap loudly instead of
            # silently deferring (the prior behaviour that hid stale
            # tickers for weeks).
            buys.append({
                "ticker": t,
                "current_shares": current_shares,
                "target_shares": None,
                "target_notional": round(per_position, 2),
                "current_price": None,
                "delta_shares": None,
                "submit_type": "skip_no_price",
                "skip_reason": "no_price_for_bracket_sizing",
            })
            continue
        if price <= 0:
            continue
        target_shares = int(per_position // price)
        delta = target_shares - current_shares
        if delta == 0:
            continue

        # Bracket levels (only used for new buys; sells/trims close
        # existing positions and don't need new stops).
        bracket: dict | None = None
        if args.order_style == "bracket" and delta > 0:
            ohlc = fresh_ohlc.get(t)
            levels = None
            if ohlc is not None and not ohlc.empty:
                levels = atr_bracket_levels(
                    entry=price, ohlc=ohlc,
                    atr_multiplier=args.atr_multiplier,
                    risk_reward=args.risk_reward,
                )
            if levels is None:
                levels = percentage_bracket_levels(
                    entry=price, risk_reward=args.risk_reward,
                )
            if levels is not None:
                bracket = {
                    "stop_loss": levels.stop,
                    "take_profit": levels.take_profit,
                    "basis": levels.basis,
                }

        buys.append({
            "ticker": t,
            "current_shares": current_shares,
            "target_shares": target_shares,
            "current_price": round(price, 4),
            "delta_shares": delta,
            "target_notional": round(target_shares * price, 2),
            "submit_type": "shares",
            "bracket": bracket,
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
                bracket_str = ""
                if b.get("bracket"):
                    bk = b["bracket"]
                    bracket_str = (
                        f"  stop ${bk['stop_loss']:.2f} / TP "
                        f"${bk['take_profit']:.2f} ({bk['basis']})"
                    )
                print(f"  {b['ticker']:>6s}  {arrow}{b['delta_shares']} sh "
                      f"(target {b['target_shares']}, current "
                      f"{b['current_shares']})  @ ${b['current_price']:.2f}"
                      f"  notional ${b['target_notional']:,.2f}{bracket_str}")
            elif b["submit_type"] == "skip_no_price":
                print(f"  {b['ticker']:>6s}  SKIP — no quote available; "
                      f"bracket sizing requires a price ({b.get('skip_reason')})")
            else:
                print(f"  {b['ticker']:>6s}  notional buy "
                      f"~${b['target_notional']:,.2f}  (no quote — "
                      f"will use Alpaca notional sizing)")
    else:
        print("\nBUYS: none")

    if sanity_summary.get("applied"):
        rejected = sanity_summary.get("rejected") or []
        cautioned = sanity_summary.get("cautioned") or []
        if rejected or cautioned:
            print(f"\nSANITY GATE ({sanity_summary.get('mode')}):  "
                  f"rejected={len(rejected)} cautioned={len(cautioned)}")
            for tk in rejected:
                o = sanity_summary["outcomes"].get(tk, {})
                print(f"  REJECT {tk:>6s}: {o.get('reason', '')}")
            for tk in cautioned:
                o = sanity_summary["outcomes"].get(tk, {})
                print(f"  CAUTION {tk:>6s}: {o.get('reason', '')}")

    if not args.execute:
        print("\n*** DRY RUN — nothing submitted. Pass --execute to trade. ***\n")
        return 0

    if args.confirm and sys.stdin.isatty():
        n_buys = sum(1 for b in buys if b["submit_type"] == "shares"
                     and b.get("delta_shares") and b["delta_shares"] > 0)
        prompt = (
            f"\n*** CONFIRM ***  About to submit {len(sells)} SELLs + "
            f"{n_buys} BUYs to Alpaca PAPER. Continue? [y/N]: "
        )
        response = input(prompt).strip().lower()
        if response not in ("y", "yes"):
            print("Aborted by operator.")
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
            bracket = b.get("bracket")
            try:
                if args.order_style == "bracket" and bracket is not None:
                    res = client.submit_bracket_order(
                        ticker=b["ticker"],
                        qty=int(b["delta_shares"]),
                        take_profit_price=bracket["take_profit"],
                        stop_loss_price=bracket["stop_loss"],
                        side="buy",
                        client_order_id=coid,
                    )
                    submitted.append({
                        "side": "buy_bracket",
                        "stop_loss": bracket["stop_loss"],
                        "take_profit": bracket["take_profit"],
                        "basis": bracket["basis"],
                        **res,
                    })
                    print(f"  BUY  {b['ticker']:>6s} {b['delta_shares']} sh "
                          f"stop ${bracket['stop_loss']:.2f} TP "
                          f"${bracket['take_profit']:.2f} ({bracket['basis']}) "
                          f"-> order {res['order_id']} ({res['status']})")
                elif args.order_style == "bracket" and bracket is None:
                    # Refuse: bracket mode requested but levels unavailable.
                    failed.append({
                        "ticker": b["ticker"], "side": "buy",
                        "error": "bracket_levels_unavailable",
                    })
                    print(f"  FAIL BUY {b['ticker']:>6s}: bracket levels "
                          f"unavailable; refusing naked market order")
                else:
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
            # No-price buys are surfaced as failures, not silent skips
            # (the legacy behaviour hid stale tickers for weeks). The
            # operator should explicitly investigate why the data feed
            # isn't returning a quote — halted, delisted, ticker change,
            # cache poisoning all look the same here.
            skipped.append({
                "ticker": b["ticker"],
                "reason": b.get("skip_reason") or "no_quote_or_bracket",
            })
            print(f"  SKIP {b['ticker']:>6s}: {b.get('skip_reason') or 'no_quote_or_bracket'} "
                  f"— investigate before next rebalance")

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
        "sanity_gate": sanity_summary,
        "order_style": args.order_style,
        "submitted": submitted,
        "skipped": skipped,
        "failed": failed,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nExecution log: {log_path}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
