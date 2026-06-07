# /// script
# dependencies = ["pandas", "numpy"]
# ///
"""Right-tail measurement harness — does the composite RANK the biggest risers?

The system optimizes/validates the conditional MEAN (Sharpe, symmetric IC). The
goal "which stocks rise the MOST in X" is a sparse RIGHT-TAIL target. This
scores the production composite RANKING (m+q+v+PEAD, sector-neutral; no gate,
no hysteresis — those are trading overlays, not predictions) against realized
forward-X-day returns, cross-sectionally, per snapshot window:

  - precision@K : fraction of the top-K composite picks that were ACTUAL
                  top-decile risers over X (random null = the decile rate ~0.10).
  - lift        : precision@K / decile-rate (1.0 = no skill).
  - sel_return  : mean fwd-X return of the top-K MINUS the universe mean
                  (the selection's excess; the "rise more" part).
  - upside_cap  : sum(top-K fwd ret) / sum(oracle top-K fwd ret), >0 only.
  - rank_IC     : Spearman(composite rank, fwd-X return) over the cross-section.

Swept across rebalance dates (phase-averaged within a window) and reported
PER WINDOW (walk-forward view), never a single date. The gating question:
does precision@K beat the random null per window, at any (K, X)?

    uv run python -m scripts.research.right_tail_harness \\
        --snapshots 2018-20=acd1e7401c6484cf,2020-22=2c853f10c6638fc0,... \\
        --horizons 21,63,126 --top-k 24 --step 21
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_factor_backtest import (  # noqa: E402
    _close_on,
    _load_earnings_histories_if_pead,
    _load_fundamentals_if_needed,
    _load_sectors_if_sn_quality,
    _resolve_ranking,
)
from src.factors.price_quality import drop_price_artifacts  # noqa: E402
from src.storage.snapshot import load_snapshot  # noqa: E402

DECILE = 0.10
_LOOKBACK = 280  # trading rows of warm-up before the first scored date (12-1 mom)


def _spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    if len(a) < 5:
        return None
    ra, rb = pd.Series(a).rank().values, pd.Series(b).rank().values
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def _setup(snap_id: str):
    """Load snapshot + build the (frozen) factor loaders once."""
    snap = load_snapshot(snap_id)
    prices = snap.price_data
    end = max((df.index.max() for df in prices.values() if df is not None and not df.empty),
              default=None)
    prices, _ = drop_price_artifacts(prices, end, lookback_rows=10**9)  # same guard as the backtest
    universe = sorted(prices.keys())
    args = SimpleNamespace(
        factor="composite", snapshot_id=snap_id, include_pead=True,
        earnings_cache_dir="data/earnings_history",
        earnings_cache_max_age_hours=10**9,  # use cache as-is, never refetch
        sector_neutral_quality=True,
    )
    earnings = _load_earnings_histories_if_pead(args, universe, snap)
    fund_loader = _load_fundamentals_if_needed(args, universe)
    sectors = _load_sectors_if_sn_quality(args, universe)
    cal = snap.spy_df.index  # trading calendar
    return prices, universe, earnings, fund_loader, sectors, cal


def _fwd_returns(prices, universe, d, target) -> dict[str, float]:
    out = {}
    for t in universe:
        p0 = _close_on(prices, t, d)
        p1 = _close_on(prices, t, target)
        if p0 and p1 and p0 > 0:
            out[t] = p1 / p0 - 1.0
    return out


def _score(top_k: list[str], full_rank: list[str], fwd: dict[str, float], k: int) -> dict | None:
    names = [t for t in fwd]
    if len(names) < 50:
        return None
    rets = np.array([fwd[t] for t in names])
    n_dec = max(1, int(round(len(names) * DECILE)))
    dec = set(np.array(names)[np.argsort(-rets)[:n_dec]])  # realized top-decile
    picks = [t for t in top_k if t in fwd][:k]
    if not picks:
        return None
    prec = sum(1 for t in picks if t in dec) / len(picks)
    uni_mean = float(rets.mean())
    sel = float(np.mean([fwd[t] for t in picks])) - uni_mean
    oracle = float(np.sort(rets)[::-1][:len(picks)].sum())
    pick_sum = float(sum(fwd[t] for t in picks))
    upcap = (pick_sum / oracle) if oracle > 0 else None
    ranks = [t for t in full_rank if t in fwd]
    ic = _spearman(np.arange(len(ranks)), np.array([fwd[t] for t in ranks]))
    # composite rank ascending = best first; IC should be NEGATIVE corr(rank, ret)
    # so flip sign to make "higher IC = better".
    ic = (-ic) if ic is not None else None
    return {"prec": prec, "lift": prec / DECILE, "sel": sel * 100,
            "upcap": upcap, "ic": ic}


def _agg(rows: list[dict], key: str) -> tuple[float, float]:
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return float("nan"), float("nan")
    return float(np.median(vals)), float(np.mean(vals))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshots", required=True,
                    help="comma list of label=snapshot_id")
    ap.add_argument("--horizons", default="21,63,126")
    ap.add_argument("--top-k", type=int, default=24)
    ap.add_argument("--step", type=int, default=21, help="trading-day stride between scored dates")
    args = ap.parse_args()

    windows = [p.split("=") for p in args.snapshots.split(",")]
    horizons = [int(h) for h in args.horizons.split(",")]
    K = args.top_k

    # results[X][label] = list of per-date metric dicts
    results: dict[int, dict[str, list]] = {X: {} for X in horizons}
    for label, snap_id in windows:
        print(f"[{label}] loading {snap_id}...", flush=True)
        prices, universe, earnings, fund_loader, sectors, cal = _setup(snap_id)
        maxX = max(horizons)
        dates = list(range(_LOOKBACK, len(cal) - maxX, args.step))
        print(f"[{label}] scoring {len(dates)} cross-sections x {len(horizons)} horizons "
              f"({len(universe)} names)...", flush=True)
        per_X = {X: [] for X in horizons}
        for i in dates:
            d = cal[i]
            ranking, _ = _resolve_ranking(
                "composite", prices, fund_loader, d, universe,
                momentum_flavor="raw", composite_factors="mqv",
                sector_neutral_quality=True, sectors=sectors,
                include_pead=True, earnings_histories=earnings,
            )
            if ranking is None or ranking.empty:
                continue
            order = ranking["ticker"].tolist()  # ascending composite rank (best first)
            top_k = order[:K]
            for X in horizons:
                fwd = _fwd_returns(prices, universe, d, cal[i + X])
                s = _score(top_k, order, fwd, K)
                if s is not None:
                    per_X[X].append(s)
        for X in horizons:
            results[X][label] = per_X[X]

    # ---- report ----
    print("\n" + "=" * 78)
    print("RIGHT-TAIL HARNESS — composite top-%d vs realized top-decile risers" % K)
    print("=" * 78)
    for X in horizons:
        print(f"\n### Horizon X = {X} trading days "
              f"(~{X/21:.0f}mo) | random precision = {DECILE:.2f}, lift 1.0 = no skill")
        print(f"{'window':9}{'precis@K':>9}{'lift':>6}{'sel_ret%':>9}{'upcap':>7}{'rankIC':>8}{'ndates':>7}")
        allrows = []
        for label, _snap in windows:
            rows = results[X].get(label, [])
            allrows += rows
            if not rows:
                print(f"{label:9}{'—':>9}"); continue
            p, _ = _agg(rows, "prec"); l, _ = _agg(rows, "lift")
            s, _ = _agg(rows, "sel"); u, _ = _agg(rows, "upcap"); ic, _ = _agg(rows, "ic")
            print(f"{label:9}{p:>9.3f}{l:>6.2f}{s:>+9.2f}{u:>7.2f}{ic:>+8.3f}{len(rows):>7}")
        if allrows:
            pm, _ = _agg(allrows, "prec"); lm, _ = _agg(allrows, "lift")
            sm, _ = _agg(allrows, "sel"); icm, _ = _agg(allrows, "ic")
            n_win = sum(1 for label, _ in windows if results[X].get(label))
            n_beat = sum(1 for label, _ in windows
                         if results[X].get(label) and _agg(results[X][label], "prec")[0] > DECILE)
            print(f"{'POOLED':9}{pm:>9.3f}{lm:>6.2f}{sm:>+9.2f}{'':>7}{icm:>+8.3f}{len(allrows):>7}")
            print(f"  -> windows with median precision@K > random: {n_beat}/{n_win}")
    print("\nCAVEAT: pure cross-sectional ranking diagnostic (signal only, no gate/hysteresis/"
          "costs). Decile defined per-date over the available cross-section. Phase-averaged "
          "within window via the date sweep; judge PER WINDOW vs the random null, not pooled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
