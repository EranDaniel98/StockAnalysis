# /// script
# dependencies = ["pandas", "numpy"]
# ///
"""Factor x horizon decomposition — WHICH factor carries the right-tail skill at X?

The composite harness (right_tail_harness) showed the BLEND ranks the biggest
risers with lift ~1.25, strongest at 3-6mo. This decomposes it: score EACH
factor's standalone ranking (momentum / quality / value / PEAD) against realized
top-decile forward-X-day risers, so you can horizon-MATCH the weights — lean on
whichever factor actually owns the tail at the horizon X you care about.

Same machinery + metrics as right_tail_harness (precision@K vs random 0.10,
lift, sel_return, rank-IC), reusing its loaders. Per window, phase-averaged via
the date sweep.

    uv run python -m scripts.research.factor_horizon_decomp \\
        --snapshots 2020-22=2c853f10c6638fc0,... --horizons 21,63,126 --top-k 24 --step 21
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.right_tail_harness import (  # noqa: E402
    DECILE, _LOOKBACK, _agg, _fwd_returns, _score, _setup,
)
from src.factors.momentum import momentum_12_1  # noqa: E402
from src.factors.pead import pead_factor  # noqa: E402
from src.factors.quality import quality_factor  # noqa: E402
from src.factors.value import value_factor  # noqa: E402

FACTORS = ["momentum", "quality", "value", "pead"]


def _factor_order(name, prices, universe, fund_loader, earnings, d) -> list[str]:
    """Standalone factor ranking at d, best-first ticker order."""
    try:
        if name == "momentum":
            df = momentum_12_1(prices, d)
        elif name == "quality":
            df = quality_factor(fund_loader, universe, d) if fund_loader else None
        elif name == "value":
            df = value_factor(fund_loader, prices, universe, d) if fund_loader else None
        elif name == "pead":
            df = pead_factor(earnings, d, prices=prices) if earnings else None
        else:
            return []
    except Exception:
        return []
    if df is None or df.empty or "rank" not in df.columns:
        return []
    return df.sort_values("rank")["ticker"].tolist()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshots", required=True)
    ap.add_argument("--horizons", default="21,63,126")
    ap.add_argument("--top-k", type=int, default=24)
    ap.add_argument("--step", type=int, default=21)
    args = ap.parse_args()

    windows = [p.split("=") for p in args.snapshots.split(",")]
    horizons = [int(h) for h in args.horizons.split(",")]
    K = args.top_k

    # res[X][factor][label] = list of per-date metric dicts
    res = {X: {f: {} for f in FACTORS} for X in horizons}
    for label, snap_id in windows:
        print(f"[{label}] loading {snap_id}...", flush=True)
        prices, universe, earnings, fund_loader, sectors, cal = _setup(snap_id)
        maxX = max(horizons)
        dates = list(range(_LOOKBACK, len(cal) - maxX, args.step))
        print(f"[{label}] scoring {len(dates)} dates x {len(FACTORS)} factors x "
              f"{len(horizons)} horizons...", flush=True)
        acc = {X: {f: [] for f in FACTORS} for X in horizons}
        for i in dates:
            d = cal[i]
            orders = {f: _factor_order(f, prices, universe, fund_loader, earnings, d)
                      for f in FACTORS}
            for X in horizons:
                fwd = _fwd_returns(prices, universe, d, cal[i + X])
                for f in FACTORS:
                    order = orders[f]
                    if not order:
                        continue
                    s = _score(order[:K], order, fwd, K)
                    if s is not None:
                        acc[X][f].append(s)
        for X in horizons:
            for f in FACTORS:
                res[X][f][label] = acc[X][f]

    # ---- report ----
    print("\n" + "=" * 76)
    print("FACTOR x HORIZON — standalone top-%d vs realized top-decile risers" % K)
    print("random precision = %.2f (lift 1.0 = no skill)" % DECILE)
    print("=" * 76)
    for X in horizons:
        print(f"\n### Horizon X = {X}td (~{X/21:.0f}mo)")
        print(f"{'factor':10}{'precis@K':>9}{'lift':>6}{'sel_ret%':>9}{'rankIC':>8}{'win>rand':>9}{'ndates':>7}")
        for f in FACTORS:
            allrows = []
            n_win = n_beat = 0
            for label, _snap in windows:
                rows = res[X][f].get(label, [])
                if rows:
                    n_win += 1
                    allrows += rows
                    if _agg(rows, "prec")[0] > DECILE:
                        n_beat += 1
            if not allrows:
                print(f"{f:10}{'—':>9}"); continue
            p, _ = _agg(allrows, "prec"); l, _ = _agg(allrows, "lift")
            s, _ = _agg(allrows, "sel"); ic, _ = _agg(allrows, "ic")
            print(f"{f:10}{p:>9.3f}{l:>6.2f}{s:>+9.2f}{ic:>+8.3f}{f'{n_beat}/{n_win}':>9}{len(allrows):>7}")
    print("\nCAVEAT: standalone per-factor rankings (raw — no sector-neutral / hysteresis / "
          "gate). Quality/value need EDGAR coverage, PEAD ~60-70% coverage, so per-factor "
          "top-K is drawn from its covered set. Pooled across windows; per-window beat-rate shown.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
