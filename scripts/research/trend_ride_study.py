# /// script
# dependencies = ["pandas", "numpy"]
# ///
"""Trend-ride study — "catch the trend, exit on the break" on a broad equity universe.

Standalone. Modifies no tracked files. BACKTEST ONLY. Reads a frozen Polygon
snapshot (deterministic; no network), ranks the broad PIT universe by 12-1
momentum, holds the top-N, and tests whether a PER-NAME trend-following EXIT
adds value over (a) buy-and-hold SPY and (b) the same basket held to rebalance.

THE QUESTION (user, 2026-06-02)
  "Find AI/tech names with the greatest potential (SNDK/DELL-like), catch the
  trend, and exit." Decision: backtest first, momentum off the BROAD universe
  (let AI names surface naturally), phase-averaged (no single-offset luck).

THREE BOOKS, same calendar / same starting cash, marked daily:
  SPY   buy-and-hold S&P 500 (the benchmark "buy-and-hold").
  HOLD  equal-weight top-N by 12-1 momentum, re-ranked every --rebalance-days,
        NO per-name exit (names leave only when they drop out of top-N at a
        rebalance). This is "buy-and-hold the momentum basket."
  RIDE  same top-N entries, PLUS a per-name trend exit (--exit-rule). An exited
        name goes to CASH until the next rebalance (we do NOT rotate into a
        replacement — that would conflate exit value with re-entry value). RIDE
        minus HOLD therefore ISOLATES the value of the exit rule.

EXIT RULES (--exit-rule, per held name, evaluated on data <= d, executed at close_d)
  sma    exit when close_d < its own --exit-sma-day SMA   (default; canonical trend break)
  trail  exit when close_d <= (peak close since entry) * (1 - --trail-pct)
  mom    exit when its own 21-day return goes negative (momentum decay)

LOOKAHEAD DISCIPLINE (the #1 trap in this repo — see project_phase_luck_capstone)
  - Ranking at rebalance d uses momentum_12_1 (reads prices <= d, and the 12-1
    return itself SKIPS the most recent month: anchors at d-21 and d-252).
  - Entries execute at close_d using a ranking formed from <= d-21.
  - The per-name exit signal at day d uses closes <= d (SMA / peak / 21d-return
    all end at d) and executes at close_d. No same-day future data.
  - SMA / peak windows read the snapshot's pre-window WARMUP rows, so the signal
    is fully formed from day one of the test window.

EVALUATION (honors the eval discipline in CLAUDE.md)
  - PRIMARY = CAPM/Jensen alpha + beta vs SPY (raw excess flatters a cash-heavy
    book: sitting in cash through a dip is low beta, not skill). Raw excess shown
    secondary.
  - --phase-sweep sweeps --rebal-offset across the rebalance cycle and reports
    the mean +/- spread, %-of-phases-positive, and WF-pass rate for each book AND
    for the RIDE-minus-HOLD exit delta. ROBUST verdict mirrors phase_envelope.py
    (median>0, >=70% phases positive, >=60% WF-pass, bounded spread, >=8 phases).

CAVEAT baked into the verdict: only ONE broad snapshot exists (2024-01-02 ->
2026-01-02), and it is the AI BULL. Trend exits typically HELP in bears/chop and
HURT in strong bulls (premature whipsaw). A bear-window broad snapshot (e.g. 2022)
is needed before generalizing. And the universe is frozen as-of 2024-01-02, so
2025 spinoffs/IPOs (SNDK et al.) are NOT in it — established trenders only.

Usage:
    uv run python scripts/research/trend_ride_study.py --snapshot-id 9f448161ca59e465
    uv run python scripts/research/trend_ride_study.py --snapshot-id 9f448161ca59e465 \
        --top-n 20 --exit-rule sma --exit-sma 50 --phase-sweep --output reports/trend_ride.json
    uv run python scripts/research/trend_ride_study.py --smoke
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # so `src` imports work when run as a script
TD_PER_YEAR = 252
SKIP_DAYS = 21              # skip-the-most-recent-month (controls short-term reversal)
START_CASH = 100_000_000.0  # large by design: keeps integer-share rounding < 0.1%/name
MIN_PHASES = 8              # below this the sweep is too sparse to judge (cf. phase_envelope.py)


# --------------------------------------------------------------------------- #
# Metrics — local copies (per-script convention; cf. vrp_study.py:70, tsmom_study.py:96).
# --------------------------------------------------------------------------- #
def ann_sharpe(daily: pd.Series) -> float:
    r = daily.dropna()
    if r.empty:
        return 0.0
    sigma = r.std(ddof=0)
    if sigma == 0 or np.isnan(sigma):
        return 0.0
    return float(r.mean() / sigma * math.sqrt(TD_PER_YEAR))


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    return float((equity / equity.cummax() - 1.0).min())


def capm_alpha_beta(strat_daily: pd.Series, spy_daily: pd.Series) -> tuple[float, float]:
    """Jensen alpha (annualized %) + beta from OLS of daily strat on daily SPY."""
    df = pd.concat([strat_daily.rename("s"), spy_daily.rename("m")], axis=1).dropna()
    if len(df) < 30 or df["m"].var() == 0:
        return 0.0, 0.0
    beta = float(df["s"].cov(df["m"]) / df["m"].var())
    alpha_d = float(df["s"].mean() - beta * df["m"].mean())
    return ((1.0 + alpha_d) ** TD_PER_YEAR - 1.0) * 100.0, beta


def cagr(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    if years <= 0:
        return 0.0
    return (equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0


def walk_forward(daily: pd.Series, n_folds: int = 5) -> dict:
    r = daily.dropna()
    if r.empty or len(r) < n_folds:
        return {"mean_sharpe": 0.0, "min_sharpe": 0.0, "passed": False}
    fs = len(r) // n_folds
    sharpes = []
    for i in range(n_folds):
        end = (i + 1) * fs if i < n_folds - 1 else len(r)
        sharpes.append(ann_sharpe(r.iloc[i * fs:end]))
    mean_s, min_s = float(np.mean(sharpes)), float(np.min(sharpes))
    return {"mean_sharpe": round(mean_s, 3), "min_sharpe": round(min_s, 3),
            "passed": bool(all(s > 0 for s in sharpes) and mean_s >= 0.5)}


# --------------------------------------------------------------------------- #
# Backtest core
# --------------------------------------------------------------------------- #
def _build_close_matrix(price_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """All-dates x tickers Close matrix (union index, per-name ffill AFTER first
    listing only — leading NaNs preserved so pre-listing != a real price)."""
    cols = {}
    for t, df in price_data.items():
        if df is None or df.empty or "Close" not in df.columns:
            continue
        s = df["Close"]
        s = s[~s.index.duplicated(keep="last")].sort_index()
        cols[t] = s
    mat = pd.DataFrame(cols).sort_index()
    return mat.ffill()  # ffill gaps; leading NaN (pre-listing) stays NaN


def _exit_signal_frames(closes: pd.DataFrame, rule: str, exit_sma: int,
                        trail_pct: float) -> dict:
    """Precompute whatever the exit rule needs, on the FULL daily index."""
    if rule == "sma":
        return {"sma": closes.rolling(exit_sma, min_periods=exit_sma).mean()}
    if rule == "mom":
        return {"mom21": closes / closes.shift(21) - 1.0}
    if rule == "trail":
        return {}  # peak tracked online per position (needs entry date)
    raise SystemExit(f"unknown --exit-rule {rule!r}")


def _momentum_rank(closes: pd.DataFrame, as_of: pd.Timestamp, lookback: int,
                   skip: int, cache: dict) -> pd.DataFrame:
    """Cross-sectional (lookback-skip) momentum, vectorized off the close matrix.

    raw_t = close[t-skip] / close[t-lookback] - 1  (Jegadeesh-Titman form; 12-1 =>
    lookback=252, skip=21). Shorter lookback lets NEWER names in: a name needs only
    `lookback` rows of history, so a 3-1 (lookback=63) screen can rank a stock with
    ~3mo of trading, which 12-1 cannot. Lookahead-safe: uses only rows <= t-skip;
    leading-NaN (pre-listing) names drop out automatically. Cached by as_of date."""
    key = as_of.normalize()
    if key in cache:
        return cache[key]
    idx = closes.index
    pos = idx.get_loc(as_of) if as_of in idx else int(idx.searchsorted(as_of, "right")) - 1
    if pos - lookback < 0:
        cache[key] = pd.DataFrame(columns=["ticker", "raw", "rank"])
        return cache[key]
    recent = closes.iloc[pos - skip]
    old = closes.iloc[pos - lookback]
    raw = (recent / old - 1.0)[old > 0].dropna()
    out = pd.DataFrame({"ticker": raw.index, "raw": raw.values})
    out["rank"] = out["raw"].rank(ascending=False, method="min").astype(int)
    cache[key] = out.sort_values("rank").reset_index(drop=True)
    return cache[key]


def run_books(price_data: dict, spy: pd.DataFrame, calendar: pd.DatetimeIndex,
              closes: pd.DataFrame, *, top_n: int, rebalance_days: int,
              rebal_offset: int, cost_bps: float, exit_rule: str, exit_sma: int,
              trail_pct: float, mom_lookback: int, mom_cache: dict) -> dict:
    """Run SPY / HOLD / RIDE books over the calendar. Returns daily equity series
    (one per book), the held-name day counts, and exit/turnover diagnostics."""
    cost = cost_bps / 10_000.0
    exit_frames = _exit_signal_frames(closes, exit_rule, exit_sma, trail_pct)

    # SPY buy-and-hold: closed form.
    spy_close = spy["Close"].reindex(calendar).ffill()
    spy_eq = START_CASH * (spy_close / spy_close.iloc[0])

    # Active universe per the close matrix (drop names with no price in window).
    universe = [t for t in price_data if t in closes.columns and t != "SPY"]

    def _new_book():
        return {"cash": START_CASH, "holdings": {}, "entry": {}, "eq": [], "exits": 0, "turn": 0.0}

    hold, ride = _new_book(), _new_book()

    def _px(t, d):
        v = closes.at[d, t] if t in closes.columns and d in closes.index else np.nan
        return None if pd.isna(v) else float(v)

    def _mtm(bk, d):
        e = bk["cash"]
        for t, sh in bk["holdings"].items():
            p = _px(t, d)
            if p is not None:
                e += sh * p
        return e

    def _liquidate(bk, d, keep: set[str]):
        for t in list(bk["holdings"]):
            if t in keep:
                continue
            sh = bk["holdings"].pop(t)
            bk["entry"].pop(t, None)
            p = _px(t, d)
            if p is None or sh == 0:
                continue
            notional = sh * p
            bk["cash"] += notional - abs(notional) * cost
            bk["turn"] += abs(notional)

    def _buy_equal_weight(bk, d, targets: list[str]):
        eq = _mtm(bk, d)
        per = eq / max(1, len(targets))
        for t in sorted(targets):
            p = _px(t, d)
            if p is None or p <= 0 or t in bk["holdings"]:
                continue
            sh = int(per // p)
            if sh <= 0:
                continue
            notional = sh * p
            bk["holdings"][t] = sh
            bk["entry"][t] = d
            bk["cash"] -= notional + notional * cost
            bk["turn"] += notional

    def _ride_exits(d):
        for t in list(ride["holdings"]):
            p = _px(t, d)
            if p is None:
                continue
            hit = False
            if exit_rule == "sma":
                s = exit_frames["sma"].at[d, t] if d in exit_frames["sma"].index else np.nan
                hit = (not pd.isna(s)) and p < float(s)
            elif exit_rule == "mom":
                m = exit_frames["mom21"].at[d, t] if d in exit_frames["mom21"].index else np.nan
                hit = (not pd.isna(m)) and float(m) < 0.0
            elif exit_rule == "trail":
                ent = ride["entry"].get(t, d)
                win = closes.loc[ent:d, t].dropna()
                hit = (not win.empty) and p <= float(win.max()) * (1.0 - trail_pct)
            if hit:
                sh = ride["holdings"].pop(t)
                ride["entry"].pop(t, None)
                ride["exits"] += 1
                notional = sh * p
                ride["cash"] += notional - abs(notional) * cost
                ride["turn"] += abs(notional)

    rebal_every = max(1, rebalance_days)
    for i, d in enumerate(calendar):
        if exit_rule and ride["holdings"]:
            _ride_exits(d)  # intra-period per-name exits happen BEFORE marking
        is_rebal = (i % rebal_every == rebal_offset % rebal_every)
        if is_rebal:
            ranking = _momentum_rank(closes, d, mom_lookback, SKIP_DAYS, mom_cache)
            if not ranking.empty:
                targets = [t for t in ranking["ticker"].tolist() if t in universe][:top_n]
                tset = set(targets)
                for bk in (hold, ride):
                    _liquidate(bk, d, keep=tset)
                    _buy_equal_weight(bk, d, targets)
        hold["eq"].append(_mtm(hold, d))
        ride["eq"].append(_mtm(ride, d))

    idx = calendar
    return {
        "spy_eq": spy_eq,
        "hold_eq": pd.Series(hold["eq"], index=idx),
        "ride_eq": pd.Series(ride["eq"], index=idx),
        "ride_exits": ride["exits"],
        "hold_turnover_x": round(hold["turn"] / START_CASH, 2),
        "ride_turnover_x": round(ride["turn"] / START_CASH, 2),
    }


def _book_metrics(eq: pd.Series, spy_eq: pd.Series) -> dict:
    daily = eq.pct_change().dropna()
    spy_daily = spy_eq.pct_change().dropna()
    total = float(eq.iloc[-1] / eq.iloc[0] - 1.0)
    spy_total = float(spy_eq.iloc[-1] / spy_eq.iloc[0] - 1.0)
    a, b = capm_alpha_beta(daily, spy_daily)
    wf = walk_forward(daily)
    return {
        "total_return_pct": round(total * 100, 2),
        "cagr_pct": round(cagr(eq) * 100, 2),
        "ann_sharpe": round(ann_sharpe(daily), 3),
        "max_drawdown_pct": round(max_drawdown(eq) * 100, 2),
        "capm_alpha_pct": round(a, 2),
        "beta": round(b, 3),
        "excess_vs_spy_pct": round((total - spy_total) * 100, 2),
        "pct_positive_days": round(float((daily > 0).mean() * 100), 1),
        "wf_pass": wf["passed"],
        "wf_mean_sharpe": wf["mean_sharpe"],
    }


def single_run(snap, calendar, closes, args, mom_cache) -> dict:
    bk = run_books(
        snap.price_data, snap.spy_df, calendar, closes,
        top_n=args.top_n, rebalance_days=args.rebalance_days,
        rebal_offset=args.rebal_offset, cost_bps=args.cost_bps,
        exit_rule=args.exit_rule, exit_sma=args.exit_sma, trail_pct=args.trail_pct,
        mom_lookback=args.mom_lookback, mom_cache=mom_cache,
    )
    spy_eq = bk["spy_eq"]
    spy_daily = spy_eq.pct_change().dropna()
    spy_m = {
        "total_return_pct": round(float(spy_eq.iloc[-1] / spy_eq.iloc[0] - 1.0) * 100, 2),
        "cagr_pct": round(cagr(spy_eq) * 100, 2),
        "ann_sharpe": round(ann_sharpe(spy_daily), 3),
        "max_drawdown_pct": round(max_drawdown(spy_eq) * 100, 2),
    }
    hold_m = _book_metrics(bk["hold_eq"], spy_eq)
    ride_m = _book_metrics(bk["ride_eq"], spy_eq)
    return {
        "rebal_offset": args.rebal_offset,
        "spy": spy_m, "hold": hold_m, "ride": ride_m,
        "exit_value_capm_alpha_pp": round(ride_m["capm_alpha_pct"] - hold_m["capm_alpha_pct"], 2),
        "exit_value_total_ret_pp": round(ride_m["total_return_pct"] - hold_m["total_return_pct"], 2),
        "ride_exits": bk["ride_exits"],
        "hold_turnover_x": bk["hold_turnover_x"],
        "ride_turnover_x": bk["ride_turnover_x"],
    }


def held_names(snap, closes, calendar, args, mom_cache, top_k: int = 25) -> list[dict]:
    """Which tickers the momentum screen actually surfaces (held-day weighted),
    at the base offset. The 'what AI names show up' answer."""
    counts: dict[str, int] = {}
    rebal_every = max(1, args.rebalance_days)
    held: list[str] = []
    for i, d in enumerate(calendar):
        if i % rebal_every == args.rebal_offset % rebal_every:
            ranking = _momentum_rank(closes, d, args.mom_lookback, SKIP_DAYS, mom_cache)
            held = ([t for t in ranking["ticker"].tolist()
                     if t in closes.columns and t != "SPY"][:args.top_n]
                    if not ranking.empty else held)
        for t in held:
            counts[t] = counts.get(t, 0) + 1
    n = len(calendar)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]
    return [{"ticker": t, "held_pct_of_window": round(100 * c / n, 1)} for t, c in ranked]


# --------------------------------------------------------------------------- #
# Phase envelope
# --------------------------------------------------------------------------- #
def _stats(xs: list[float]) -> dict:
    return {"mean": round(statistics.mean(xs), 2), "median": round(statistics.median(xs), 2),
            "std": round(statistics.pstdev(xs), 2), "min": round(min(xs), 2), "max": round(max(xs), 2)}


def _envelope(vals: list[float], wf_flags: list[bool]) -> dict:
    n = len(vals)
    pct_pos = 100 * sum(v > 0 for v in vals) / n
    wf_rate = 100 * sum(wf_flags) / n
    s = _stats(vals)
    return {**s, "pct_phases_positive": round(pct_pos, 0), "wf_pass_rate_pct": round(wf_rate, 0)}


def _robust(env: dict, n: int) -> bool:
    return bool(
        n >= MIN_PHASES and env["median"] > 0 and env["pct_phases_positive"] >= 70
        and env["wf_pass_rate_pct"] >= 60 and env["std"] < abs(env["mean"]) * 1.5
        and (env["max"] - env["min"]) <= 25
    )


def phase_sweep(snap, calendar, closes, args, mom_cache) -> dict:
    offsets = list(range(0, args.rebalance_days, args.step))
    rows = []
    for off in offsets:
        a = argparse.Namespace(**{**vars(args), "rebal_offset": off})
        rows.append(single_run(snap, calendar, closes, a, mom_cache))
    n = len(rows)

    ride_capm = [r["ride"]["capm_alpha_pct"] for r in rows]
    hold_capm = [r["hold"]["capm_alpha_pct"] for r in rows]
    exit_delta = [r["exit_value_capm_alpha_pp"] for r in rows]
    ride_wf = [r["ride"]["wf_pass"] for r in rows]
    hold_wf = [r["hold"]["wf_pass"] for r in rows]

    env_ride = _envelope(ride_capm, ride_wf)
    env_hold = _envelope(hold_capm, hold_wf)
    env_exit = _envelope(exit_delta, ride_wf)

    if n < MIN_PHASES:
        verdict = (f"INCONCLUSIVE -- only {n} phases (need >= {MIN_PHASES}; lower --step).")
    else:
        ride_robust = _robust(env_ride, n)
        exit_helps = env_exit["median"] > 0 and env_exit["pct_phases_positive"] >= 70
        verdict = (
            f"RIDE vs SPY: {'ROBUST alpha' if ride_robust else 'PHASE-LUCK / FRAGILE'} "
            f"(CAPM-a median {env_ride['median']:+.1f}%, {env_ride['pct_phases_positive']:.0f}% phases +, "
            f"WF {env_ride['wf_pass_rate_pct']:.0f}%). "
            f"EXIT vs HOLD: the trend exit "
            f"{'ADDS value' if exit_helps else 'does NOT add value'} "
            f"(RIDE-HOLD CAPM-a median {env_exit['median']:+.1f}pp, "
            f"{env_exit['pct_phases_positive']:.0f}% phases +)."
        )
    return {
        "n_phases": n, "offsets": offsets,
        "envelope": {"ride_vs_spy_capm_alpha": env_ride,
                     "hold_vs_spy_capm_alpha": env_hold,
                     "exit_value_ride_minus_hold_pp": env_exit},
        "per_phase": rows,
        "verdict": verdict,
    }


# --------------------------------------------------------------------------- #
# Smoke: synthetic panel (no snapshot), proves the pipeline reaches a verdict.
# --------------------------------------------------------------------------- #
def smoke() -> dict:
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2022-06-01", periods=900)
    tickers = [f"T{i:02d}" for i in range(40)]
    price_data = {}
    for k, t in enumerate(tickers):
        drift = 0.0010 if k < 8 else (-0.0003 if k < 20 else 0.0002)  # a few strong trenders
        px = 50 * np.exp(np.cumsum(rng.normal(drift, 0.02, len(idx))))
        price_data[t] = pd.DataFrame({"Close": px}, index=idx)
    spy = pd.DataFrame({"Close": 400 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(idx))))}, index=idx)

    class _Snap:
        pass
    snap = _Snap()
    snap.price_data = price_data
    snap.spy_df = spy

    closes = _build_close_matrix(price_data)
    window = idx[300:]  # leave warmup for momentum + SMA
    calendar = window
    args = argparse.Namespace(
        top_n=8, rebalance_days=63, rebal_offset=0, cost_bps=5.0,
        exit_rule="sma", exit_sma=50, trail_pct=0.2, step=21, mom_lookback=252,
    )
    mom_cache: dict = {}
    res = single_run(snap, calendar, closes, args, mom_cache)
    ok = (
        all(k in res for k in ("spy", "hold", "ride"))
        and isinstance(res["exit_value_capm_alpha_pp"], float)
        and res["ride_exits"] >= 0
        and res["hold"]["total_return_pct"] is not None
    )
    return {"smoke_pass": bool(ok), "n_days": len(calendar),
            "hold_total_pct": res["hold"]["total_return_pct"],
            "ride_total_pct": res["ride"]["total_return_pct"],
            "spy_total_pct": res["spy"]["total_return_pct"],
            "ride_exits": res["ride_exits"]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Trend-ride study (broad-universe momentum + per-name trend exit).")
    ap.add_argument("--snapshot-id", help="frozen snapshot id (broad_pit recommended)")
    ap.add_argument("--top-n", type=int, default=20, help="names held (default 20).")
    ap.add_argument("--mom-lookback", type=int, default=252,
                    help="momentum lookback in trading days, skip-month fixed at 21 "
                         "(default 252 = classic 12-1; 126 = 6-1, 63 = 3-1). Shorter "
                         "catches newer trends/names but is noisier / higher-turnover.")
    ap.add_argument("--rebalance-days", type=int, default=63, help="re-rank cadence (default 63 = quarterly).")
    ap.add_argument("--rebal-offset", type=int, default=0, help="phase offset for a single run.")
    ap.add_argument("--cost-bps", type=float, default=5.0, help="one-way cost bps (default 5).")
    ap.add_argument("--exit-rule", choices=("sma", "trail", "mom"), default="sma",
                    help="per-name trend exit (default sma).")
    ap.add_argument("--exit-sma", type=int, default=50, help="SMA window for --exit-rule sma (default 50).")
    ap.add_argument("--trail-pct", type=float, default=0.20, help="trailing-stop drop for --exit-rule trail (0.20).")
    ap.add_argument("--phase-sweep", action="store_true", help="sweep --rebal-offset and report the envelope.")
    ap.add_argument("--step", type=int, default=7, help="phase step in trading days (default 7).")
    ap.add_argument("--output", help="write JSON report here.")
    ap.add_argument("--smoke", action="store_true", help="synthetic self-test, no snapshot.")
    args = ap.parse_args()

    if args.smoke:
        out = smoke()
        print(json.dumps(out, indent=2))
        return 0 if out["smoke_pass"] else 1

    if not args.snapshot_id:
        ap.error("--snapshot-id required (or use --smoke)")

    from src.storage.snapshot import load_snapshot
    snap = load_snapshot(args.snapshot_id)
    if snap.spy_df is None or snap.spy_df.empty:
        raise SystemExit(f"snapshot {args.snapshot_id} has no SPY frame")

    start = pd.Timestamp(snap.manifest.window_start)
    end = pd.Timestamp(snap.manifest.window_end)
    spy_idx = snap.spy_df.index
    calendar = spy_idx[(spy_idx >= start) & (spy_idx <= end)]
    if calendar.empty:
        raise SystemExit("no SPY rows inside the snapshot window")
    closes = _build_close_matrix(snap.price_data)
    mom_cache: dict = {}

    report: dict = {
        "snapshot_id": args.snapshot_id,
        "universe_label": snap.manifest.universe_label,
        "window": {"start": start.date().isoformat(), "end": end.date().isoformat(),
                   "n_trading_days": int(len(calendar))},
        "params": {"top_n": args.top_n, "mom_lookback": args.mom_lookback,
                   "rebalance_days": args.rebalance_days,
                   "cost_bps": args.cost_bps, "exit_rule": args.exit_rule,
                   "exit_sma": args.exit_sma, "trail_pct": args.trail_pct},
        "held_names_momentum_surfaced": held_names(snap, closes, calendar, args, mom_cache),
    }
    if args.phase_sweep:
        report["phase_sweep"] = phase_sweep(snap, calendar, closes, args, mom_cache)
    else:
        report["single_run"] = single_run(snap, calendar, closes, args, mom_cache)

    print(json.dumps(report, indent=2, default=str))
    if args.output:
        outp = Path(args.output)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(report, indent=2, default=str))
        print(f"\nwrote {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
