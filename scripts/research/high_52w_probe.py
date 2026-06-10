# /// script
# dependencies = ["pandas", "numpy"]
# ///
"""52-week-high orthogonality probe — does George-Hwang nearness-to-high add
anything BEYOND 12-1 momentum for ranking the biggest risers?

George & Hwang (2004): price / 52w-high predicts returns and (they argue)
subsumes momentum. But the two are mechanically correlated — a name that
rallied 12 months is usually near its high. So this probe is GATED:

  1. Orthogonality gate — per scored date, Spearman(h52 raw, mom raw) over
     the cross-section + top-K pick overlap. If the median correlation is
     ~0.9 the factor is a momentum clone and the probe stops there.
  2. Tail value — only meaningful if gate passes: score h52 alone and in
     blends through the right-tail harness vs the established baselines
     (mom_only lift 2.08, mom+val(6/4) 1.67 @63td).

    uv run python -m scripts.research.high_52w_probe \\
        --snapshots 2018-20=acd1e7401c6484cf,... --horizons 63,126 --top-k 24 --step 21
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

from scripts.research.right_tail_harness import (  # noqa: E402
    DECILE, _LOOKBACK, _agg, _fwd_returns, _score, _spearman,
)
from scripts.run_factor_backtest import _load_fundamentals_if_needed  # noqa: E402
from src.factors.composite import combine as combine_factors  # noqa: E402
from src.factors.momentum import momentum_12_1  # noqa: E402
from src.factors.price_quality import drop_price_artifacts  # noqa: E402
from src.factors.value import value_factor  # noqa: E402
from src.storage.snapshot import load_snapshot  # noqa: E402

# scheme name -> {factor: weight}; m = 12-1 momentum, v = value, h = 52w-high
SCHEMES = {
    "mom_only":      {"m": 1.0},                      # tail champion (lift 2.08)
    "h52_only":      {"h": 1.0},
    "mom+h52(5/5)":  {"m": 0.5, "h": 0.5},
    "mom+val(6/4)":  {"m": 0.6, "v": 0.4},            # the shipped momval book
    "m+v+h(5/3/2)":  {"m": 0.5, "v": 0.3, "h": 0.2},  # candidate momval upgrade
}


def high_52w(prices, as_of, *, lookback: int = 252, min_history_days: int = 252) -> pd.DataFrame:
    """raw = last close / max close over the trailing ``lookback`` sessions ≤ as_of."""
    as_of_ts = pd.Timestamp(as_of)
    rows: list[dict] = []
    for ticker, df in prices.items():
        if df is None or df.empty or "Close" not in df.columns:
            continue
        eligible = df[df.index <= as_of_ts]
        if len(eligible) < min_history_days:
            continue
        window = eligible["Close"].tail(lookback)
        hi, cur = float(window.max()), float(window.iloc[-1])
        if pd.isna(hi) or hi <= 0 or pd.isna(cur):
            continue
        rows.append({"ticker": ticker, "raw": cur / hi})
    if not rows:
        return pd.DataFrame(columns=["ticker", "raw", "rank", "z_score"])
    out = pd.DataFrame(rows)
    out["rank"] = out["raw"].rank(ascending=False, method="min").astype(int)
    mu, sigma = float(out["raw"].mean()), float(out["raw"].std(ddof=0))
    out["z_score"] = (out["raw"] - mu) / sigma if sigma > 0 else 0.0
    return out.sort_values("rank").reset_index(drop=True)


def _setup_lite(snap_id: str):
    """Snapshot + EDGAR PIT only — no earnings/sectors (schemes here are m/v/h)."""
    snap = load_snapshot(snap_id)
    prices = snap.price_data
    end = max((df.index.max() for df in prices.values() if df is not None and not df.empty),
              default=None)
    prices, _ = drop_price_artifacts(prices, end, lookback_rows=10**9)
    universe = sorted(prices.keys())
    args = SimpleNamespace(factor="composite", snapshot_id=snap_id)
    fund_loader = _load_fundamentals_if_needed(args, universe)
    return prices, universe, fund_loader, snap.spy_df.index


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

    res = {X: {s: {} for s in SCHEMES} for X in horizons}
    gate: dict[str, dict[str, list]] = {}  # label -> {corr: [], overlap: []}
    for label, snap_id in windows:
        print(f"[{label}] loading {snap_id}...", flush=True)
        prices, universe, fund_loader, cal = _setup_lite(snap_id)
        maxX = max(horizons)
        dates = list(range(_LOOKBACK, len(cal) - maxX, args.step))
        print(f"[{label}] scoring {len(dates)} dates x {len(SCHEMES)} schemes...", flush=True)
        acc = {X: {s: [] for s in SCHEMES} for X in horizons}
        g = {"corr": [], "overlap": []}
        for i in dates:
            d = cal[i]
            frames = {
                "m": momentum_12_1(prices, d),
                "h": high_52w(prices, d),
                "v": pd.DataFrame(),
            }
            if fund_loader is not None:
                try:
                    v = value_factor(fund_loader, prices, universe, d)
                    frames["v"] = v if v is not None else pd.DataFrame()
                except Exception:
                    pass
            # ---- orthogonality gate ----
            m, h = frames["m"], frames["h"]
            if not m.empty and not h.empty:
                j = m[["ticker", "raw"]].merge(h[["ticker", "raw"]], on="ticker",
                                               suffixes=("_m", "_h"))
                rho = _spearman(j["raw_m"].values, j["raw_h"].values)
                if rho is not None:
                    g["corr"].append(rho)
                top_m = set(m["ticker"].head(K))
                top_h = set(h["ticker"].head(K))
                g["overlap"].append(len(top_m & top_h) / K)
            # ---- tail scoring ----
            orders = {s: _scheme_order(frames, w, K) for s, w in SCHEMES.items()}
            for X in horizons:
                fwd = _fwd_returns(prices, universe, d, cal[i + X])
                for s in SCHEMES:
                    if orders[s]:
                        sc = _score(orders[s][:K], orders[s], fwd, K)
                        if sc is not None:
                            acc[X][s].append(sc)
        gate[label] = g
        for X in horizons:
            for s in SCHEMES:
                res[X][s][label] = acc[X][s]

    print("\n" + "=" * 74)
    print("52W-HIGH PROBE — orthogonality gate")
    print("=" * 74)
    print(f"{'window':9}{'spearman(h52,mom)':>19}{'top-%d overlap' % K:>16}{'ndates':>8}")
    all_corr, all_ov = [], []
    for label, _ in windows:
        g = gate[label]
        all_corr += g["corr"]
        all_ov += g["overlap"]
        c = float(np.median(g["corr"])) if g["corr"] else float("nan")
        o = float(np.median(g["overlap"])) if g["overlap"] else float("nan")
        print(f"{label:9}{c:>19.3f}{o:>16.2f}{len(g['corr']):>8}")
    print(f"{'POOLED':9}{float(np.median(all_corr)):>19.3f}"
          f"{float(np.median(all_ov)):>16.2f}{len(all_corr):>8}")

    print("\n" + "=" * 74)
    print("52W-HIGH PROBE — tail value, top-%d vs realized top-decile risers" % K)
    print("random precision = %.2f (lift 1.0 = no skill)" % DECILE)
    print("=" * 74)
    for X in horizons:
        print(f"\n### Horizon X = {X}td (~{X/21:.0f}mo)")
        print(f"{'scheme':16}{'precis@K':>9}{'lift':>6}{'sel_ret%':>9}{'rankIC':>8}{'win>rand':>9}")
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
                print(f"{s:16}{'—':>9}")
                continue
            p, _ = _agg(allrows, "prec")
            l, _ = _agg(allrows, "lift")
            sel, _ = _agg(allrows, "sel")
            ic, _ = _agg(allrows, "ic")
            print(f"{s:16}{p:>9.3f}{l:>6.2f}{sel:>+9.2f}{ic:>+8.3f}{f'{n_beat}/{n_win}':>9}")
    print("\nGATE RULE: median |spearman| >= ~0.90 -> momentum clone, ignore the tail table. "
          "Moderate corr (~0.5-0.8) is EXPECTED (mechanically related); then judge on "
          "whether any h-blend beats mom_only / mom+val(6/4) on lift + sel_ret per window.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
