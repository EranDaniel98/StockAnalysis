# /// script
# dependencies = ["pandas", "numpy", "requests", "python-dotenv"]
# ///
"""Self-contained forward paper book for 12-1 top-20 broad-momentum (catch-and-HOLD).

The ONE survivor of the trend-ride study (see project_trend_ride_study): on live
2024-26 data, holding the top-20 broad-universe 12-1 momentum names was the only
robust config (+10% CAPM-α, 100% WF) — every trend-EXIT variant subtracted value.
This wires it as a FORWARD, un-overfittable test: a virtual equal-weight book marked
to live Polygon prices, rebalanced quarterly, tracked vs SPY since start.

DELIBERATELY ISOLATED FROM ALPACA. No broker, no orders. It cannot touch the live
shipped-config forward validation in your paper account (that one owns Alpaca; this
one is a local state file). It is still a true forward test — it uses live forward
prices the strategy has never seen.

STRATEGY (fixed — do NOT tune mid-test; that defeats the purpose):
  - Universe: a broad PIT list FROZEN at start (--universe-file). Frozen-forward is
    survivorship-safe: we exclude names listed AFTER start, never hold hindsight.
  - Signal: Jegadeesh-Titman 12-1 (close[t-21]/close[t-252]-1), top-20, equal-weight.
  - HOLD to rebalance: every --rebalance-days (63) trading days, full re-rank. NO
    per-name trend exit, NO regime gate — the study found both subtract here.
  - Cost: --cost-bps one-way on rebalance turnover.

RISK ACKNOWLEDGED (baked into every status print): this is a ~2x-beta bull bet with
a backtested -38% max drawdown and the downside-protection half UNTESTED (the trend
never broke in-sample). The forward run exists precisely to see how it behaves when
it eventually does.

State: reports/trend_forward_paper_state.json (holdings, baseline, daily history).

Daily runbook (run once per trading day, like your 2026-05-27 forward validation):
    uv run python -m scripts.research.trend_forward_paper            # init (first run) / mark + rebalance-if-due
    uv run python -m scripts.research.trend_forward_paper --status   # print without fetching
    uv run python -m scripts.research.trend_forward_paper --force-rebalance
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

STATE_PATH = ROOT / "reports" / "trend_forward_paper_state.json"
LOOKBACK_DAYS = 252
SKIP_DAYS = 21
FETCH_CAL_DAYS = 420   # calendar days of history to pull so 252 td warm up


# --------------------------------------------------------------------------- #
# Data — Polygon direct (deterministic, delisting-inclusive; same source as
# build_snapshot). SPY is a stock on Polygon; VIX is not needed (no gate).
# --------------------------------------------------------------------------- #
def _polygon_daily(tickers: list[str], start: str, end: str,
                   *, workers: int = 8) -> dict[str, pd.DataFrame]:
    from src.market_data.polygon import PolygonClient, PolygonError, bars_to_frame

    client = PolygonClient()

    def _one(t: str):
        try:
            bars = client.aggregates(t, start, end, timespan="day", multiplier=1, adjusted=True)
        except PolygonError:
            return None
        df = bars_to_frame(bars, daily=True)
        return df if df is not None and not df.empty else None

    out: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(tickers)))) as ex:
        futs = {ex.submit(_one, t): t for t in tickers}
        for fut in as_completed(futs):
            df = fut.result()
            if df is not None:
                out[futs[fut]] = df
    return out


def _momentum_top_n(prices: dict[str, pd.DataFrame], as_of: pd.Timestamp, top_n: int) -> pd.DataFrame:
    """12-1 momentum ranking, top-N. Reuses the production factor (lookahead-safe:
    reads <= as_of, skips the most recent month)."""
    from src.factors.momentum import momentum_12_1

    rank = momentum_12_1(prices, as_of)
    return rank.head(top_n).reset_index(drop=True)


def _last_close(df: pd.DataFrame, as_of: pd.Timestamp) -> float | None:
    if df is None or df.empty or "Close" not in df.columns:
        return None
    elig = df[df.index <= as_of]["Close"].dropna()
    return None if elig.empty else float(elig.iloc[-1])


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
def _load_state() -> dict | None:
    return json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else None


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def _read_universe(path: Path) -> list[str]:
    lines = [ln.strip().upper() for ln in path.read_text(encoding="utf-8").splitlines()]
    return [ln for ln in lines if ln and not ln.startswith("#")]


def _latest_universe_file() -> Path | None:
    files = sorted((ROOT / "data").glob("universe_broad_pit_*.txt"))
    return files[-1] if files else None


def _trading_days_between(start: str, end: str) -> int:
    """Business-day count (weekends excluded; holidays ignored — a few-day slop is
    immaterial to a quarterly forward cadence)."""
    return int(np.busday_count(pd.Timestamp(start).date(), pd.Timestamp(end).date()))


# --------------------------------------------------------------------------- #
# Book mechanics — virtual, fractional shares, equal-weight, fully invested.
# --------------------------------------------------------------------------- #
def _rebalance(state: dict, as_of: pd.Timestamp, *, verbose: bool = True) -> dict:
    """Full re-rank to a fresh equal-weight top-N. Sells everything, rebuys; charges
    cost_bps on turnover. Universe + history fetched fresh from Polygon."""
    p = state["params"]
    universe = _read_universe(Path(state["universe_file"]))
    start = (as_of - pd.Timedelta(days=FETCH_CAL_DAYS)).date().isoformat()
    end = as_of.date().isoformat()
    print(f"[rebalance {end}] fetching {len(universe)} universe names from Polygon...")
    prices = _polygon_daily(universe, start, end)
    print(f"  got history for {len(prices)}/{len(universe)} names")

    top = _momentum_top_n(prices, as_of, p["top_n"])
    if top.empty:
        raise SystemExit("momentum ranking empty — no rebalance")
    targets = top["ticker"].tolist()
    px = {t: _last_close(prices.get(t), as_of) for t in targets}
    targets = [t for t in targets if px.get(t) and px[t] > 0]

    cost_rate = p["cost_bps"] / 10_000.0
    # Mark current book at today's prices to get pre-rebalance equity.
    cur_holdings = state.get("holdings", {})
    cur_px = prices if cur_holdings else {}
    equity = state.get("cash", state["baseline_equity"])
    for t, h in cur_holdings.items():
        cpx = _last_close(cur_px.get(t), as_of) or h.get("last_px") or h["entry_px"]
        equity += h["shares"] * cpx
    per_name = equity / max(1, len(targets))

    # Turnover cost on |Δnotional| across the union of old+new names.
    old_notional = {t: cur_holdings[t]["shares"] * (_last_close(cur_px.get(t), as_of)
                    or cur_holdings[t].get("last_px") or cur_holdings[t]["entry_px"])
                    for t in cur_holdings}
    new_notional = {t: per_name for t in targets}
    turnover = sum(abs(new_notional.get(t, 0.0) - old_notional.get(t, 0.0))
                   for t in set(old_notional) | set(new_notional))
    cost = turnover * cost_rate

    holdings = {t: {"shares": per_name / px[t], "entry_px": px[t],
                    "entry_date": end, "last_px": px[t]} for t in targets}
    invested = per_name * len(targets)
    state["holdings"] = holdings
    state["cash"] = equity - invested - cost
    state.setdefault("rebalances", []).append(
        {"date": end, "picks": targets, "n": len(targets),
         "equity_pre": round(equity, 2), "turnover": round(turnover, 2),
         "cost": round(cost, 2)})
    state["last_rebalance"] = end
    if verbose:
        print(f"  rebalanced to {len(targets)} names, equity ${equity:,.2f} "
              f"(turnover ${turnover:,.0f}, cost ${cost:,.2f})")
        print("  picks:", " ".join(targets))
    return state


def _mark(state: dict, as_of: pd.Timestamp) -> dict:
    """Mark the held book + SPY to live prices; append a history row."""
    held = list(state.get("holdings", {}))
    start = (as_of - pd.Timedelta(days=14)).date().isoformat()
    end = as_of.date().isoformat()
    prices = _polygon_daily(held + ["SPY"], start, end)
    spy_px = _last_close(prices.get("SPY"), as_of)

    equity = state.get("cash", 0.0)
    for t, h in state["holdings"].items():
        lpx = _last_close(prices.get(t), as_of) or h.get("last_px") or h["entry_px"]
        h["last_px"] = lpx
        equity += h["shares"] * lpx

    base = state["baseline_equity"]
    ret = equity / base - 1.0
    spy_ret = (spy_px / state["spy_start_close"] - 1.0) if (spy_px and state.get("spy_start_close")) else None
    row = {"date": end, "equity": round(equity, 2),
           "ret_pct": round(ret * 100, 2),
           "spy_close": round(spy_px, 4) if spy_px else None,
           "spy_ret_pct": round(spy_ret * 100, 2) if spy_ret is not None else None,
           "excess_vs_spy_pct": round((ret - spy_ret) * 100, 2) if spy_ret is not None else None}
    hist = state.setdefault("history", [])
    hist[:] = [h for h in hist if h["date"] != end] + [row]  # idempotent per date
    state["last_marked"] = end
    return state


def _print_status(state: dict) -> None:
    print("\n=== 12-1 broad-momentum FORWARD PAPER (local, no Alpaca) ===")
    print(f"start={state['start_date']}  baseline=${state['baseline_equity']:,.2f}  "
          f"universe={Path(state['universe_file']).name} ({state.get('universe_n','?')} names)")
    print(f"last rebalance={state.get('last_rebalance')}  holdings={len(state.get('holdings',{}))}")
    hist = state.get("history", [])
    if hist:
        last = hist[-1]
        print(f"\nlatest mark {last['date']}: equity ${last['equity']:,.2f}  "
              f"ret {last['ret_pct']:+.2f}%  SPY {last.get('spy_ret_pct'):+.2f}%  "
              f"excess {last.get('excess_vs_spy_pct'):+.2f}%")
    held = state.get("holdings", {})
    if held:
        names = sorted(held, key=lambda t: -held[t]["shares"] * held[t].get("last_px", held[t]["entry_px"]))
        print("\nholdings:", " ".join(names))
    print("\n*** RISK: ~2x-beta bull bet; backtested -38% max DD; downside protection "
          "UNTESTED (trend never broke in-sample). This forward run is to watch exactly that. ***")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--universe-file", default=None,
                    help="frozen broad PIT universe (default: latest data/universe_broad_pit_*.txt)")
    ap.add_argument("--top-n", type=int, default=20)
    ap.add_argument("--rebalance-days", type=int, default=63, help="trading-day cadence (default 63).")
    ap.add_argument("--cost-bps", type=float, default=5.0)
    ap.add_argument("--baseline", type=float, default=100_000.0, help="virtual starting equity.")
    ap.add_argument("--as-of", default=None, help="override mark date YYYY-MM-DD (testing).")
    ap.add_argument("--force-rebalance", action="store_true")
    ap.add_argument("--status", action="store_true", help="print state only, no network.")
    args = ap.parse_args()

    as_of = (pd.Timestamp(args.as_of) if args.as_of
             else pd.Timestamp.now(tz=timezone.utc).normalize().tz_localize(None))
    state = _load_state()

    if args.status:
        if not state:
            print("no state yet — run without --status to initialize.")
            return 0
        _print_status(state)
        return 0

    if state is None:
        uf = Path(args.universe_file) if args.universe_file else _latest_universe_file()
        if uf is None or not uf.exists():
            raise SystemExit("no universe file — run scripts/research/build_broad_universe.py first.")
        universe = _read_universe(uf)
        print(f"INIT forward book: start={as_of.date()} universe={uf.name} ({len(universe)} names)")
        state = {
            "strategy": "trend12_1_broad_top20_hold",
            "start_date": as_of.date().isoformat(),
            "universe_file": str(uf), "universe_n": len(universe),
            "params": {"top_n": args.top_n, "rebalance_days": args.rebalance_days,
                       "cost_bps": args.cost_bps, "lookback": LOOKBACK_DAYS, "skip": SKIP_DAYS},
            "baseline_equity": args.baseline, "cash": args.baseline,
            "holdings": {}, "rebalances": [], "history": [],
        }
        state = _rebalance(state, as_of)
        # Anchor SPY at start for the benchmark.
        spy = _polygon_daily(["SPY"], (as_of - pd.Timedelta(days=14)).date().isoformat(),
                             as_of.date().isoformat())
        state["spy_start_close"] = _last_close(spy.get("SPY"), as_of)
        state = _mark(state, as_of)
        _save_state(state)
        _print_status(state)
        return 0

    # Existing book: rebalance if due, then mark.
    due = args.force_rebalance or (
        _trading_days_between(state.get("last_rebalance", state["start_date"]),
                              as_of.date().isoformat()) >= state["params"]["rebalance_days"])
    if due:
        print(f"rebalance due ({_trading_days_between(state.get('last_rebalance', state['start_date']), as_of.date().isoformat())} "
              f"td since last) — re-ranking.")
        state = _rebalance(state, as_of)
    state = _mark(state, as_of)
    _save_state(state)
    _print_status(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
