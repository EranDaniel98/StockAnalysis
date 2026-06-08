"""Forward-paper book for the momentum-value 'biggest-risers' composite.

Like the AI book ([[project_ai_forward_book]]) but for the factor composite, not
pure price momentum: a virtual equal-weight book marked daily to live Polygon
prices, rebalanced quarterly via the mom+val(0.6/0.4) pipeline, tracked vs SPY
since start. LOCAL, no Alpaca — isolated from the live shipped-config run.

State: reports/trend_forward_paper_momval_state.json (so the existing
GET /api/research/momval endpoint serves it). Daily runbook:

    uv run python -m scripts.research.momval_forward_paper           # init / mark + rebalance-if-due
    uv run python -m scripts.research.momval_forward_paper --status  # print, no network
    uv run python -m scripts.research.momval_forward_paper --force-rebalance
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from scripts.research.trend_forward_paper import (  # noqa: E402
    _last_close, _polygon_daily, _trading_days_between,
)

STATE_PATH = ROOT / "reports" / "trend_forward_paper_momval_state.json"


def _cfg() -> dict:
    """momval_book config (weights, params, risk note) from strategies.yaml."""
    from src.config_loader import Config
    return Config().strategies.get("momval_book", {})


def _load_state() -> dict | None:
    return json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else None


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def _momval_picks(as_of: pd.Timestamp, top_n: int) -> pd.DataFrame:
    """Today's mom+val(0.6/0.4) top-N over the live PIT S&P 500."""
    from src.factors.pipeline import run_factor_picks
    cfg = _cfg()
    res = run_factor_picks(
        as_of=as_of, top_n=top_n,
        composite_factors="mv",
        factor_weights=cfg.get("weights", {"momentum": 0.6, "value": 0.4}),
        include_pead=False, sector_neutral_quality=False,
        min_overlap=1, min_history_days=int(cfg.get("min_history_days", 504)),
    )
    return res.top_n, res.universe_size


def _rebalance(state: dict, as_of: pd.Timestamp) -> dict:
    p = state["params"]
    end = as_of.date().isoformat()
    print(f"[rebalance {end}] computing mom+val(0.6/0.4) top-{p['top_n']}...")
    top, uni_n = _momval_picks(as_of, p["top_n"])
    state["universe_n"] = int(uni_n)
    if top.empty:
        raise SystemExit("composite ranking empty — no rebalance")
    targets = top["ticker"].tolist()
    info = {r["ticker"]: {"rank": int(r.get("rank") or 0),
                          "z": float(r.get("z_score")) if pd.notna(r.get("z_score")) else None,
                          "mom_rank": int(r["mom_rank"]) if pd.notna(r.get("mom_rank")) else None,
                          "val_rank": int(r["val_rank"]) if pd.notna(r.get("val_rank")) else None}
            for _, r in top.iterrows()}

    start = (as_of - pd.Timedelta(days=14)).date().isoformat()
    prices = _polygon_daily(targets + list(state.get("holdings", {})), start, end)
    px = {t: _last_close(prices.get(t), as_of) for t in targets}
    targets = [t for t in targets if px.get(t) and px[t] > 0]

    cost_rate = p["cost_bps"] / 10_000.0
    cur = state.get("holdings", {})
    equity = state.get("cash", state["baseline_equity"])
    for t, h in cur.items():
        cpx = _last_close(prices.get(t), as_of) or h.get("last_px") or h["entry_px"]
        equity += h["shares"] * cpx
    per_name = equity / max(1, len(targets))

    old_notional = {t: cur[t]["shares"] * (_last_close(prices.get(t), as_of)
                    or cur[t].get("last_px") or cur[t]["entry_px"]) for t in cur}
    new_notional = {t: per_name for t in targets}
    turnover = sum(abs(new_notional.get(t, 0.0) - old_notional.get(t, 0.0))
                   for t in set(old_notional) | set(new_notional))
    cost = turnover * cost_rate

    # Store composite rank/z under the mom_* keys the research router reads.
    state["holdings"] = {
        t: {"shares": per_name / px[t], "entry_px": px[t], "entry_date": end,
            "last_px": px[t], "mom_rank": info[t]["rank"], "mom_z": info[t]["z"],
            "mom_raw": None, "val_rank": info[t]["val_rank"]}
        for t in targets
    }
    state["cash"] = equity - per_name * len(targets) - cost
    state.setdefault("rebalances", []).append(
        {"date": end, "picks": targets, "n": len(targets),
         "equity_pre": round(equity, 2), "turnover": round(turnover, 2), "cost": round(cost, 2)})
    state["last_rebalance"] = end
    print(f"  rebalanced to {len(targets)} names, equity ${equity:,.2f} (cost ${cost:,.2f})")
    print("  picks:", " ".join(targets))
    return state


def _mark(state: dict, as_of: pd.Timestamp) -> dict:
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
    row = {"date": end, "equity": round(equity, 2), "ret_pct": round(ret * 100, 2),
           "spy_close": round(spy_px, 4) if spy_px else None,
           "spy_ret_pct": round(spy_ret * 100, 2) if spy_ret is not None else None,
           "excess_vs_spy_pct": round((ret - spy_ret) * 100, 2) if spy_ret is not None else None}
    hist = state.setdefault("history", [])
    hist[:] = [h for h in hist if h["date"] != end] + [row]
    state["last_marked"] = end
    return state


def _print_status(state: dict) -> None:
    print("\n=== Momentum-Value FORWARD PAPER [momval] (local, no Alpaca) ===")
    print(f"start={state['start_date']}  baseline=${state['baseline_equity']:,.2f}  "
          f"weights={state['params'].get('weights')}  universe={state.get('universe_n','?')}")
    print(f"last rebalance={state.get('last_rebalance')}  holdings={len(state.get('holdings',{}))}")
    hist = state.get("history", [])
    if hist:
        last = hist[-1]
        print(f"latest mark {last['date']}: equity ${last['equity']:,.2f}  ret {last['ret_pct']:+.2f}%  "
              f"SPY {last.get('spy_ret_pct')}%  excess {last.get('excess_vs_spy_pct')}%")
    held = state.get("holdings", {})
    if held:
        names = sorted(held, key=lambda t: held[t].get("mom_rank", 1e9))
        print(f"\nholdings ({len(held)}) sorted by composite rank:")
        for t in names:
            h = held[t]
            since = (h.get("last_px", h["entry_px"]) / h["entry_px"] - 1.0) if h.get("entry_px") else None
            print(f"  #{h.get('mom_rank'):>3} {t:>6} z={h.get('mom_z'):+.2f}  "
                  f"since {since*100:+.2f}%" if since is not None else f"  {t}")
    note = state.get("risk_note") or _cfg().get("risk_note") or ""
    if note:
        print(f"\n*** RISK: {note.strip()} ***")


def main() -> int:
    cfg = _cfg()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top-n", type=int, default=int(cfg.get("top_n", 24)))
    ap.add_argument("--rebalance-days", type=int, default=int(cfg.get("rebalance_days", 63)))
    ap.add_argument("--cost-bps", type=float, default=float(cfg.get("cost_bps", 5.0)))
    ap.add_argument("--baseline", type=float, default=float(cfg.get("baseline_equity", 100_000.0)))
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--force-rebalance", action="store_true")
    ap.add_argument("--status", action="store_true")
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
        print(f"INIT momval forward book: start={as_of.date()}")
        state = {
            "strategy": "momval_6_4_composite", "book": "momval",
            "start_date": as_of.date().isoformat(),
            "universe_file": "PIT_S&P_500", "universe_n": 0,
            "params": {"top_n": args.top_n, "rebalance_days": args.rebalance_days,
                       "cost_bps": args.cost_bps,
                       "weights": cfg.get("weights", {"momentum": 0.6, "value": 0.4})},
            "risk_note": (cfg.get("risk_note") or "").strip(),
            "baseline_equity": args.baseline, "cash": args.baseline,
            "holdings": {}, "rebalances": [], "history": [],
        }
        state = _rebalance(state, as_of)
        spy = _polygon_daily(["SPY"], (as_of - pd.Timedelta(days=14)).date().isoformat(),
                             as_of.date().isoformat())
        state["spy_start_close"] = _last_close(spy.get("SPY"), as_of)
        state = _mark(state, as_of)
        _save_state(state)
        _print_status(state)
        return 0

    due = args.force_rebalance or (
        _trading_days_between(state.get("last_rebalance", state["start_date"]),
                              as_of.date().isoformat()) >= state["params"]["rebalance_days"])
    if due:
        print(f"rebalance due — re-ranking mom+val.")
        state = _rebalance(state, as_of)
    state = _mark(state, as_of)
    _save_state(state)
    _print_status(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
