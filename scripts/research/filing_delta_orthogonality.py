"""Stage 1 orthogonality gate for the pre-registered Lazy-Prices study
(reports/_lazy_prices_hypothesis.json) — is filing_delta a momentum/value
clone, BEFORE any return is computed?

Per snapshot, on a 63-trading-day grid (high_52w_probe conventions):
  (a) per-date Spearman rho of filing_delta raw vs 12-1 momentum raw
      (src.factors.momentum.momentum_12_1: 252td return skipping last 21td,
      snapshot prices only),
  (b) per-date Spearman rho vs value raw (src.factors.value.value_factor =
      EDGAR PIT earnings yield, eps_ttm / price, off the snapshot's frozen
      fundamentals_pit.json),
  (c) top-K overlap |top-K filing_delta ∩ top-K momentum| / K.

Pooled rho = median of per-date rhos (the high_52w_probe "POOLED" convention;
mean reported alongside). Overlap gate = MEAN per the spec's "averaged".

Pre-registered gates (fail = stop, the signal is a clone):
  |rho_mom| < 0.30,  mean overlap < 30%,  |rho_value| < 0.40

The script reports PASS/FAIL but always exits 0.

    uv run python -m scripts.research.filing_delta_orthogonality \\
        --snapshot-ids acd1e7401c6484cf,a36c9bfd0c353b53,...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.right_tail_harness import _LOOKBACK, _spearman  # noqa: E402
from scripts.run_factor_backtest import _load_fundamentals_if_needed  # noqa: E402
from src.factors.filing_delta import (  # noqa: E402
    FilingDeltaLoader,
    filing_delta_factor,
    sidecar_path,
)
from src.factors.momentum import momentum_12_1  # noqa: E402
from src.factors.price_quality import drop_price_artifacts  # noqa: E402
from src.factors.value import value_factor  # noqa: E402
from src.storage.snapshot import load_snapshot  # noqa: E402

# Pre-registered Stage-1 gates (spec "orthogonality" field).
GATE_RHO_MOM = 0.30
GATE_OVERLAP = 0.30
GATE_RHO_VALUE = 0.40


def _setup(snap_id: str):
    """Snapshot prices (artifact-scrubbed) + EDGAR PIT loader + SPY calendar —
    clone of high_52w_probe._setup_lite."""
    snap = load_snapshot(snap_id)
    prices = snap.price_data
    end = max((df.index.max() for df in prices.values() if df is not None and not df.empty),
              default=None)
    prices, _ = drop_price_artifacts(prices, end, lookback_rows=10**9)
    universe = sorted(prices.keys())
    args = SimpleNamespace(factor="composite", snapshot_id=snap_id)
    fund_loader = _load_fundamentals_if_needed(args, universe)
    return prices, universe, fund_loader, snap.spy_df.index


def _raw_series(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=float)
    return frame.set_index("ticker")["raw"]


def _pair_rho(a: pd.Series, b: pd.Series, min_names: int) -> float | None:
    j = pd.concat([a, b], axis=1, join="inner").dropna()
    if len(j) < min_names:
        return None
    return _spearman(j.iloc[:, 0].to_numpy(), j.iloc[:, 1].to_numpy())


def _stats(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0, "median": None, "mean": None}
    return {"n": len(vals),
            "median": round(float(np.median(vals)), 4),
            "mean": round(float(np.mean(vals)), 4)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot-ids", required=True, help="comma-separated snapshot ids")
    ap.add_argument("--step", type=int, default=63,
                    help="trading-day grid step (default 63 = house cadence)")
    ap.add_argument("--top-k", type=int, default=24,
                    help="book size for the overlap gate (default 24)")
    ap.add_argument("--min-names", type=int, default=20,
                    help="min common names for a date to count (default 20)")
    ap.add_argument("--output", default="reports/filing_delta_orthogonality.json")
    args = ap.parse_args()

    snaps = [s.strip() for s in args.snapshot_ids.split(",") if s.strip()]
    K = args.top_k

    per_snap: dict[str, dict] = {}
    pooled = {"rho_mom": [], "rho_value": [], "overlap": []}
    for sid in snaps:
        sc = sidecar_path(sid)
        if not sc.exists():
            print(f"[{sid[:8]}] SKIP — no sidecar {sc}", file=sys.stderr)
            continue
        print(f"[{sid[:8]}] loading snapshot + sidecar...", flush=True)
        prices, universe, fund_loader, cal = _setup(sid)
        fdl = FilingDeltaLoader.from_json(sc)
        dates = [cal[i] for i in range(_LOOKBACK, len(cal), args.step)]
        print(f"[{sid[:8]}] scoring {len(dates)} grid dates "
              f"({len(universe)} names, {len(fdl.tickers)} with filings)...", flush=True)

        rhos_m, rhos_v, overlaps = [], [], []
        for d in dates:
            fd = filing_delta_factor(fdl, universe, d)
            if fd.empty:
                continue
            mom = momentum_12_1(prices, d)
            fd_raw = _raw_series(fd)
            mom_raw = _raw_series(mom)
            rho = _pair_rho(fd_raw, mom_raw, args.min_names)
            if rho is not None:
                rhos_m.append(rho)
            if not mom.empty:
                common = set(fd["ticker"]) & set(mom["ticker"])
                if len(common) >= max(args.min_names, K):
                    top_fd = set(fd[fd["ticker"].isin(common)]["ticker"].head(K))
                    top_m = set(mom[mom["ticker"].isin(common)]["ticker"].head(K))
                    overlaps.append(len(top_fd & top_m) / K)
            if fund_loader is not None:
                try:
                    val = value_factor(fund_loader, prices, universe, d)
                except Exception:
                    val = None
                if val is not None and not val.empty:
                    rho = _pair_rho(fd_raw, _raw_series(val), args.min_names)
                    if rho is not None:
                        rhos_v.append(rho)
        per_snap[sid] = {"rho_mom": _stats(rhos_m), "rho_value": _stats(rhos_v),
                         "overlap": _stats(overlaps)}
        pooled["rho_mom"] += rhos_m
        pooled["rho_value"] += rhos_v
        pooled["overlap"] += overlaps

    pooled_stats = {k: _stats(v) for k, v in pooled.items()}
    # Gate metrics: rho gates on the pooled MEDIAN (high_52w_probe POOLED
    # convention); overlap gates on the pooled MEAN (spec: "averaged").
    g_rho_m = pooled_stats["rho_mom"]["median"]
    g_rho_v = pooled_stats["rho_value"]["median"]
    g_ov = pooled_stats["overlap"]["mean"]
    gates = {
        "rho_mom": {"value": g_rho_m, "bar": f"|rho| < {GATE_RHO_MOM}",
                    "pass": g_rho_m is not None and abs(g_rho_m) < GATE_RHO_MOM},
        "overlap": {"value": g_ov, "bar": f"mean overlap < {GATE_OVERLAP:.0%}",
                    "pass": g_ov is not None and g_ov < GATE_OVERLAP},
        "rho_value": {"value": g_rho_v, "bar": f"|rho| < {GATE_RHO_VALUE}",
                      "pass": g_rho_v is not None and abs(g_rho_v) < GATE_RHO_VALUE},
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "study": "lazy_prices_filing_delta_stage1_orthogonality",
        "params": {"snapshot_ids": snaps, "step": args.step, "top_k": K,
                   "min_names": args.min_names},
        "value_measure": "src.factors.value.value_factor (EDGAR PIT earnings "
                         "yield, eps_ttm/price, frozen fundamentals_pit.json)",
        "per_snapshot": per_snap,
        "pooled": pooled_stats,
        "gates": gates,
    }, indent=2), encoding="utf-8")

    print("\n" + "=" * 78)
    print(f"FILING-DELTA STAGE-1 ORTHOGONALITY (step={args.step}td, K={K})")
    print("=" * 78)
    print(f"{'snapshot':10}{'rho_mom med':>12}{'rho_val med':>12}"
          f"{'overlap mean':>14}{'ndates':>8}")
    for sid, s in per_snap.items():
        print(f"{sid[:8]:10}"
              f"{(s['rho_mom']['median'] if s['rho_mom']['n'] else float('nan')):>12.3f}"
              f"{(s['rho_value']['median'] if s['rho_value']['n'] else float('nan')):>12.3f}"
              f"{(s['overlap']['mean'] if s['overlap']['n'] else float('nan')):>14.3f}"
              f"{s['rho_mom']['n']:>8}")
    print("-" * 78)
    print("PRE-REGISTERED GATES (fail = clone, stop the study):")
    for name, g in gates.items():
        v = "n/a" if g["value"] is None else f"{g['value']:+.3f}"
        print(f"  {name:10} {v:>8}   bar: {g['bar']:<22} "
              f"{'PASS' if g['pass'] else 'FAIL'}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
