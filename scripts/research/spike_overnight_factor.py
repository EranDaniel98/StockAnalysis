"""IC spike: does trailing OVERNIGHT return (close->open) predict forward returns,
and is it orthogonal to price momentum? Measure-then-kill gate for adding an
overnight-return factor to the m/q/v composite.

Overnight anomaly (Lou-Polk-Skouras 2019): overnight returns have momentum-like
persistence driven by a different clientele, and they're ~orthogonal to price
momentum (which blends overnight + intraday). A factor = rank by trailing mean
overnight return. Computed from the snapshot's adjusted OHLCV: open_t/close_{t-1}-1.

Usage: uv run python scripts/research/spike_overnight_factor.py [SNAPSHOT_ID]
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.storage.snapshot import load_snapshot  # noqa: E402

SNAP = sys.argv[1] if len(sys.argv) > 1 else "ed270407fd89cf60"
LOOKBACKS = [20, 60]          # trailing trading days for the overnight factor
HORIZONS = [5, 21, 63]        # forward total-return horizons (days)
N_BOOT, MIN_NAMES = 2000, 30
np.random.seed(42)


def main():
    snap = load_snapshot(SNAP)
    closes, overnight = {}, {}
    for t, df in snap.price_data.items():
        if df is None or df.empty or "Open" not in df.columns or "Close" not in df.columns:
            continue
        d = df.sort_index()
        c, o = d["Close"].astype(float), d["Open"].astype(float)
        closes[t] = c
        overnight[t] = o / c.shift(1) - 1.0

    trading = pd.DatetimeIndex(sorted(set().union(*[set(c.index) for c in closes.values()])))
    # monthly as_of = last trading day on/before each month-end
    asofs = []
    for m in pd.date_range(trading.min(), trading.max(), freq="ME"):
        pos = trading.searchsorted(m, side="right") - 1
        if pos >= 0:
            asofs.append(trading[pos])
    asofs = sorted(set(asofs))

    def pos_at(c, a):
        p = c.index.searchsorted(a, side="right") - 1
        return p if p >= 0 else None

    def factor(t, a, lb):
        on = overnight[t]
        p = pos_at(on, a)
        if p is None or p - lb + 1 < 0:
            return None
        win = on.iloc[p - lb + 1: p + 1].dropna()
        return float(win.mean()) if len(win) >= lb * 0.7 else None

    def fwd(t, a, h):
        c = closes[t]
        p = pos_at(c, a)
        if p is None or p + h >= len(c):
            return None
        return float(c.iloc[p + h] / c.iloc[p] - 1.0)

    def mom(t, a):  # 12-1 momentum, for the orthogonality check
        c = closes[t]
        p = pos_at(c, a)
        if p is None or p - 252 < 0:
            return None
        return float(c.iloc[p - 21] / c.iloc[p - 252] - 1.0)

    def ic_block(lb, h):
        ics = []
        for a in asofs:
            pairs = [(factor(t, a, lb), fwd(t, a, h)) for t in closes]
            pairs = [(f, r) for f, r in pairs if f is not None and r is not None]
            if len(pairs) >= MIN_NAMES:
                f = np.array([x[0] for x in pairs])
                r = np.array([x[1] for x in pairs])
                ic = stats.spearmanr(f, r).statistic
                if np.isfinite(ic):
                    ics.append(ic)
        ics = np.array(ics)
        if len(ics) < 3:
            return {"n_cohorts": int(len(ics)), "ic_mean": None}
        boot = [np.mean(np.random.choice(ics, len(ics), replace=True)) for _ in range(N_BOOT)]
        lo, hi = np.percentile(boot, [2.5, 97.5])
        tstat = ics.mean() / (ics.std(ddof=1) / np.sqrt(len(ics))) if ics.std() > 0 else 0.0
        return {"n_cohorts": int(len(ics)), "ic_mean": round(float(ics.mean()), 4),
                "t": round(float(tstat), 2), "ci95": [round(float(lo), 4), round(float(hi), 4)],
                "sig": bool(lo > 0 or hi < 0)}

    # orthogonality: mean cross-sectional rank-corr(overnight_60, momentum_12_1)
    corrs = []
    for a in asofs:
        pairs = [(factor(t, a, 60), mom(t, a)) for t in closes]
        pairs = [(f, m) for f, m in pairs if f is not None and m is not None]
        if len(pairs) >= MIN_NAMES:
            f = np.array([x[0] for x in pairs])
            m = np.array([x[1] for x in pairs])
            c = stats.spearmanr(f, m).statistic
            if np.isfinite(c):
                corrs.append(c)
    mom_corr = round(float(np.mean(corrs)), 4) if corrs else None

    report = {"spike": "overnight_return_factor", "snapshot": SNAP,
              "n_tickers": len(closes), "n_asofs": len(asofs),
              "rank_ic": {f"lb{lb}_h{h}": ic_block(lb, h) for lb in LOOKBACKS for h in HORIZONS},
              "mean_xs_corr_with_momentum_12_1": mom_corr}
    (ROOT / "reports" / "overnight_factor_ic.json").write_text(json.dumps(report, indent=2))

    print(f"overnight-return factor IC | snap={SNAP} | {len(closes)} names, {len(asofs)} monthly as-ofs")
    print(f"{'lb/horizon':<14}{'IC':>9}{'t':>7}{'CI95':>22}{'sig':>6}")
    for k, v in report["rank_ic"].items():
        if v.get("ic_mean") is None:
            print(f"  {k:<12}{'n/a':>9}")
        else:
            print(f"  {k:<12}{v['ic_mean']:>+9.4f}{v['t']:>+7.2f}{str(v['ci95']):>22}"
                  f"{'  *' if v['sig'] else '':>6}")
    print(f"\northogonality: mean cross-sectional corr(overnight_60, momentum_12_1) = {mom_corr}")
    print("  (near 0 = orthogonal/additive; near 1 = redundant with momentum)")
    print(f"wrote {ROOT / 'reports' / 'overnight_factor_ic.json'}")


if __name__ == "__main__":
    main()
