# /// script
# dependencies = ["pandas", "numpy"]
# ///
"""Calibration + abstention study for the momval (0.6/0.4) biggest-risers book.

Two questions, both answered WALK-FORWARD (train strictly on dates whose
forward horizon has fully elapsed — no outcome leakage):

  1. CALIBRATION — what probability does a composite rank actually carry?
     Expanding-window binned P(top-decile riser over X | normalized-rank bin),
     evaluated as a reliability table + Brier skill vs the 0.10 base rate.
     Turns "lift 1.67" into a number the screener can display per pick.

  2. ABSTENTION — can we tell WHEN the ranking is weak, before the fact?
     Six PIT date-level features (momentum dispersion / top-K conviction /
     mom-val agreement / breadth / VIX / SPY trend). Per feature, a
     walk-forward policy: trade only when the feature is on the good side of
     its past median, where "good side" = sign of the feature's past
     correlation with selection return (no hand-picked direction).

STATISTICAL HONESTY: ~96 unique monthly dates, overlapping 63/126td outcomes
-> few independent observations, and 6 features x 2 horizons = multiplicity.
A feature must help on BOTH horizons and most windows to be believed.

    uv run python -m scripts.research.calibration_abstention \\
        --snapshots 2018-20=acd1e7401c6484cf,... --top-k 24 --step 21
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

from scripts.research.high_52w_probe import _setup_lite  # noqa: E402
from scripts.research.right_tail_harness import (  # noqa: E402
    DECILE, _LOOKBACK, _fwd_returns, _spearman,
)
from src.factors.composite import combine as combine_factors  # noqa: E402
from src.factors.momentum import momentum_12_1  # noqa: E402
from src.factors.value import value_factor  # noqa: E402
from src.storage.snapshot import load_snapshot  # noqa: E402

WEIGHTS = {"m": 0.6, "v": 0.4}            # the shipped momval book
HORIZONS = (63, 126)
NR_BIN_EDGES = [0.0, 0.02, 0.05, 0.10, 0.20, 0.40, 1.0]   # top-24/~500 ~ top 5%
MIN_BIN_TRAIN = 30        # rows per bin before trusting its frequency
MIN_TRAIN_DATES = 10      # distinct elapsed dates before calibration starts
MIN_POLICY_DATES = 24     # elapsed dates before the abstention policy starts
FEATURES = ["mom_disp", "top_z", "agree", "breadth", "vix", "spy_trend"]


def _last_at(df: pd.DataFrame | None, d: pd.Timestamp, col: str = "Close") -> float | None:
    if df is None or df.empty or col not in df.columns:
        return None
    s = df[df.index <= d][col].dropna()
    return float(s.iloc[-1]) if len(s) else None


def _date_features(m: pd.DataFrame, v: pd.DataFrame, order: list[str],
                   k: int, vix_df, spy_df, d) -> dict:
    f: dict[str, float | None] = {}
    raw = m["raw"]
    f["mom_disp"] = float(raw.quantile(0.75) - raw.quantile(0.25))
    zmap = dict(zip(m["ticker"], m["z_score"]))
    zs = [zmap[t] for t in order[:k] if t in zmap]
    f["top_z"] = float(np.mean(zs)) if zs else None
    if not v.empty:
        j = m[["ticker", "rank"]].merge(v[["ticker", "rank"]], on="ticker",
                                        suffixes=("_m", "_v"))
        f["agree"] = _spearman(j["rank_m"].values, j["rank_v"].values)
    else:
        f["agree"] = None
    f["breadth"] = float((raw > 0).mean())
    f["vix"] = _last_at(vix_df, d)
    spy = spy_df["Close"][spy_df.index <= d].dropna() if spy_df is not None else pd.Series(dtype=float)
    f["spy_trend"] = (float(spy.iloc[-1] / spy.tail(200).mean() - 1.0)
                      if len(spy) >= 200 else None)
    return f


def build_dataset(windows: list[list[str]], k: int, step: int):
    """One chronological stream: per-name calibration rows + per-date feature rows.
    Overlapping snapshot windows are deduped by date (first window wins)."""
    name_rows: list[dict] = []
    date_rows: list[dict] = []
    seen: set = set()
    for label, snap_id in windows:
        print(f"[{label}] loading {snap_id}...", flush=True)
        prices, universe, fund_loader, cal = _setup_lite(snap_id)
        snap = load_snapshot(snap_id)
        vix_df, spy_df = snap.vix_df, snap.spy_df
        maxX = max(HORIZONS)
        idxs = [i for i in range(_LOOKBACK, len(cal) - maxX, step) if cal[i] not in seen]
        print(f"[{label}] scoring {len(idxs)} new dates...", flush=True)
        for i in idxs:
            d = cal[i]
            seen.add(d)
            m = momentum_12_1(prices, d)
            try:
                v = value_factor(fund_loader, prices, universe, d) if fund_loader else pd.DataFrame()
            except Exception:
                v = pd.DataFrame()
            if v is None:
                v = pd.DataFrame()
            frames, wts = ([m, v], [0.6, 0.4]) if not v.empty else ([m], [1.0])
            combined = combine_factors(frames, min_overlap=1, weights=wts)
            if combined is None or combined.empty or m.empty:
                continue
            order = combined.sort_values("rank")["ticker"].tolist()
            n = len(order)
            nr = {t: idx / max(1, n - 1) for idx, t in enumerate(order)}

            fwd, dec, fwd_end = {}, {}, {}
            for X in HORIZONS:
                fwd[X] = _fwd_returns(prices, universe, d, cal[i + X])
                rets = np.array(list(fwd[X].values()))
                names = np.array(list(fwd[X].keys()))
                n_dec = max(1, int(round(len(names) * DECILE)))
                dec[X] = set(names[np.argsort(-rets)[:n_dec]])
                fwd_end[X] = cal[i + X]
            if any(len(fwd[X]) < 50 for X in HORIZONS):
                continue

            for t in order:
                if t not in fwd[HORIZONS[0]] or t not in fwd[HORIZONS[1]]:
                    continue
                name_rows.append({
                    "date": d, "window": label, "ticker": t, "nr": nr[t],
                    **{f"y{X}": int(t in dec[X]) for X in HORIZONS},
                    **{f"end{X}": fwd_end[X] for X in HORIZONS},
                })

            row = {"date": d, "window": label,
                   **_date_features(m, v, order, k, vix_df, spy_df, d)}
            for X in HORIZONS:
                picks = [t for t in order[:k] if t in fwd[X]]
                if picks:
                    uni = float(np.mean(list(fwd[X].values())))
                    row[f"prec{X}"] = sum(1 for t in picks if t in dec[X]) / len(picks)
                    row[f"sel{X}"] = (float(np.mean([fwd[X][t] for t in picks])) - uni) * 100
                row[f"end{X}"] = fwd_end[X]
            date_rows.append(row)
    nf = pd.DataFrame(name_rows).sort_values("date").reset_index(drop=True)
    df = pd.DataFrame(date_rows).sort_values("date").reset_index(drop=True)
    return nf, df


# ---------------------------------------------------------------- calibration
def run_calibration(nf: pd.DataFrame, X: int) -> None:
    edges = NR_BIN_EDGES
    labels = [f"{edges[j]*100:g}-{edges[j+1]*100:g}%" for j in range(len(edges) - 1)]
    nf = nf.copy()
    nf["bin"] = pd.cut(nf["nr"], bins=edges, labels=labels, include_lowest=True)
    dates = sorted(nf["date"].unique())
    preds: list[tuple[str, float, int]] = []   # (bin, p_hat, y)
    for t in dates:
        train = nf[nf[f"end{X}"] < t]
        if train["date"].nunique() < MIN_TRAIN_DATES:
            continue
        freq = train.groupby("bin", observed=False)[f"y{X}"].agg(["mean", "count"])
        cur = nf[nf["date"] == t]
        for _, r in cur.iterrows():
            b = r["bin"]
            p = (float(freq.loc[b, "mean"])
                 if b in freq.index and freq.loc[b, "count"] >= MIN_BIN_TRAIN else DECILE)
            preds.append((str(b), p, int(r[f"y{X}"])))
    if not preds:
        print(f"  (X={X}) no evaluation rows after burn-in")
        return
    pr = pd.DataFrame(preds, columns=["bin", "p", "y"])
    brier = float(((pr["p"] - pr["y"]) ** 2).mean())
    brier0 = float(((DECILE - pr["y"]) ** 2).mean())
    print(f"\n### Calibration, X={X}td — walk-forward reliability "
          f"({pr.shape[0]} pick-rows over {nf['date'].nunique()} dates)")
    print(f"{'rank bin':>10}{'pred P':>8}{'realized':>10}{'n':>8}")
    for b in labels:
        sub = pr[pr["bin"] == b]
        if sub.empty:
            continue
        print(f"{b:>10}{sub['p'].mean():>8.3f}{sub['y'].mean():>10.3f}{len(sub):>8}")
    print(f"  Brier {brier:.4f} vs base-rate(0.10) {brier0:.4f} "
          f"-> skill {1 - brier / brier0:+.3%}")


# ----------------------------------------------------------------- abstention
def run_abstention(df: pd.DataFrame, X: int, thr_q: float = 0.5) -> None:
    print(f"\n### Abstention, X={X}td — walk-forward trade/skip per feature "
          f"(threshold = past q{thr_q:g} on the bad side, direction = sign of past corr with sel)")
    print(f"{'feature':>10}{'corr(sel)':>10}{'cover':>7}"
          f"{'sel all':>9}{'sel trd':>9}{'sel skp':>9}{'prec all':>9}{'prec trd':>9}{'win':>6}")
    sel_c, prec_c, end_c = f"sel{X}", f"prec{X}", f"end{X}"
    base = df.dropna(subset=[sel_c]).reset_index(drop=True)
    for feat in FEATURES:
        d = base.dropna(subset=[feat])
        rho = _spearman(d[feat].values, d[sel_c].values)
        traded_idx, skipped_idx = [], []
        for i, r in d.iterrows():
            past = d[d[end_c] < r["date"]]
            if len(past) < MIN_POLICY_DATES:
                continue
            srho = _spearman(past[feat].values, past[sel_c].values)
            if srho is None:
                continue
            sign = 1.0 if srho >= 0 else -1.0
            # thr_q is the quantile of the BAD tail: with a negative corr,
            # q0.75 means "abstain only above the past 75th percentile".
            q = (1.0 - thr_q) if sign > 0 else thr_q
            thr = float(past[feat].quantile(q))
            (traded_idx if (r[feat] - thr) * sign > 0 else skipped_idx).append(i)
        evald = d.loc[traded_idx + skipped_idx]
        if evald.empty:
            print(f"{feat:>10}{'—':>10}")
            continue
        trd, skp = d.loc[traded_idx], d.loc[skipped_idx]
        cover = len(trd) / len(evald)
        # per-window win: traded median sel beats that window's all-dates median
        wins, tot = 0, 0
        for w, sub in evald.groupby("window"):
            tw = trd[trd["window"] == w]
            if len(sub) >= 4 and len(tw) >= 2:
                tot += 1
                wins += int(tw[sel_c].median() > sub[sel_c].median())
        print(f"{feat:>10}{rho:>+10.3f}{cover:>7.0%}"
              f"{evald[sel_c].median():>+9.2f}{trd[sel_c].median():>+9.2f}"
              f"{(skp[sel_c].median() if len(skp) else float('nan')):>+9.2f}"
              f"{evald[prec_c].median():>9.3f}{trd[prec_c].median():>9.3f}"
              f"{f'{wins}/{tot}':>6}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshots", required=True)
    ap.add_argument("--top-k", type=int, default=24)
    ap.add_argument("--step", type=int, default=21)
    ap.add_argument("--cache-dir", default="data/calib_cache",
                    help="parquet cache for the built dataset (delete to rebuild)")
    args = ap.parse_args()
    windows = [p.split("=") for p in args.snapshots.split(",")]

    cache = Path(args.cache_dir)
    nf_p, df_p = cache / "name_rows.parquet", cache / "date_rows.parquet"
    if nf_p.exists() and df_p.exists():
        print(f"loading dataset from cache {cache}/ (delete to rebuild)")
        nf, df = pd.read_parquet(nf_p), pd.read_parquet(df_p)
    else:
        nf, df = build_dataset(windows, args.top_k, args.step)
        cache.mkdir(parents=True, exist_ok=True)
        nf.to_parquet(nf_p, index=False)
        df.to_parquet(df_p, index=False)
    print(f"\ndataset: {len(nf)} name-rows, {len(df)} unique dates "
          f"({df['date'].min().date()} .. {df['date'].max().date()})")

    print("\n" + "=" * 74)
    print("CALIBRATION + ABSTENTION — momval(0.6/0.4) top-%d, walk-forward" % args.top_k)
    print("=" * 74)
    for X in HORIZONS:
        run_calibration(nf, X)
    for X in HORIZONS:
        run_abstention(df, X, thr_q=0.5)
    # sensitivity: abstain only in the worst QUARTILE of each feature (higher
    # coverage) — a believable feature must survive this threshold change.
    for X in HORIZONS:
        run_abstention(df, X, thr_q=0.75)
    print("\nCAVEATS: ~%d unique monthly dates, overlapping %d/%dtd outcomes -> few"
          " independent obs; 6 features x 2 horizons = multiplicity. Believe a"
          " feature only if it helps on BOTH horizons and most windows. Calibration"
          " bins below MIN_BIN_TRAIN=%d fall back to the 0.10 base rate."
          % (len(df), *HORIZONS, MIN_BIN_TRAIN))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
