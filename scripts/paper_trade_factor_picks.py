"""Send today's composite factor picks to Alpaca PAPER.

Reads the most recent ``data/daily_picks/YYYY-MM-DD.json``, computes
the equal-weight rebalance from current paper positions, and submits
market orders.

Default mode is **DRY RUN** -- it prints the plan but does NOT submit.
Pass ``--execute`` to actually place orders.

Safety
------
- Paper-only client (AlpacaClient is hard-coded to paper=True).
- Trading kill switch overridden via ``STOCKNEW_TRADING_ENABLED=1``
  for the lifetime of this process only -- no config edit.
- Deterministic client_order_ids: a re-run on the same UTC date is
  refused by Alpaca as a duplicate; no double-fills.
- The script DOES NOT touch positions outside the strategy's
  client_order_id namespace (i.e., it sells everything currently
  held, on the assumption that the paper account is dedicated to
  this strategy). Run on a clean paper account.

Usage
-----

    # Dry run (default) -- show the plan only:
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
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("paper_trade_factor_picks")

STRATEGY_LABEL = "factor_composite_d05_r63"


# ─── arg parsing ─────────────────────────────────────────────────────

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
    p.add_argument("--override-drift", action="store_true",
                   help="Proceed even when the drift detector returns FAIL. "
                        "By default we refuse to trade on a FAIL because it "
                        "means today's picks composition diverged from the "
                        "trailing baseline (factor-coverage collapse, "
                        "universe shrink, sector-cap break, etc.). Use this "
                        "ONLY when you've manually verified the cause.")
    p.add_argument("--override-sanity-errors", action="store_true",
                   help="Proceed even when the sanity gate had transport / "
                        "API errors (not LLM verdicts -- actual call failures). "
                        "Default refuses because the gate had its silent-mock "
                        "fallback removed: a failure now means the call broke, "
                        "not that the LLM is uncertain. Override ONLY for "
                        "known-transient issues.")
    p.add_argument("--override-kill-switch", action="store_true",
                   help="Proceed even when the live-α kill switch reports "
                        "TRIGGERED (60d rolling α vs SPY below threshold). "
                        "Default refuses. Override ONLY after manually "
                        "reviewing reports/kill_switch.json and deciding "
                        "the trigger is a transient drawdown, not a "
                        "regime/strategy failure.")
    p.add_argument("--retry-suffix", default="",
                   help="Appended to every client_order_id (e.g., 'v2') to "
                        "make today's IDs unique when re-running after a "
                        "flatten. Alpaca remembers cancelled order IDs "
                        "forever and rejects same-day re-submissions as "
                        "dupes; this suffix breaks the collision. Leave "
                        "blank for the normal idempotent path.")
    return p.parse_args()


# ─── picks loading ───────────────────────────────────────────────────

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


def _resolve_long_short_mode(args, payload: dict) -> bool:
    """CLI overrides JSON; JSON default False. Refuse LS mode if picks
    file has no shorts (silent degrade hides the misconfiguration)."""
    if args.long_short is None:
        mode = bool(payload.get("long_short", False))
    else:
        mode = bool(args.long_short)
    if mode and not (payload.get("shorts") or []):
        raise SystemExit(
            "--long-short requested but picks file has no 'shorts' set. "
            "Generate with: python -m scripts.daily_factor_picks --long-short"
        )
    return mode


def _fetch_quotes(
    tickers: list[str],
) -> tuple[dict[str, float], dict[str, pd.DataFrame]]:
    """Pull last close + OHLC history for the ticker list via yfinance.

    The OHLC frames are needed for ATR-based stop sizing on the BUY side.
    yfinance is the same data source the picks generator uses, so prices
    align with the strategy's view.

    Returns ``(quotes, ohlc_by_ticker)`` -- quotes is last-close per ticker;
    ohlc_by_ticker holds the full DataFrame for ATR computation.
    """
    if not tickers:
        return {}, {}
    from src.config_loader import Config
    from src.data.cache import DataCache
    from src.data.fetcher_factory import get_data_fetcher

    config = Config()
    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5,
        ),
    )
    fetcher = get_data_fetcher(config, cache)
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


# ─── pre-trade gates ─────────────────────────────────────────────────
# Implementations live in src/execution/pre_trade_gates.py so the
# orchestrator stays focused on plan-building + submission.
from src.execution.pre_trade_gates import (
    run_drift_gate as _run_drift_gate,
    run_kill_switch_gate as _run_kill_switch_gate_impl,
    run_sanity_gate as _run_sanity_gate,
)


def _run_kill_switch_gate(args) -> dict:
    """Thin shim that passes the script-local STRATEGY_LABEL to the gate."""
    return _run_kill_switch_gate_impl(args, STRATEGY_LABEL)


# ─── broker setup + sizing ───────────────────────────────────────────

def _open_alpaca_client():
    """Construct an Alpaca PAPER client + safety gate. Returns (client,
    account_dict). Equity is validated >0 before returning."""
    from src.config_loader import Config
    from src.execution.alpaca import AlpacaClient
    from src.execution.safety_gates import TradingSafetyGate

    config = Config()
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
        raise SystemExit("Paper account has zero equity -- top it up.")
    return client, {"equity": equity, "cash": cash, "buying_power": buying_power}


def _compute_sizing(
    args, equity: float, n_longs: int, n_shorts: int, long_short_mode: bool,
) -> dict:
    """Long-only: full equity on the long side. Long-short: half to each
    side (gross ~1.0x, net ~0). Each side applies its own cash buffer."""
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
    return {
        "long_capital": long_capital,
        "short_capital": short_capital,
        "per_long": per_long,
        "per_short": per_short,
    }


# ─── action plan ─────────────────────────────────────────────────────

def _resolve_bracket_levels(args, price: float, ohlc, is_long: bool):
    """ATR-based stop/take-profit, falling back to fixed-percentage if
    OHLC history is unusable."""
    from src.execution.risk_sizing import (
        atr_bracket_levels, percentage_bracket_levels,
        short_atr_bracket_levels, short_percentage_bracket_levels,
    )
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


def _build_one_action(
    args, p: dict, is_long: bool,
    current_positions: dict, fresh_quotes: dict, fresh_ohlc: dict,
    per_long: float, per_short: float, closes: list,
) -> dict | None:
    """Build the action dict for one pick. May append to ``closes`` if a
    position flip is required (current/target opposite signs)."""
    from src.execution.risk_sizing import is_position_flip, size_position

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
    plan = size_position(
        price=price, per_slot=per,
        current_shares=current_shares, is_long=is_long,
    )
    if plan.skip_reason is not None:
        # Operator-visible skip -- the alternative (silently sizing to 0
        # shares) was the high-price-short footgun that dropped COST
        # from a prior day's plan without any warning.
        return {
            "ticker": t,
            "side": "long" if is_long else "short",
            "current_shares": current_shares,
            "target_shares": plan.target_shares,
            "current_price": round(price, 4),
            "delta_shares": plan.delta_shares,
            "submit_type": "skip_no_size",
            "skip_reason": plan.skip_reason,
        }
    target_shares = plan.target_shares
    delta = plan.delta_shares
    if delta == 0:
        return None

    # Position flip: currently long, targeted short (or reverse). Alpaca
    # rejects a bracket sell on a name with existing long shares with
    # "bracket orders must be entry orders" -- the order isn't a clean
    # entry. Inject a market close into ``closes`` so the existing
    # position flattens FIRST, then the bracket entry submits from
    # flat. The closes loop runs before opens; flip-close fills are
    # polled before flip-entry submission in _submit_opens.
    flip_from = 0
    if is_position_flip(current_shares, target_shares):
        flip_from = current_shares
        closes.append({
            "ticker": t,
            "current_shares": current_shares,
            "side": "flip_long" if current_shares > 0 else "flip_short",
            "current_price": round(price, 4),
            "reason": (
                "flip_to_short" if target_shares < 0 else "flip_to_long"
            ),
        })
        # Treat the entry as a fresh entry from flat: target unchanged,
        # but the trade-size delta is now just the target magnitude.
        current_shares = 0
        delta = target_shares

    bracket: dict | None = None
    # Bracket levels apply only to OPENING a new position (delta in the
    # direction of the target). Resizes / partial closes don't spawn new
    # brackets -- the existing position's bracket (if any) already
    # covers it.
    opening = (is_long and delta > 0) or ((not is_long) and delta < 0)
    if args.order_style == "bracket" and opening:
        levels = _resolve_bracket_levels(args, price, fresh_ohlc.get(t), is_long)
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
        "flip_from_shares": flip_from,
        "target_shares": target_shares,
        "current_price": round(price, 4),
        "delta_shares": delta,
        "target_notional": round(abs(target_shares) * price, 2),
        "submit_type": "shares",
        "bracket": bracket,
    }


def _build_action_plan(
    args, longs: list[dict], shorts: list[dict],
    current_positions: dict, fresh_quotes: dict, fresh_ohlc: dict,
    per_long: float, per_short: float,
) -> tuple[list[dict], list[dict]]:
    """Returns (closes, actions). ``closes`` covers positions no longer
    in the target set AND flip-from-prior-side closes. ``actions`` has
    every open/resize, with a 'side' field."""
    target_tickers = (
        {p["ticker"] for p in longs} | {p["ticker"] for p in shorts}
    )

    closes: list[dict] = []
    # 1. Close any position NOT in either target set. ``current_shares``
    # carries the sign (negative = current short -> must BUY to cover).
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

    # 2. Build the sign-aware target action for each long + short pick.
    # _build_one_action appends to ``closes`` when a position flip is
    # detected.
    actions: list[dict] = []
    for p in longs:
        act = _build_one_action(
            args, p, True, current_positions, fresh_quotes, fresh_ohlc,
            per_long, per_short, closes,
        )
        if act is not None:
            actions.append(act)
    for p in shorts:
        act = _build_one_action(
            args, p, False, current_positions, fresh_quotes, fresh_ohlc,
            per_long, per_short, closes,
        )
        if act is not None:
            actions.append(act)
    return closes, actions


# ─── display ────────────────────────────────────────────────────────

def _print_action_line(b: dict) -> None:
    if b["submit_type"] == "shares":
        arrow = "+" if b["delta_shares"] > 0 else ""
        bracket_str = ""
        if b.get("bracket"):
            bk = b["bracket"]
            bracket_str = (
                f"  stop ${bk['stop_loss']:.2f} / TP "
                f"${bk['take_profit']:.2f} ({bk['basis']})"
            )
        # Flip note: when a pre-flip close was injected, current_shares
        # reads as 0 (post-virtual-close) but flip_from_shares shows
        # the actual prior position so the operator sees the intent.
        flip_str = ""
        if b.get("flip_from_shares"):
            flip_str = (
                f"  [FLIP from {b['flip_from_shares']:+d} -> "
                f"{b['target_shares']:+d}; close already queued]"
            )
        print(f"  {b['ticker']:>6s}  {arrow}{b['delta_shares']} sh "
              f"(target {b['target_shares']}, current "
              f"{b['current_shares']})  @ ${b['current_price']:.2f}"
              f"  notional ${b['target_notional']:,.2f}{bracket_str}"
              f"{flip_str}")
    elif b["submit_type"] == "skip_no_price":
        print(f"  {b['ticker']:>6s}  SKIP -- no quote available "
              f"({b.get('skip_reason')})")
    elif b["submit_type"] == "skip_no_size":
        print(f"  {b['ticker']:>6s}  SKIP @ ${b.get('current_price', 0):.2f}  "
              f"-- {b.get('skip_reason')}")


def _print_plan(
    payload: dict, sizing: dict, sells: list, buys: list,
    long_short_mode: bool, sanity_summary: dict,
) -> None:
    print("\n=== REBALANCE PLAN ===")
    label = STRATEGY_LABEL + ("-ls" if long_short_mode else "")
    print(f"Strategy: {label}")
    print(f"As-of (picks): {payload['as_of']}")
    equity = sizing.get("equity", 0.0)
    print(f"Paper account equity: ${equity:,.2f}")
    if long_short_mode:
        print(f"Long capital: ${sizing['long_capital']:,.2f} "
              f"(per-long ${sizing['per_long']:,.2f})")
        print(f"Short capital: ${sizing['short_capital']:,.2f} "
              f"(per-short ${sizing['per_short']:,.2f})\n")
    else:
        print(f"Target per-position notional: ${sizing['per_long']:,.2f}\n")

    if sells:
        n_flip = sum(1 for s in sells if s["side"].startswith("flip_"))
        n_drop = len(sells) - n_flip
        header = f"CLOSES ({len(sells)} -- {n_drop} dropped from target set"
        if n_flip:
            header += f", {n_flip} pre-flip"
        print(header + "):")
        for s in sells:
            est = abs(s["current_shares"]) * s["current_price"] \
                if s["current_price"] else 0
            side_label = s["side"]
            if side_label == "flip_long":
                verb = "FLIP-sell"
            elif side_label == "flip_short":
                verb = "FLIP-cover"
            else:
                verb = side_label
            print(f"  {s['ticker']:>6s}  {verb} {abs(s['current_shares'])} sh "
                  f"@ ~${s['current_price']:.2f}  ~${est:,.2f}")
    else:
        print("CLOSES: none\n")

    longs_in_plan = [b for b in buys if b["side"] == "long"]
    shorts_in_plan = [b for b in buys if b["side"] == "short"]

    if longs_in_plan:
        print(f"\nLONGS ({len(longs_in_plan)}):")
        for b in longs_in_plan:
            _print_action_line(b)
    elif not long_short_mode:
        print("\nLONGS: none")

    if shorts_in_plan:
        print(f"\nSHORTS ({len(shorts_in_plan)}):")
        for b in shorts_in_plan:
            _print_action_line(b)
    elif long_short_mode:
        print("\nSHORTS: none")

    _print_sanity_summary(sanity_summary)


def _print_sanity_summary(sanity_summary: dict) -> None:
    if not sanity_summary.get("applied"):
        return
    long_rej = sanity_summary.get("long_rejected") or []
    long_cau = sanity_summary.get("long_cautioned") or []
    short_rej = sanity_summary.get("short_rejected") or []
    short_cau = sanity_summary.get("short_cautioned") or []
    if not (long_rej or long_cau or short_rej or short_cau):
        return
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


# ─── execution ──────────────────────────────────────────────────────

def _confirm_execution(args, sells: list, buys: list) -> bool:
    """Y/N prompt before live submission. Returns False if operator aborts;
    True otherwise (including when not interactive)."""
    if not (args.confirm and sys.stdin.isatty()):
        return True
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
        return False
    return True


def _submit_closes(
    client, sells: list, today, *, retry_suffix: str = "",
) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Submit close-out market orders. Returns (submitted, failed,
    flip_close_coids) -- flip COIDs are returned so the caller can poll
    them before submitting the matching entry brackets."""
    from src.execution.alpaca import make_client_order_id

    submitted: list[dict] = []
    failed: list[dict] = []
    flip_close_coids: dict[str, str] = {}

    for s in sells:
        cs = s["current_shares"]
        if cs == 0:
            continue
        broker_side = "sell" if cs > 0 else "buy"
        qty = abs(cs)
        coid = make_client_order_id(
            STRATEGY_LABEL + "-close", s["ticker"], today,
            retry_suffix=retry_suffix,
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
            if s["side"].startswith("flip_"):
                flip_close_coids[s["ticker"]] = coid
        except Exception as e:  # noqa: BLE001
            failed.append({"ticker": s["ticker"], "side": "close", "error": str(e)})
            print(f"  FAIL CLOSE {s['ticker']:>6s}: {e}")
    return submitted, failed, flip_close_coids


def _poll_flip_close_fills(
    client, flip_close_coids: dict[str, str],
) -> dict[str, str]:
    """Poll each flip-close to filled (or terminal-fail) before allowing
    its matching bracket entry to submit. Terminal statuses other than
    'filled' block the entry -- we don't want to short a name we
    couldn't successfully close out of long first."""
    flip_close_status: dict[str, str] = {}
    if not flip_close_coids:
        return flip_close_status

    terminal_bad = {"canceled", "expired", "replaced", "stopped",
                    "done_for_day", "rejected", "suspended"}
    deadline = time.monotonic() + 60.0  # 60s budget; paper fills <1s
    remaining = dict(flip_close_coids)
    print(f"\n  Polling {len(remaining)} flip close(s) for fill...")
    while remaining and time.monotonic() < deadline:
        for t in list(remaining):
            coid = remaining[t]
            order = client.get_order_by_coid(coid)
            if order is None:
                continue
            status = (order.get("status") or "").lower().replace(
                "orderstatus.", "",
            )
            if status == "filled":
                flip_close_status[t] = "filled"
                del remaining[t]
                print(f"    {t:>6s}  flip close FILLED")
            elif any(bad in status for bad in terminal_bad):
                flip_close_status[t] = status
                del remaining[t]
                print(f"    {t:>6s}  flip close TERMINAL: {status}")
        if remaining:
            time.sleep(1.5)
    for t in remaining:
        flip_close_status[t] = "timeout"
        print(f"    {t:>6s}  flip close TIMEOUT (60s) -- entry will SKIP")
    return flip_close_status


def _submit_opens(
    args, client, buys: list,
    flip_close_status: dict[str, str], today,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Submit open / resize orders. Side-aware: long opens via
    submit_bracket_order side=buy; short opens via submit_bracket_order
    side=sell with short-bracket levels (stop above entry, TP below).

    Flip entries are blocked if their matching flip-close didn't fill --
    submitting a bracket against an unflattened position is what Alpaca
    rejects with 'bracket orders must be entry orders'.
    """
    from src.execution.alpaca import make_client_order_id

    submitted: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []

    for b in buys:
        if b["submit_type"] != "shares":
            # No-price actions surface as failures, not silent skips.
            reason = b.get("skip_reason") or "no_quote_or_bracket"
            skipped.append({
                "ticker": b["ticker"], "side": b["side"], "reason": reason,
            })
            print(f"  SKIP {b['ticker']:>6s} {b['side']:>5s}: "
                  f"{reason} -- investigate before next rebalance")
            continue
        delta = b.get("delta_shares") or 0
        if delta == 0:
            continue
        if b.get("flip_from_shares"):
            status = flip_close_status.get(b["ticker"])
            if status != "filled":
                failed.append({
                    "ticker": b["ticker"], "side": b["side"],
                    "error": (
                        f"flip_close_not_filled ({status or 'unknown'}); "
                        "refusing flip entry to avoid bracket-on-non-flat "
                        "rejection"
                    ),
                })
                print(
                    f"  FAIL {b['side'].upper():>5s} {b['ticker']:>6s}: "
                    f"flip close did not fill (status={status}); "
                    f"refusing entry"
                )
                continue
        is_long = b["side"] == "long"
        opening = (is_long and delta > 0) or ((not is_long) and delta < 0)
        bracket = b.get("bracket")
        # COID namespace per side so a same-day re-run never collides a
        # long entry with a short entry on the same ticker.
        coid_ns = STRATEGY_LABEL + ("-long" if is_long else "-short")
        coid = make_client_order_id(
            coid_ns, b["ticker"], today, retry_suffix=args.retry_suffix,
        )

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
                # Resize / partial close -- naked market order is fine
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
                submitted.append({"side": f"resize_{b['side']}", **res})
                arrow = "+" if delta > 0 else ""
                print(f"  RESIZE {b['ticker']:>6s} {b['side']:>5s} "
                      f"{arrow}{delta} sh -> order {res['order_id']} "
                      f"({res['status']})")
        except Exception as e:  # noqa: BLE001
            failed.append({
                "ticker": b["ticker"], "side": b["side"], "error": str(e),
            })
            print(f"  FAIL {b['side'].upper():>5s} {b['ticker']:>6s}: {e}")
    return submitted, skipped, failed


def _write_execution_log(
    args, payload: dict, equity: float, sizing: dict,
    n_longs: int, n_shorts: int, long_short_mode: bool,
    sanity_summary: dict, submitted: list, skipped: list, failed: list,
    today,
) -> Path:
    log_dir = Path(args.picks_dir) / "execution_log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{today.isoformat()}.json"
    log_path.write_text(json.dumps({
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "picks_date": payload["as_of"],
        "strategy": STRATEGY_LABEL + ("-ls" if long_short_mode else ""),
        "long_short_mode": long_short_mode,
        "equity_at_start": equity,
        "long_capital": sizing["long_capital"],
        "short_capital": sizing["short_capital"],
        "n_longs": n_longs,
        "n_shorts": n_shorts,
        "sanity_gate": sanity_summary,
        "order_style": args.order_style,
        "submitted": submitted,
        "skipped": skipped,
        "failed": failed,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nExecution log: {log_path}")
    return log_path


# ─── orchestration ───────────────────────────────────────────────────

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()

    payload = _load_picks(args.picks_dir, args.picks_date)
    longs = payload["picks"]
    shorts = payload.get("shorts") or []
    long_short_mode = _resolve_long_short_mode(args, payload)
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

    _run_drift_gate(args)
    _run_kill_switch_gate(args)
    longs, shorts, sanity_summary = _run_sanity_gate(
        args, longs, shorts, long_short_mode,
    )
    n_longs, n_shorts = len(longs), len(shorts)
    logger.info(
        "Post-sanity: %d longs + %d shorts -> rebalance plan", n_longs, n_shorts,
    )

    # Build the Alpaca client AFTER setting the env override so the
    # safety gate reads enabled=true. We never write trading_enabled
    # back to disk -- env-only override.
    if args.execute:
        os.environ["STOCKNEW_TRADING_ENABLED"] = "1"
        logger.warning("EXECUTE MODE: orders will be submitted to Alpaca PAPER.")
    else:
        logger.info(
            "DRY-RUN: no orders will be submitted. Pass --execute to trade."
        )
    client, account = _open_alpaca_client()
    equity = account["equity"]

    sizing = _compute_sizing(args, equity, n_longs, n_shorts, long_short_mode)
    sizing["equity"] = equity

    current_positions = {p["ticker"]: p for p in client.get_positions()}
    logger.info("Current paper positions: %d names", len(current_positions))

    # Quote + OHLC fetch for any target ticker we don't already hold.
    target_tickers = (
        {p["ticker"] for p in longs} | {p["ticker"] for p in shorts}
    )
    needs_quote = [t for t in target_tickers if t not in current_positions]
    if needs_quote:
        logger.info(
            "Fetching live quotes for %d new-position tickers...",
            len(needs_quote),
        )
        fresh_quotes, fresh_ohlc = _fetch_quotes(needs_quote)
        logger.info("Got %d/%d fresh quotes", len(fresh_quotes), len(needs_quote))
    else:
        fresh_quotes, fresh_ohlc = {}, {}

    sells, buys = _build_action_plan(
        args, longs, shorts, current_positions, fresh_quotes, fresh_ohlc,
        sizing["per_long"], sizing["per_short"],
    )

    _print_plan(payload, sizing, sells, buys, long_short_mode, sanity_summary)

    if not args.execute:
        print("\n*** DRY RUN -- nothing submitted. Pass --execute to trade. ***\n")
        return 0

    if not _confirm_execution(args, sells, buys):
        return 0

    print("\n=== EXECUTING ===")
    today = datetime.now(timezone.utc).date()

    submitted_closes, failed_closes, flip_close_coids = _submit_closes(
        client, sells, today, retry_suffix=args.retry_suffix,
    )
    flip_close_status = _poll_flip_close_fills(client, flip_close_coids)
    submitted_opens, skipped, failed_opens = _submit_opens(
        args, client, buys, flip_close_status, today,
    )

    submitted = submitted_closes + submitted_opens
    failed = failed_closes + failed_opens
    print(f"\n=== DONE ===  submitted={len(submitted)}  "
          f"skipped={len(skipped)}  failed={len(failed)}")

    _write_execution_log(
        args, payload, equity, sizing, n_longs, n_shorts, long_short_mode,
        sanity_summary, submitted, skipped, failed, today,
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
