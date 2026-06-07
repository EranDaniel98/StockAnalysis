# /// script
# dependencies = ["pandas", "numpy"]
# ///
"""Right-tail composite variant — does a MOMENTUM-tilted blend beat equal-weight
at ranking the biggest risers?

The decomposition (factor_horizon_decomp) showed momentum carries the tail (lift
2.08) and the equal m+q+v+pead blend DILUTES it (lift 1.25). This scores several
weight schemes through the same right-tail harness so we can pick the blend that
maximizes precision@K on the biggest risers — then the crash-risk cost is
measured separately via the trading backtest (drawdown).

Schemes (factor: weight): the current equal blend, momentum-only, and two tilts.

    uv run python -m scripts.research.right_tail_variant \\
        --snapshots 2020-22=2c853f10c6638fc0,... --horizons 63,126 --top-k 24 --step 21
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np  # noqa: F401  (used via harness helpers)
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.right_tail_harness import (  # noqa: E402
    DECILE, _LOOKBACK, _agg, _fwd_returns, _score, _setup,
)
from src.factors.composite import combine as combine_factors  # noqa: E402
from src.factors.momentum import momentum_12_1  # noqa: E402
from src.factors.pead import pead_factor  # noqa: E402
from src.factors.quality import quality_factor  # noqa: E402
from src.factors.value import value_factor  # noqa: E402

# scheme name -> {factor: weight}. Factors absent from a scheme are dropped.
SCHEMES = {
    "equal(m+q+v+p)": {"m": 1.0, "q": 1.0, "v": 1.0, "p": 1.0},   # current production blend
    "mom_only":       {"m": 1.0},
    "mom+val(6/4)":   {"m": 0.6, "v": 0.4},
    "momheavy(5/3/1/1)": {"m": 0.5, "v": 0.3, "q": 0.1, "p": 0.1},
}


def _frames(prices, universe, fund_loader, earnings, d) -> dict[str, pd.DataFrame]:
    """Compute the 4 standalone factor frames at d (empty df if uncomputable)."""
    out: dict[str, pd.DataFrame] = {}
    def _try(fn):
        try:
            df = fn()
            return df if df is not None and not df.empty else pd.DataFrame()
        except Exception:
            return pd.DataFrame()
    out["m"] = _try(lambda: momentum_12_1(prices, d))
    out["q"] = _try(lambda: quality_factor(fund_loader, universe, d)) if fund_loader else pd.DataFrame()
    out["v"] = _try(lambda: value_factor(fund_loader, prices, universe, d)) if fund_loader else pd.DataFrame()
    out["p"] = _try(lambda: pead_factor(earnings, d, prices=prices)) if earnings else pd.DataFrame()
    return out


def _scheme_order(frames: dict[str, pd.DataFrame], scheme: dict[str, float], k: int) -> list[str]:
    fr, wt = [], []
    for f, w in scheme.items():
        df = frames.get(f)
        if df is not None and not df.empty:
            fr.append(df)
            wt.append(w)
    if not fr:
        return []
    combined = combine_factors(fr, min_overlap=1, weights=wt)
    if combined is None or combined.empty:
        return []
    return combined.sort_values("rank")["ticker"].tolist()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshots", required=True)
    ap.add_argument("--horizons", default="63,126")
    ap.add_argument("--top-k", type=int, default=24)
    ap.add_argument("--step", type=int, default=21)
    args = ap.parse_args()

    windows = [p.split("=") for p in args.snapshots.split(",")]
    horizons = [int(h) for h in args.horizons.split(",")]
    K = args.top_k

    # res[X][scheme][label] = list of metric dicts
    res = {X: {s: {} for s in SCHEMES} for X in horizons}
    for label, snap_id in windows:
        print(f"[{label}] loading {snap_id}...", flush=True)
        prices, universe, earnings, fund_loader, sectors, cal = _setup(snap_id)
        maxX = max(horizons)
        dates = list(range(_LOOKBACK, len(cal) - maxX, args.step))
        print(f"[{label}] scoring {len(dates)} dates x {len(SCHEMES)} schemes...", flush=True)
        acc = {X: {s: [] for s in SCHEMES} for X in horizons}
        for i in dates:
            d = cal[i]
            fr = _frames(prices, universe, fund_loader, earnings, d)
            orders = {s: _scheme_order(fr, w, K) for s, w in SCHEMES.items()}
            for X in horizons:
                fwd = _fwd_returns(prices, universe, d, cal[i + X])
                for s in SCHEMES:
                    order = orders[s]
                    if not order:
                        continue
                    m = _score(order[:K], order, fwd, K)
                    if m is not None:
                        acc[X][s].append(m)
        for X in horizons:
            for s in SCHEMES:
                res[X][s][label] = acc[X][s]

    print("\n" + "=" * 74)
    print("RIGHT-TAIL VARIANT — weight-scheme top-%d vs realized top-decile risers" % K)
    print("random precision = %.2f (lift 1.0 = no skill)" % DECILE)
    print("=" * 74)
    for X in horizons:
        print(f"\n### Horizon X = {X}td (~{X/21:.0f}mo)")
        print(f"{'scheme':20}{'precis@K':>9}{'lift':>6}{'sel_ret%':>9}{'rankIC':>8}{'win>rand':>9}")
        for s in SCHEMES:
            allrows, n_win, n_beat = [], 0, 0
            for label, _snap in windows:
                rows = res[X][s].get(label, [])
                if rows:
                    n_win += 1
                    allrows += rows
                    if _agg(rows, "prec")[0] > DECILE:
                        n_beat += 1
            if not allrows:
                print(f"{s:20}{'—':>9}"); continue
            p, _ = _agg(allrows, "prec"); l, _ = _agg(allrows, "lift")
            sel, _ = _agg(allrows, "sel"); ic, _ = _agg(allrows, "ic")
            print(f"{s:20}{p:>9.3f}{l:>6.2f}{sel:>+9.2f}{ic:>+8.3f}{f'{n_beat}/{n_win}':>9}")
    print("\nCAVEAT: tail-precision only (no trading / drawdown). min_overlap=1 (permissive). "
          "The momentum-tilt's CRASH-RISK cost is measured separately via the backtest "
          "(max-DD: momentum-heavy >> equal blend). Best horizon 3-6mo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
