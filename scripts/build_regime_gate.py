"""Panel idea #1 — Quality/Junk Regime Meta-Gate (test, not deploy).

The session's biggest finding: the PEAD+quality beta-neutral long-short sleeve is
regime-dependent (+α in flight-to-quality, −α in junk rallies, break-even overall).
This tests whether a WALK-FORWARD gate can detect the bad (junk-rally) regime ex-ante
and scale the sleeve toward FLAT (not flip — flipping is the falsified anti-pattern),
turning a break-even sleeve into a positive one.

Pipeline (all EOD, reuses factor_lab.Ctx):
  1. Per snapshot, per 21d rebalance: form the mqv+pead composite long-short decile
     spread -> sleeve return series (concatenated across 2018-2026).
  2. Gate features at each date (data <= date only): 20d junk-minus-quality return
     spread (ROA quintiles), VIX level, 20d VIX change, SPY drawdown-from-252d-high.
  3. Walk-forward expanding-window logistic: predict P(next sleeve return > 0);
     gated_ret = sleeve_ret * gate, gate = P (soft) or 1[P>0.5] (hard).
  4. Compare ungated vs gated: mean/yr, Sharpe, per-window, vs a DUTY-CYCLE-MATCHED
     permutation null (random gates, same % active) — the pre-registered bar.

    uv run python -m scripts.build_regime_gate --horizon 21
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from scripts.factor_lab import Ctx, base_signals, _z  # reuse the lab machinery

SNAP_ROOT = Path("data/snapshots")
# Contiguous 2018-2026 windows (incl. the junk-rally windows 2019 & 2020-H2).
WINDOWS = [
    ("2018-20", "acd1e7401c6484cf"),
    ("2020-22", "2c853f10c6638fc0"),
    ("2022-24", "1c1c314850bb7368"),
    ("2024-26", "ed270407fd89cf60"),
]
COMPOSITE_LEGS = ["mom_12_1", "quality", "value", "pead"]


def _vix_spy(snap: Path):
    def _close(p, cols=("Close", "close", "adj_close", "Adj Close")):
        df = pd.read_parquet(p)
        dc = next((c for c in ("date", "Date") if c in df.columns), df.columns[0])
        cc = next((c for c in cols if c in df.columns), None)
        return df.set_index(pd.to_datetime(df[dc]))[cc].sort_index()
    vix = _close(snap / "vix.parquet") if (snap / "vix.parquet").exists() else None
    spy = _close(snap / "spy.parquet") if (snap / "spy.parquet").exists() else None
    return vix, spy


def _sleeve_and_features(ctx: Ctx, i: int, horizon: int, vix: pd.Series, spy: pd.Series):
    """Return (sleeve_long_short_fwd_return, feature_dict) at rebalance index i, or None."""
    sigs = base_signals(ctx, i)
    legs = [s for s in COMPOSITE_LEGS if s in sigs]
    if len(legs) < 3:
        return None
    common = sigs[legs[0]].index
    for s in legs[1:]:
        common = common.intersection(sigs[s].index)
    if len(common) < 40:
        return None
    comp = sum(_z(sigs[s].loc[common]) for s in legs)
    n_dec = max(5, int(len(comp) * 0.10))
    longs = comp.nlargest(n_dec).index
    shorts = comp.nsmallest(n_dec).index
    fwd = ctx.panel.iloc[i + horizon] / ctx.panel.iloc[i] - 1.0
    sleeve = float(fwd[longs].mean() - fwd[shorts].mean())  # decile spread ~ beta-neutral

    ts = ctx.dates[i]
    # junk-minus-quality 20d spread (ROA quintiles; data <= ts)
    aod = ts.to_pydatetime().replace(tzinfo=__import__("datetime").timezone.utc)
    roa = {t: ctx.fund.lookup(t, aod).roa for t in common
           if ctx.fund.lookup(t, aod) is not None and ctx.fund.lookup(t, aod).roa is not None}
    feat = {}
    if len(roa) >= 40 and i >= 20:
        r = pd.Series(roa)
        ret20 = ctx.panel.iloc[i][r.index] / ctx.panel.iloc[i - 20][r.index] - 1.0
        q = r.rank(pct=True)
        junk = ret20[q <= 0.2].mean()
        qual = ret20[q >= 0.8].mean()
        feat["junk_quality_spread"] = float(junk - qual)  # +ve = junk winning = bad regime
    if vix is not None:
        v = vix.reindex(vix.index.union([ts])).ffill().get(ts, np.nan)
        feat["vix"] = float(v) if pd.notna(v) else np.nan
        v20 = vix.reindex(vix.index.union([ts])).ffill()
        try:
            feat["vix_chg20"] = float(v - v20.iloc[max(0, v20.index.get_loc(ts) - 20)])
        except Exception:
            feat["vix_chg20"] = np.nan
    if spy is not None and i >= 0:
        s = spy.reindex(spy.index.union([ts])).ffill()
        loc = s.index.get_loc(ts)
        hi = s.iloc[max(0, loc - 252):loc + 1].max()
        feat["spy_dd"] = float(s.get(ts, np.nan) / hi - 1.0) if hi else np.nan
    return sleeve, feat


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=21)
    ap.add_argument("--step", type=int, default=21, help="non-overlapping rebalance spacing")
    ap.add_argument("--min-train", type=int, default=20, help="periods before gating activates")
    ap.add_argument("--n-perm", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args()
    H, step = args.horizon, args.step

    rows = []  # (window, date, sleeve_ret, features...)
    for label, sid in WINDOWS:
        snap = SNAP_ROOT / sid
        if not snap.exists():
            continue
        print(f"loading {label} ({sid[:8]}) ...", flush=True)
        ctx = Ctx(sid)
        vix, spy = _vix_spy(snap)
        for i in range(252, len(ctx.dates) - H - 1, step):
            res = _sleeve_and_features(ctx, i, H, vix, spy)
            if res is None:
                continue
            sleeve, feat = res
            rows.append({"window": label, "date": ctx.dates[i], "sleeve": sleeve, **feat})

    df = pd.DataFrame(rows).dropna().reset_index(drop=True)
    feat_cols = [c for c in ("junk_quality_spread", "vix", "vix_chg20", "spy_dd") if c in df]
    print(f"\n{len(df)} rebalance periods, features: {feat_cols}")
    if len(df) < args.min_train + 10:
        print("insufficient periods for a walk-forward gate"); return 1

    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    y = (df["sleeve"] > 0).astype(int).to_numpy()
    X = df[feat_cols].to_numpy()
    gate = np.ones(len(df))  # default ON (ungated) until min_train reached
    for k in range(args.min_train, len(df)):
        Xtr, ytr = X[:k], y[:k]
        if len(np.unique(ytr)) < 2:
            continue
        sc = StandardScaler().fit(Xtr)
        lr = LogisticRegression(max_iter=500, C=1.0).fit(sc.transform(Xtr), ytr)
        gate[k] = float(lr.predict_proba(sc.transform(X[k:k + 1]))[0, 1])  # soft gate = P(up)

    sleeve = df["sleeve"].to_numpy()
    per_yr = 252.0 / H
    def ann(series):  # annualized mean return of a per-period series
        return float(np.mean(series) * per_yr * 100)
    def sharpe(series):
        s = np.std(series)
        return float(np.mean(series) / s * np.sqrt(per_yr)) if s > 0 else 0.0

    gated = sleeve * gate  # soft-gated (scale exposure by P(up))
    hard = sleeve * (gate > 0.5)  # hard on/off

    # Per-window (phase) comparison
    print(f"\n{'window':10s}{'n':>4}{'ungated%/yr':>13}{'soft-gated':>12}{'hard-gated':>12}")
    for label, _ in WINDOWS:
        m = df["window"] == label
        if m.sum() == 0:
            continue
        print(f"{label:10s}{int(m.sum()):>4}{ann(sleeve[m]):>+13.1f}{ann(gated[m.to_numpy()]):>+12.1f}{ann(hard[m.to_numpy()]):>+12.1f}")
    pos_un = sum(ann(sleeve[(df['window']==l).to_numpy()]) > 0 for l, _ in WINDOWS)
    pos_g = sum(ann(hard[(df['window']==l).to_numpy()]) > 0 for l, _ in WINDOWS)

    print(f"\nFULL  ungated: {ann(sleeve):+.1f}%/yr Sharpe {sharpe(sleeve):.2f} | "
          f"soft-gate: {ann(gated):+.1f}%/yr Sharpe {sharpe(gated):.2f} | "
          f"hard-gate: {ann(hard):+.1f}%/yr Sharpe {sharpe(hard):.2f}")
    print(f"phases positive: ungated {pos_un}/4 -> hard-gated {pos_g}/4")

    # Duty-cycle-matched permutation null: random gates with same % active as the hard gate.
    rng = np.random.default_rng(args.seed)
    active = (gate > 0.5)
    duty = active.mean()
    real_lift = ann(hard) - ann(sleeve)
    null_lifts = []
    for _ in range(args.n_perm):
        rg = rng.random(len(sleeve)) < duty
        null_lifts.append(ann(sleeve * rg) - ann(sleeve))
    p = float((np.array(null_lifts) >= real_lift).mean())
    print(f"\nGATE LIFT (hard) {real_lift:+.1f}%/yr vs ungated | duty {duty*100:.0f}% active | "
          f"duty-matched-null p={p:.3f}")
    print(f"DECISION (pre-registered): lift >= +2.0%/yr AND phases>=4/4 better AND null p<0.05 -> "
          f"{'PASS' if (real_lift>=2.0 and pos_g>=pos_un and p<0.05) else 'FAIL'}")

    out = Path("reports") / f"regime_gate_test_H{H}.json"
    out.write_text(json.dumps({
        "n_periods": len(df), "features": feat_cols,
        "ungated_ann": ann(sleeve), "soft_gated_ann": ann(gated), "hard_gated_ann": ann(hard),
        "lift_hard": real_lift, "duty": duty, "null_p": p,
        "phases_pos_ungated": pos_un, "phases_pos_gated": pos_g,
    }, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
