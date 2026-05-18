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
    p.add_argument("--long-short", action=argparse.BooleanOptionalAction,
                   default=None,
                   help="Run as long-short. Default: auto-detect from the "
                        "picks JSON's 'long_short' key. Set explicitly to "
                        "override (e.g., --no-long-short forces long-only "
                        "even on an LS picks file).")
    p.add_argument("--short-cash-buffer-pct", type=float, default=2.0,
                   help="Held in cash on the SHORT side too (default 2%%). "
                        "Long and short halves each apply this buffer.")
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
    longs = payload["picks"]
    shorts = payload.get("shorts") or []
    # Resolve long-short mode: CLI overrides JSON; JSON default False.
    if args.long_short is None:
        long_short_mode = bool(payload.get("long_short", False))
    else:
        long_short_mode = bool(args.long_short)
    # If LS mode requested but no shorts present, refuse rather than
    # silently degrade to long-only.
    if long_short_mode and not shorts:
        raise SystemExit(
            "--long-short requested but picks file has no 'shorts' set. "
            "Generate with: python -m scripts.daily_factor_picks --long-short"
        )
    if not long_short_mode:
        shorts = []
    if not longs:
        raise SystemExit("Picks file's longs list is empty.")
    logger.info(
        "Loaded %d longs%s for %s from strategy=%s",
        len(longs),
        f" + {len(shorts)} shorts" if long_short_mode else "",
        payload["as_of"], payload.get("strategy", "?"),
    )

    # ─── Pre-trade LLM sanity gate ──────────────────────────────────────
    # Asymmetric trust: REJECT removes; CAUTION warns. SKIP (gate error)
    # is treated as REJECT — "when in doubt, don't trade". Run separately
    # on longs (action=BUY) and shorts (action=SHORT) so the prompt
    # framing matches.
    sanity_summary: dict = {"applied": False, "kept": [], "rejected": [],
                            "cautioned": [], "outcomes": {}}
    if not args.skip_sanity:
        from src.research_agent.sanity_gate import gate_picks_sync, is_available

        if args.sanity_mode == "live" and not is_available():
            raise SystemExit(
                "--sanity-mode=live requires ANTHROPIC_API_KEY. "
                "Either set the key or rerun with --sanity-mode=mock."
            )
        logger.info(
            "Running sanity gate (mode=%s) on %d longs%s...",
            args.sanity_mode, len(longs),
            f" + {len(shorts)} shorts" if long_short_mode else "",
        )
        long_result = gate_picks_sync(
            picks=longs, mode=args.sanity_mode, action="BUY",
        )
        short_result = (
            gate_picks_sync(picks=shorts, mode=args.sanity_mode, action="SHORT")
            if long_short_mode and shorts
            else None
        )

        def _outcome_dict(res) -> dict:
            return {t: {
                "verdict": o.verdict,
                "reason": o.reason,
                "confidence": o.check.confidence if o.check else None,
                "model": o.check.model_used if o.check else None,
                "mocked": o.check.mocked if o.check else None,
            } for t, o in res.outcomes.items()}

        sanity_summary = {
            "applied": True,
            "mode": args.sanity_mode,
            "long_kept": long_result.kept,
            "long_rejected": long_result.rejected,
            "long_cautioned": long_result.cautioned,
            "long_outcomes": _outcome_dict(long_result),
            "short_kept": short_result.kept if short_result else [],
            "short_rejected": short_result.rejected if short_result else [],
            "short_cautioned": short_result.cautioned if short_result else [],
            "short_outcomes": (
                _outcome_dict(short_result) if short_result else {}
            ),
        }
        if long_result.rejected:
            logger.warning(
                "Sanity gate REJECTED %d longs: %s",
                len(long_result.rejected), ", ".join(long_result.rejected),
            )
        if short_result and short_result.rejected:
            logger.warning(
                "Sanity gate REJECTED %d shorts: %s",
                len(short_result.rejected), ", ".join(short_result.rejected),
            )

        kept_longs = set(long_result.kept)
        kept_shorts = set(short_result.kept) if short_result else set()
        longs = [p for p in longs if p["ticker"] in kept_longs]
        shorts = [p for p in shorts if p["ticker"] in kept_shorts]

        if not longs and not shorts:
            raise SystemExit(
                "Sanity gate rejected every pick. Nothing to trade. "
                "Investigate the verdicts above; rerun with --skip-sanity "
                "only if you have a reason to override (you should not)."
            )
    else:
        logger.warning(
            "Sanity gate BYPASSED via --skip-sanity. Picks reach the "
            "broker unfiltered. NOT recommended for live trading."
        )

    long_tickers = {p["ticker"] for p in longs}
    short_tickers = {p["ticker"] for p in shorts}
    target_tickers = long_tickers | short_tickers
    n_longs = len(longs)
    n_shorts = len(shorts)
    logger.info(
        "Post-sanity: %d longs + %d shorts → rebalance plan",
        n_longs, n_shorts,
    )

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

    # Sizing. Long-only: all equity on the long side. Long-short: half
    # to each side (gross ~1.0x, net ~0). Each side applies its own
    # cash buffer.
    if long_short_mode:
        long_capital = equity * 0.5 * (1.0 - args.cash_buffer_pct / 100.0)
        short_capital = equity * 0.5 * (1.0 - args.short_cash_buffer_pct / 100.0)
    else:
        long_capital = equity * (1.0 - args.cash_buffer_pct / 100.0)
        short_capital = 0.0
    per_long = long_capital / max(1, n_longs)
    per_short = short_capital / max(1, n_shorts) if n_shorts else 0.0
    logger.info(
        "Sizing: equity=$%.2f long_capital=$%.2f short_capital=$%.2f "
        "per_long=$%.2f per_short=$%.2f",
        equity, long_capital, short_capital, per_long, per_short,
    )

    # Current positions on the paper account. Alpaca returns positive
    # qty for longs, negative for shorts.
    current_positions = {p["ticker"]: p for p in client.get_positions()}
    logger.info("Current paper positions: %d names", len(current_positions))

    # Quote + OHLC fetch for any target ticker (long OR short) we don't
    # already hold. Sizing + bracket levels need both.
    needs_quote = [
        t for t in target_tickers
        if t not in current_positions
    ]
    if needs_quote:
        logger.info("Fetching live quotes for %d new-position tickers...",
                    len(needs_quote))
        fresh_quotes, fresh_ohlc = _fetch_quotes(needs_quote)
        logger.info("Got %d/%d fresh quotes", len(fresh_quotes), len(needs_quote))
    else:
        fresh_quotes, fresh_ohlc = {}, {}

    # Build the action plan.
    closes: list[dict] = []          # close-outs (cover shorts OR sell longs)
    actions: list[dict] = []         # opens/resizes — carries 'side' field

    # 1. Close any position NOT in either target set. ``current_shares``
    # carries the sign (negative = current short → must BUY to cover).
    for t, pos in current_positions.items():
        if t in target_tickers:
            continue
        current_shares = int(float(pos["shares"]))
        if current_shares == 0:
            continue
        closes.append({
            "ticker": t,
            "current_shares": current_shares,
            "side": "sell" if current_shares > 0 else "cover",
            "current_price": float(pos.get("current_price") or 0.0),
            "reason": "not_in_target",
        })

    # 2. For each target, compute target_shares (sign-aware) + bracket.
    from src.execution.risk_sizing import (
        atr_bracket_levels, percentage_bracket_levels,
        short_atr_bracket_levels, short_percentage_bracket_levels,
    )

    def _resolve_levels(t: str, price: float, is_long: bool):
        ohlc = fresh_ohlc.get(t)
        levels = None
        if is_long:
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
        else:
            if ohlc is not None and not ohlc.empty:
                levels = short_atr_bracket_levels(
                    entry=price, ohlc=ohlc,
                    atr_multiplier=args.atr_multiplier,
                    risk_reward=args.risk_reward,
                )
            if levels is None:
                levels = short_percentage_bracket_levels(
                    entry=price, risk_reward=args.risk_reward,
                )
        return levels

    def _build_action(p: dict, is_long: bool) -> dict | None:
        t = p["ticker"]
        current = current_positions.get(t)
        current_shares = int(float(current["shares"])) if current else 0
        price = (float(current["current_price"])
                 if current and current.get("current_price")
                 else fresh_quotes.get(t))
        if price is None:
            return {
                "ticker": t,
                "side": "long" if is_long else "short",
                "current_shares": current_shares,
                "target_shares": None,
                "current_price": None,
                "delta_shares": None,
                "submit_type": "skip_no_price",
                "skip_reason": "no_price_for_bracket_sizing",
            }
        if price <= 0:
            return None
        per = per_long if is_long else per_short
        if per <= 0:
            return None
        magnitude = int(per // price)
        target_shares = magnitude if is_long else -magnitude
        delta = target_shares - current_shares
        if delta == 0:
            return None
        bracket: dict | None = None
        # Bracket levels apply only to OPENING a new position (delta in
        # the direction of the target). Resizes / partial closes don't
        # spawn new brackets — the existing position's bracket (if any)
        # already covers it.
        opening = (is_long and delta > 0) or ((not is_long) and delta < 0)
        if args.order_style == "bracket" and opening:
            levels = _resolve_levels(t, price, is_long)
            if levels is not None:
                bracket = {
                    "stop_loss": levels.stop,
                    "take_profit": levels.take_profit,
                    "basis": levels.basis,
                }
        return {
            "ticker": t,
            "side": "long" if is_long else "short",
            "current_shares": current_shares,
            "target_shares": target_shares,
            "current_price": round(price, 4),
            "delta_shares": delta,
            "target_notional": round(abs(target_shares) * price, 2),
            "submit_type": "shares",
            "bracket": bracket,
        }

    for p in longs:
        act = _build_action(p, is_long=True)
        if act is not None:
            actions.append(act)
    for p in shorts:
        act = _build_action(p, is_long=False)
        if act is not None:
            actions.append(act)

    # Back-compat aliases for the rest of the script (which iterates
    # over `buys`/`sells` and prints them). The semantics now: `sells`
    # = closes (sell longs / cover shorts); `buys` = open/resize actions
    # regardless of direction.
    sells = closes
    buys = actions

    # ----- print the plan -----
    print("\n=== REBALANCE PLAN ===")
    label = STRATEGY_LABEL + ("-ls" if long_short_mode else "")
    print(f"Strategy: {label}")
    print(f"As-of (picks): {payload['as_of']}")
    print(f"Paper account equity: ${equity:,.2f}")
    if long_short_mode:
        print(f"Long capital: ${long_capital:,.2f} (per-long ${per_long:,.2f})")
        print(f"Short capital: ${short_capital:,.2f} "
              f"(per-short ${per_short:,.2f})\n")
    else:
        print(f"Target per-position notional: ${per_long:,.2f}\n")

    if sells:
        print(f"CLOSES ({len(sells)} — positions not in current target set):")
        for s in sells:
            est = abs(s["current_shares"]) * s["current_price"] \
                if s["current_price"] else 0
            verb = s["side"]
            print(f"  {s['ticker']:>6s}  {verb} {abs(s['current_shares'])} sh "
                  f"@ ~${s['current_price']:.2f}  ~${est:,.2f}")
    else:
        print("CLOSES: none\n")

    longs_in_plan = [b for b in buys if b["side"] == "long"]
    shorts_in_plan = [b for b in buys if b["side"] == "short"]

    def _print_action(b: dict) -> None:
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
            print(f"  {b['ticker']:>6s}  SKIP — no quote available "
                  f"({b.get('skip_reason')})")

    if longs_in_plan:
        print(f"\nLONGS ({len(longs_in_plan)}):")
        for b in longs_in_plan:
            _print_action(b)
    elif not long_short_mode:
        print("\nLONGS: none")

    if shorts_in_plan:
        print(f"\nSHORTS ({len(shorts_in_plan)}):")
        for b in shorts_in_plan:
            _print_action(b)
    elif long_short_mode:
        print("\nSHORTS: none")

    if sanity_summary.get("applied"):
        long_rej = sanity_summary.get("long_rejected") or []
        long_cau = sanity_summary.get("long_cautioned") or []
        short_rej = sanity_summary.get("short_rejected") or []
        short_cau = sanity_summary.get("short_cautioned") or []
        any_flag = bool(long_rej or long_cau or short_rej or short_cau)
        if any_flag:
            print(f"\nSANITY GATE ({sanity_summary.get('mode')}):  "
                  f"long rejected={len(long_rej)}/cautioned={len(long_cau)}; "
                  f"short rejected={len(short_rej)}/cautioned={len(short_cau)}")
            long_out = sanity_summary.get("long_outcomes") or {}
            short_out = sanity_summary.get("short_outcomes") or {}
            for tk in long_rej:
                print(f"  REJECT LONG  {tk:>6s}: "
                      f"{long_out.get(tk, {}).get('reason', '')}")
            for tk in long_cau:
                print(f"  CAUTION LONG {tk:>6s}: "
                      f"{long_out.get(tk, {}).get('reason', '')}")
            for tk in short_rej:
                print(f"  REJECT SHORT {tk:>6s}: "
                      f"{short_out.get(tk, {}).get('reason', '')}")
            for tk in short_cau:
                print(f"  CAUTION SHORT {tk:>6s}: "
                      f"{short_out.get(tk, {}).get('reason', '')}")

    if not args.execute:
        print("\n*** DRY RUN — nothing submitted. Pass --execute to trade. ***\n")
        return 0

    if args.confirm and sys.stdin.isatty():
        n_opens = sum(
            1 for b in buys
            if b["submit_type"] == "shares" and b.get("delta_shares")
            and (
                (b["side"] == "long" and b["delta_shares"] > 0)
                or (b["side"] == "short" and b["delta_shares"] < 0)
            )
        )
        prompt = (
            f"\n*** CONFIRM ***  About to submit {len(sells)} CLOSES + "
            f"{n_opens} OPENs to Alpaca PAPER. Continue? [y/N]: "
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

    # Closes first (free up margin/cash for new opens).
    for s in sells:
        cs = s["current_shares"]
        if cs == 0:
            continue
        broker_side = "sell" if cs > 0 else "buy"
        qty = abs(cs)
        coid = make_client_order_id(
            STRATEGY_LABEL + "-close", s["ticker"], today,
        )
        try:
            res = client.submit_market_order(
                ticker=s["ticker"],
                qty=qty,
                side=broker_side,
                client_order_id=coid,
                reference_price=s["current_price"] or None,
            )
            submitted.append({"side": "close_" + s["side"], **res})
            print(f"  CLOSE {s['ticker']:>6s} {s['side']:>5s} {qty} sh -> "
                  f"order {res['order_id']} ({res['status']})")
        except Exception as e:  # noqa: BLE001
            failed.append({"ticker": s["ticker"], "side": "close", "error": str(e)})
            print(f"  FAIL CLOSE {s['ticker']:>6s}: {e}")

    # Then opens / resizes. Side-aware: long opens via submit_bracket_order
    # side=buy; short opens via submit_bracket_order side=sell with
    # short-bracket levels (stop above entry, TP below).
    for b in buys:
        if b["submit_type"] != "shares":
            # No-price actions surface as failures, not silent skips.
            skipped.append({
                "ticker": b["ticker"],
                "side": b["side"],
                "reason": b.get("skip_reason") or "no_quote_or_bracket",
            })
            print(f"  SKIP {b['ticker']:>6s} {b['side']:>5s}: "
                  f"{b.get('skip_reason') or 'no_quote_or_bracket'} "
                  f"— investigate before next rebalance")
            continue
        delta = b.get("delta_shares") or 0
        if delta == 0:
            continue
        is_long = b["side"] == "long"
        opening = (is_long and delta > 0) or ((not is_long) and delta < 0)
        bracket = b.get("bracket")
        # COID namespace per side so a same-day re-run never collides
        # a long entry with a short entry on the same ticker.
        coid_ns = STRATEGY_LABEL + ("-long" if is_long else "-short")
        coid = make_client_order_id(coid_ns, b["ticker"], today)

        try:
            if opening and args.order_style == "bracket":
                if bracket is None:
                    failed.append({
                        "ticker": b["ticker"], "side": b["side"],
                        "error": "bracket_levels_unavailable",
                    })
                    print(f"  FAIL {b['side'].upper():>5s} {b['ticker']:>6s}: "
                          f"bracket levels unavailable; refusing naked order")
                    continue
                res = client.submit_bracket_order(
                    ticker=b["ticker"],
                    qty=abs(int(delta)),
                    take_profit_price=bracket["take_profit"],
                    stop_loss_price=bracket["stop_loss"],
                    side="buy" if is_long else "sell",
                    client_order_id=coid,
                )
                submitted.append({
                    "side": f"open_{b['side']}_bracket",
                    "stop_loss": bracket["stop_loss"],
                    "take_profit": bracket["take_profit"],
                    "basis": bracket["basis"],
                    **res,
                })
                verb = "BUY " if is_long else "SHORT"
                print(f"  {verb} {b['ticker']:>6s} {abs(delta)} sh "
                      f"stop ${bracket['stop_loss']:.2f} TP "
                      f"${bracket['take_profit']:.2f} ({bracket['basis']}) "
                      f"-> order {res['order_id']} ({res['status']})")
            else:
                # Resize / partial close — naked market order is fine
                # because we're not opening fresh risk; existing bracket
                # (if any) still covers the residual position.
                broker_side = "buy" if delta > 0 else "sell"
                res = client.submit_market_order(
                    ticker=b["ticker"],
                    qty=abs(int(delta)),
                    side=broker_side,
                    client_order_id=coid,
                    reference_price=b["current_price"],
                )
                submitted.append({
                    "side": f"resize_{b['side']}",
                    **res,
                })
                arrow = "+" if delta > 0 else ""
                print(f"  RESIZE {b['ticker']:>6s} {b['side']:>5s} "
                      f"{arrow}{delta} sh -> order {res['order_id']} "
                      f"({res['status']})")
        except Exception as e:  # noqa: BLE001
            failed.append({
                "ticker": b["ticker"], "side": b["side"], "error": str(e),
            })
            print(f"  FAIL {b['side'].upper():>5s} {b['ticker']:>6s}: {e}")

    print(f"\n=== DONE ===  submitted={len(submitted)}  "
          f"skipped={len(skipped)}  failed={len(failed)}")

    # Write an execution log.
    log_dir = Path(args.picks_dir) / "execution_log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{today.isoformat()}.json"
    log_path.write_text(json.dumps({
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "picks_date": payload["as_of"],
        "strategy": STRATEGY_LABEL + ("-ls" if long_short_mode else ""),
        "long_short_mode": long_short_mode,
        "equity_at_start": equity,
        "long_capital": long_capital,
        "short_capital": short_capital,
        "n_longs": n_longs,
        "n_shorts": n_shorts,
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
