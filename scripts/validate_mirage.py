"""Validate the Mirage factor — the interaction-vs-additive test.

The co-design's central claim is that ``Mirage = -Z(accrual) * |Z_PEAD| * Decay``
captures something a LINEAR ``-Z(accrual) + |Z_PEAD|`` model cannot. This harness
tests exactly that, cheaply, via forward-return rank-IC on a frozen snapshot —
before any portfolio integration. Three gates:

  #1a  product IC  >  accrual-alone IC        (the PEAD gating adds something)
  #2   product IC  >  additive-baseline IC    (THE interaction test — decisive)
  #3   product IC  >  95th pct of a permutation null (accrual ranks shuffled)

All scores are built from the SAME eligible cross-section (mirage_components),
so the only difference is product vs sum. Non-overlapping windows (step==horizon)
keep the per-date IC t-stat honest.

    uv run python -m scripts.validate_mirage --snapshot-id <id> [--horizon 21]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from src.factors.accruals_pit import AccrualsPITLoader
from src.factors.earnings_cache import load_earnings_histories
from src.factors.mirage import mirage_components

SNAP_ROOT = Path("data/snapshots")
MIN_NAMES = 8  # skip a rebalance with too few eligible names to rank


def _sector_map(snap_dir: Path) -> dict[str, str]:
    rows = json.loads((snap_dir / "fundamentals_pit.json").read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for r in rows:  # last-write per ticker is fine; sector rarely changes
        if r.get("sector"):
            out[r["ticker"]] = r["sector"]
    return out


def _ic(score: pd.Series, fwd: pd.Series) -> float | None:
    df = pd.concat([score, fwd], axis=1).dropna()
    if len(df) < MIN_NAMES:
        return None
    rho, _ = spearmanr(df.iloc[:, 0], df.iloc[:, 1])
    return None if np.isnan(rho) else float(rho)


def _summary(ics: list[float]) -> dict:
    a = np.array(ics, dtype=float)
    n = len(a)
    mean = float(a.mean()) if n else float("nan")
    se = float(a.std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
    return {
        "n_dates": n,
        "mean_ic": mean,
        "t_stat": (mean / se) if se and not np.isnan(se) else float("nan"),
        "pct_positive": float((a > 0).mean() * 100) if n else float("nan"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", required=True)
    ap.add_argument("--horizon", type=int, default=21, help="forward-return holding days")
    ap.add_argument("--step", type=int, default=None, help="rebalance spacing (default = horizon, non-overlapping)")
    ap.add_argument("--decay-days", type=int, default=45)
    ap.add_argument("--n-perm", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    step = args.step or args.horizon
    H = args.horizon

    snap_dir = SNAP_ROOT / args.snapshot_id
    raw = pd.read_parquet(snap_dir / "prices.parquet")
    raw["date"] = pd.to_datetime(raw["date"])
    prices = {t: g.set_index("date").sort_index() for t, g in raw.groupby("ticker")}
    panel = raw.pivot(index="date", columns="ticker", values="Close").sort_index()

    accruals = AccrualsPITLoader.from_json(snap_dir / "accruals_pit.json")
    sector_of = _sector_map(snap_dir)
    universe = sorted(set(accruals.tickers) & set(prices))
    # Historical snapshot — use the on-disk earnings cache as-is (no live refetch).
    earnings = load_earnings_histories(universe, max_age_hours=10 ** 9)

    dates = panel.index
    start_i, end_i = 120, len(dates) - H - 1
    rebal_idx = list(range(start_i, end_i, step))

    rng = np.random.default_rng(args.seed)
    ic_prod, ic_add, ic_acc = [], [], []
    null_means: list[float] = []  # per-perm mean product-IC across dates
    perm_per_date: list[list[float]] = []  # for pooling permutation across dates
    avg_names = []

    for i in rebal_idx:
        d = dates[i]
        comp = mirage_components(accruals, earnings, prices, d, sector_of=sector_of, decay_days=args.decay_days)
        if len(comp) < MIN_NAMES:
            continue
        comp = comp.set_index("ticker")
        za, zp, dec = comp["z_accrual"], comp["z_pead_abs"], comp["decay"]
        product = (-za) * zp * dec
        additive = (-za) * dec + zp * dec
        accrual_only = (-za) * dec

        fwd = panel.iloc[i + H][comp.index] / panel.iloc[i][comp.index] - 1.0
        ip, ia, ic = _ic(product, fwd), _ic(additive, fwd), _ic(accrual_only, fwd)
        if ip is None:
            continue
        ic_prod.append(ip)
        if ia is not None:
            ic_add.append(ia)
        if ic is not None:
            ic_acc.append(ic)
        avg_names.append(len(comp))

        # permutation null: shuffle accrual ranks across names, recompute product IC
        date_null = []
        za_arr = za.to_numpy()
        for _ in range(args.n_perm):
            perm = (-rng.permutation(za_arr)) * zp.to_numpy() * dec.to_numpy()
            r = _ic(pd.Series(perm, index=comp.index), fwd)
            if r is not None:
                date_null.append(r)
        perm_per_date.append(date_null)

    # pool permutation: average across dates per perm-index -> null dist of mean-IC
    if perm_per_date:
        k = min(len(x) for x in perm_per_date)
        mat = np.array([x[:k] for x in perm_per_date])  # (n_dates, k)
        null_means = mat.mean(axis=0).tolist()

    prod, add, acc = _summary(ic_prod), _summary(ic_add), _summary(ic_acc)
    null_p95 = float(np.percentile(null_means, 95)) if null_means else float("nan")
    perm_p = (float((np.array(null_means) >= prod["mean_ic"]).mean()) if null_means else float("nan"))

    result = {
        "snapshot": args.snapshot_id,
        "horizon": H, "step": step, "decay_days": args.decay_days,
        "n_rebalances": len(ic_prod),
        "avg_eligible_names": float(np.mean(avg_names)) if avg_names else 0,
        "product": prod, "additive": add, "accrual_only": acc,
        "permutation": {"n_perm": args.n_perm, "null_mean_ic_p95": null_p95, "p_value": perm_p},
        "gates": {
            "g1a_beats_accrual_alone": prod["mean_ic"] > acc["mean_ic"],
            "g2_beats_additive": prod["mean_ic"] > add["mean_ic"],
            "g3_beats_permutation_null": (not np.isnan(perm_p)) and perm_p < 0.05,
        },
    }
    out = Path("reports") / f"mirage_validation_{args.snapshot_id}.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"\n=== Mirage validation — snapshot {args.snapshot_id} (H={H}d, {len(ic_prod)} rebalances, "
          f"avg {result['avg_eligible_names']:.0f} names) ===")
    for name, s in (("PRODUCT (Mirage)", prod), ("additive baseline", add), ("accrual-alone", acc)):
        print(f"  {name:18s} mean-IC {s['mean_ic']:+.4f}  t={s['t_stat']:+.2f}  %+={s['pct_positive']:.0f}")
    print(f"  permutation null p95 mean-IC {null_p95:+.4f}  -> product p-value {perm_p:.3f}")
    g = result["gates"]
    print(f"\n  GATE 1a (beats accrual-alone): {'PASS' if g['g1a_beats_accrual_alone'] else 'FAIL'}")
    print(f"  GATE 2  (beats ADDITIVE)     : {'PASS' if g['g2_beats_additive'] else 'FAIL'}  <- the interaction test")
    print(f"  GATE 3  (beats perm null)    : {'PASS' if g['g3_beats_permutation_null'] else 'FAIL'}")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
