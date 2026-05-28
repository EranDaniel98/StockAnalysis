"""Factor lab — rapid cross-sectional forward-IC screening with a permutation null.

The try-and-error engine for strategy discovery. Evaluates a battery of candidate
signals (price, EDGAR fundamentals, accruals, PEAD, and their interactions) by
forward-return rank-IC across regimes, with a permutation null so we don't mistake
noise for edge (the lesson from the Mirage null + the phase-luck capstone).

Every signal is oriented "higher = more bullish". Base signals are z-scored
cross-sectionally per date; interactions are products of those z-scores. IC is
Spearman vs the H-day forward return on non-overlapping windows (step == horizon)
so the per-date IC t-stat is honest.

    uv run python -m scripts.factor_lab --snapshot-ids ed270407fd89cf60,1c1c314850bb7368 \
        --horizons 21,63

Reads data <= as_of only. Accrual/fundamental sidecars are optional per snapshot.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

warnings.filterwarnings("ignore")

from src.factors.accruals_pit import AccrualsPITLoader
from src.factors.earnings_cache import load_earnings_histories
from src.factors.fundamentals_pit_loader import FundamentalsPITLoader
from src.factors.momentum import momentum_12_1
from src.factors.pead import pead_factor
from src.factors.quality import quality_factor
from src.factors.value import value_factor

SNAP_ROOT = Path("data/snapshots")
MIN_NAMES = 20


class Ctx:
    def __init__(self, snap_id: str):
        d = SNAP_ROOT / snap_id
        raw = pd.read_parquet(d / "prices.parquet")
        raw["date"] = pd.to_datetime(raw["date"])
        self.snap_id = snap_id
        self.prices = {t: g.set_index("date").sort_index() for t, g in raw.groupby("ticker")}
        self.panel = raw.pivot(index="date", columns="ticker", values="Close").sort_index()
        self.dates = self.panel.index
        self.fund = FundamentalsPITLoader.from_json(d / "fundamentals_pit.json")
        ap = d / "accruals_pit.json"
        self.accr = AccrualsPITLoader.from_json(ap) if ap.exists() else None
        rows = json.loads((d / "fundamentals_pit.json").read_text(encoding="utf-8"))
        self.sector_of = {r["ticker"]: r["sector"] for r in rows if r.get("sector")}
        self.universe = sorted(set(self.panel.columns))
        self.earnings = load_earnings_histories(self.universe, max_age_hours=10 ** 9)


def _as_of_dt(ts: pd.Timestamp) -> _dt.datetime:
    dt = ts.to_pydatetime()
    return dt if dt.tzinfo else dt.replace(tzinfo=_dt.timezone.utc)


def _frame_z(df: pd.DataFrame) -> pd.Series:
    """Extract a ticker->z_score Series from a factor frame."""
    if df is None or df.empty:
        return pd.Series(dtype=float)
    return df.set_index("ticker")["z_score"]


# --- base signals: ctx, i (panel int-index) -> Series(ticker -> raw, higher=bullish) ---

def _ret(panel: pd.DataFrame, i: int, lo: int, hi: int) -> pd.Series:
    return panel.iloc[i - lo] / panel.iloc[i - hi] - 1.0


def base_signals(ctx: Ctx, i: int) -> dict[str, pd.Series]:
    p, ts = ctx.panel, ctx.dates[i]
    out: dict[str, pd.Series] = {}
    # price (vectorized)
    if i >= 252:
        out["mom_12_1"] = _ret(p, i, 21, 252)
        out["mom_6_1"] = _ret(p, i, 21, 126)
    if i >= 21:
        out["rev_21"] = -_ret(p, i, 0, 21)
    if i >= 5:
        out["rev_5"] = -_ret(p, i, 0, 5)
    if i >= 60:
        out["lowvol_60"] = -p.iloc[i - 60:i].pct_change().std()
        # 52w-high proximity (anchoring): close / 252d-high
        out["hi52w"] = p.iloc[i] / p.iloc[max(0, i - 252):i + 1].max()
    # fundamentals (per-date, validated factors)
    try:
        out["quality"] = _frame_z(quality_factor(ctx.fund, ctx.universe, ts))
    except Exception:
        pass
    try:
        out["value"] = _frame_z(value_factor(ctx.fund, ctx.prices, ctx.universe, ts))
    except Exception:
        pass
    try:
        out["pead"] = _frame_z(pead_factor(ctx.earnings, ts, prices=ctx.prices))
    except Exception:
        pass
    # accruals + raw-fact-derived EDGAR signals (from the accruals sidecar)
    if ctx.accr is not None:
        aod = _as_of_dt(ts)
        acc, gp, ag, ng = {}, {}, {}, {}
        for t in ctx.accr.tickers:
            rec = ctx.accr.lookup(t, aod)
            if rec is None:
                continue
            acc[t] = -rec.accrual  # high accrual = low quality -> fade
            # gross profitability (Novy-Marx): gross_profit / total_assets
            f = ctx.fund.lookup(t, aod)
            if f and f.gross_margin is not None and f.revenue and rec.total_assets > 0:
                gp[t] = f.gross_margin * f.revenue / rec.total_assets
            hist = ctx.accr.history(t, aod)
            if len(hist) >= 5:
                ta0, ta4 = hist[-1].total_assets, hist[-5].total_assets
                if ta4 > 0:
                    ag[t] = -(ta0 / ta4 - 1.0)  # asset growth = negative predictor
                ni0, ni4 = hist[-1].net_income, hist[-5].net_income
                if ni4 and ni4 > 0:
                    ng[t] = ni0 / ni4 - 1.0  # YoY earnings momentum
        for k, d in (("accruals", acc), ("gross_prof", gp), ("asset_growth", ag), ("ni_growth", ng)):
            if d:
                out[k] = pd.Series(d)
    # fundamental-trajectory + cash legs (need filing history)
    aod = _as_of_dt(ts)
    dom, deg, fcta = {}, {}, {}
    for t in ctx.universe:
        h = ctx.fund.history(t, aod)
        if len(h) < 2:
            continue
        eg_t, eg_p = h[-1].earnings_growth_yoy, h[-2].earnings_growth_yoy
        if eg_t is not None and eg_p is not None:
            deg[t] = eg_t - eg_p
        if len(h) >= 5:
            om_t, om_p = h[-1].operating_margin, h[-5].operating_margin
            if om_t is not None and om_p is not None:
                dom[t] = (om_t - om_p) / (abs(om_p) + 0.05)
        fcfs = [s.free_cash_flow for s in h[-4:] if s.free_cash_flow is not None]
        rec = ctx.accr.lookup(t, aod) if ctx.accr is not None else None
        if len(fcfs) >= 2 and rec is not None and rec.total_assets > 0:
            fcta[t] = (sum(fcfs) * 4.0 / len(fcfs)) / rec.total_assets  # FCF-to-assets (no PIT mcap)
    for k, d in (("delta_opmargin", dom), ("delta_earn_growth", deg), ("fcf_to_assets", fcta)):
        if d:
            out[k] = pd.Series(d)
    return {k: v.dropna() for k, v in out.items() if v is not None and len(v.dropna()) >= MIN_NAMES}


# interactions: (name, legA, legB) — product of cross-sectional z-scores
INTERACTIONS = [
    ("mom_x_lowvol", "mom_12_1", "lowvol_60"),
    ("mom_x_quality", "mom_12_1", "quality"),
    ("qual_x_value", "quality", "value"),      # quality-at-a-reasonable-price
    ("accr_x_value", "accruals", "value"),
    ("rev_x_quality", "rev_5", "quality"),     # bounce the quality oversold
    ("mom_x_value", "mom_12_1", "value"),
    ("pead_x_quality", "pead", "quality"),
    ("hi52w_x_mom", "hi52w", "mom_12_1"),
]


def _z(s: pd.Series) -> pd.Series:
    sd = s.std(ddof=0)
    return (s - s.mean()) / sd if sd and not np.isnan(sd) else s * 0.0


def _sector_rank_norm(s: pd.Series, sector_of: dict) -> pd.Series:
    """Rank within sector -> [-0.5, +0.5]; global rank for sub-8 sectors.
    Winsorization-by-construction; immune to EDGAR heavy tails."""
    sec = pd.Series({t: sector_of.get(t, "Unknown") for t in s.index})
    out = pd.Series(np.nan, index=s.index, dtype=float)
    for _, grp in s.groupby(sec):
        if len(grp) >= 8:
            out.loc[grp.index] = (grp.rank(method="average") - 1) / (len(grp) - 1) - 0.5
    miss = out.index[out.isna()]
    if len(miss) > 1:
        out.loc[miss] = (s.loc[miss].rank(method="average") - 1) / (len(miss) - 1) - 0.5
    return out.fillna(0.0)


# QGF-6 (co-design): equal-weight sum of sector-rank-normalized legs, all higher=better
QGF6_LEGS = ["gross_prof", "asset_growth", "delta_opmargin", "delta_earn_growth", "pead", "fcf_to_assets"]
# Lean composite: drop the legs that fail the per-leg gate (delta_earn_growth not
# significant, fcf_to_assets sign-flips) per the pre-registered trim rule.
QGF_LEAN_LEGS = ["gross_prof", "asset_growth", "delta_opmargin", "pead"]
GP_AG_LEGS = ["gross_prof", "asset_growth"]  # the two 100%-consistent standouts


# additive combos (NOT products — interactions were dead) of sign-stable legs
COMBOS = [
    ("combo_qp", ["quality", "pead"]),
    ("combo_qpg", ["quality", "pead", "gross_prof"]),
    ("combo_qpm", ["quality", "pead", "mom_12_1"]),
    ("combo_qp_ag", ["quality", "pead", "asset_growth"]),
]


def all_signals(ctx: Ctx, i: int) -> dict[str, pd.Series]:
    base = base_signals(ctx, i)
    zb = {k: _z(v) for k, v in base.items()}
    out = dict(base)
    for name, a, b in INTERACTIONS:
        if a in zb and b in zb:
            common = zb[a].index.intersection(zb[b].index)
            if len(common) >= MIN_NAMES:
                out[name] = (zb[a].loc[common] * zb[b].loc[common])
    for name, legs in COMBOS:
        if all(leg in zb for leg in legs):
            common = zb[legs[0]].index
            for leg in legs[1:]:
                common = common.intersection(zb[leg].index)
            if len(common) >= MIN_NAMES:
                out[name] = sum(zb[leg].loc[common] for leg in legs)
    # QGF-6 composite: sector-rank-normalized equal-weight sum (>=4 of 6 legs present)
    present = [leg for leg in QGF6_LEGS if leg in base]
    if len(present) >= 5:
        norm = pd.DataFrame({leg: _sector_rank_norm(base[leg], ctx.sector_of) for leg in present})
        n_present = norm.notna().sum(axis=1)
        comp = norm.fillna(0.0).sum(axis=1)[n_present >= 4]
        if len(comp) >= MIN_NAMES:
            out["QGF6"] = comp
        # sector-rank baseline (quality+pead) for the lift comparison
        if "quality" in base and "pead" in base:
            qp = pd.DataFrame({"q": _sector_rank_norm(base["quality"], ctx.sector_of),
                               "p": _sector_rank_norm(base["pead"], ctx.sector_of)})
            out["QP2_baseline"] = qp.fillna(0.0).sum(axis=1)
    for cname, legs in (("QGF_lean", QGF_LEAN_LEGS), ("GP_AG", GP_AG_LEGS)):
        prs = [leg for leg in legs if leg in base]
        if len(prs) == len(legs):
            nm = pd.DataFrame({leg: _sector_rank_norm(base[leg], ctx.sector_of) for leg in prs})
            comp = nm.fillna(0.0).sum(axis=1)[nm.notna().sum(axis=1) >= max(2, len(legs) - 1)]
            if len(comp) >= MIN_NAMES:
                out[cname] = comp
    return out


def _ic(sig: pd.Series, fwd: pd.Series) -> float | None:
    df = pd.concat([sig, fwd], axis=1).dropna()
    if len(df) < MIN_NAMES:
        return None
    rho, _ = spearmanr(df.iloc[:, 0], df.iloc[:, 1])
    return None if np.isnan(rho) else float(rho)


def run_snapshot(ctx: Ctx, horizon: int, step: int, n_perm: int, rng) -> dict[str, dict]:
    dates = ctx.dates
    idxs = list(range(252, len(dates) - horizon - 1, step))
    per_sig_ic: dict[str, list[float]] = {}
    per_sig_null: dict[str, list[list[float]]] = {}
    for i in idxs:
        sigs = all_signals(ctx, i)
        fwd_all = ctx.panel.iloc[i + horizon] / ctx.panel.iloc[i] - 1.0
        for name, s in sigs.items():
            fwd = fwd_all.reindex(s.index)
            ic = _ic(s, fwd)
            if ic is None:
                continue
            per_sig_ic.setdefault(name, []).append(ic)
            # permutation: shuffle signal across names
            vals = s.to_numpy()
            nulls = []
            for _ in range(n_perm):
                r = _ic(pd.Series(rng.permutation(vals), index=s.index), fwd)
                if r is not None:
                    nulls.append(r)
            per_sig_null.setdefault(name, []).append(nulls)

    res: dict[str, dict] = {}
    for name, ics in per_sig_ic.items():
        a = np.array(ics)
        n = len(a)
        mean = float(a.mean())
        se = float(a.std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
        # pooled permutation null: mean across dates per perm-index
        nulls = per_sig_null[name]
        k = min((len(x) for x in nulls), default=0)
        if k > 0:
            mat = np.array([x[:k] for x in nulls])
            null_means = mat.mean(axis=0)
            p = float((np.abs(null_means) >= abs(mean)).mean())
        else:
            p = float("nan")
        res[name] = {
            "n_dates": n, "mean_ic": mean,
            "t": (mean / se) if se and not np.isnan(se) else float("nan"),
            "pct_pos": float((a > 0).mean() * 100),
            "perm_p": p,
        }
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-ids", required=True, help="comma-separated")
    ap.add_argument("--horizons", default="21,63")
    ap.add_argument("--step", type=int, default=21)
    ap.add_argument("--n-perm", type=int, default=150)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    snaps = args.snapshot_ids.split(",")
    horizons = [int(h) for h in args.horizons.split(",")]
    rng = np.random.default_rng(args.seed)

    all_res: dict = {}  # (snap,H) -> {sig: stats}
    for sid in snaps:
        print(f"loading {sid} ...", flush=True)
        ctx = Ctx(sid)
        for H in horizons:
            print(f"  scoring H={H} ...", flush=True)
            all_res[f"{sid[:8]}|H{H}"] = run_snapshot(ctx, H, args.step, args.n_perm, rng)

    # pool per signal across (snap,H) by simple mean of mean_ic, and count significant cells
    sigs = sorted({s for cell in all_res.values() for s in cell})
    rows = []
    for sig in sigs:
        cells = [(k, all_res[k][sig]) for k in all_res if sig in all_res[k]]
        means = [c["mean_ic"] for _, c in cells]
        n_sig = sum(1 for _, c in cells if c["perm_p"] < 0.05 and abs(c["mean_ic"]) > 0.01)
        n_pos = sum(1 for m in means if m > 0)
        rows.append({
            "signal": sig, "n_cells": len(cells),
            "avg_ic": float(np.mean(means)), "min_ic": float(np.min(means)), "max_ic": float(np.max(means)),
            "n_signif": n_sig, "sign_consistency": max(n_pos, len(means) - n_pos) / len(means),
        })
    rows.sort(key=lambda r: -abs(r["avg_ic"]))

    out = Path("reports") / "factor_lab_leaderboard.json"
    out.write_text(json.dumps({"cells": all_res, "leaderboard": rows}, indent=2), encoding="utf-8")

    print(f"\n=== IC LEADERBOARD ({len(snaps)} snapshots x {len(horizons)} horizons = {len(all_res)} cells) ===")
    print(f"{'signal':16s}{'avg_ic':>9}{'min':>8}{'max':>8}{'signif/cells':>14}{'sign_cons':>11}")
    for r in rows:
        print(f"{r['signal']:16s}{r['avg_ic']:>+9.4f}{r['min_ic']:>+8.4f}{r['max_ic']:>+8.4f}"
              f"{str(r['n_signif'])+'/'+str(r['n_cells']):>14}{r['sign_consistency']*100:>10.0f}%")
    print(f"\n(signif = perm_p<0.05 AND |IC|>0.01; sign_cons = % cells agreeing on sign)")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
