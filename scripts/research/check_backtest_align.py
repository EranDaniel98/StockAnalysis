"""Compare post-align backtest output to saved d03 ablation reference.

Verifies the default-flip in scripts/run_factor_backtest.py produces
results matching the saved ablation that was run with EXPLICIT flags
of the same values. Anything beyond noise = a flag I missed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]

PAIRS = [
    ("data/backtests/post_align/2022_2024.json",
     "data/backtests/post_24of24/ablation_2022_2024_top3pct.json"),
    ("data/backtests/post_align/2024_2026.json",
     "data/backtests/post_24of24/ablation_2024_2026_top3pct.json"),
]

TOL_PCT = 0.1   # 0.1pp absolute tolerance on alpha, return, DD
TOL_SHARPE = 0.05  # 0.05 absolute tolerance on Sharpe (matches yfin noise envelope edge)


def cmp_metric(name: str, new: float, ref: float, tol: float) -> tuple[bool, str]:
    diff = abs(new - ref)
    ok = diff <= tol
    flag = "OK" if ok else "**MISMATCH**"
    return ok, f"  {name:<22} new={new:>+8.3f}  ref={ref:>+8.3f}  diff={diff:>+6.3f}  {flag}"


def check_pair(new_path: Path, ref_path: Path) -> bool:
    if not new_path.exists():
        print(f"missing new: {new_path}")
        return False
    if not ref_path.exists():
        print(f"missing ref: {ref_path}")
        return False
    new = json.loads(new_path.read_text())
    ref = json.loads(ref_path.read_text())
    print(f"\n--- {new_path.name}  vs  {ref_path.name} ---")
    print(f"  snapshot: new={new['snapshot_id']}  ref={ref['snapshot_id']}")
    if new["snapshot_id"] != ref["snapshot_id"]:
        print("  **MISMATCH** snapshot id")
        return False

    all_ok = True
    checks = [
        ("total_return_pct", new["metrics"]["total_return_pct"],
         ref["metrics"]["total_return_pct"], TOL_PCT),
        ("ann_sharpe", new["metrics"]["ann_sharpe"],
         ref["metrics"]["ann_sharpe"], TOL_SHARPE),
        ("max_drawdown_pct", new["metrics"]["max_drawdown_pct"],
         ref["metrics"]["max_drawdown_pct"], TOL_PCT),
        ("alpha_vs_spy_pct", new["alpha_vs_spy_pct"],
         ref["alpha_vs_spy_pct"], TOL_PCT),
        ("wf_mean_sharpe", new["walk_forward"]["mean_sharpe"],
         ref["walk_forward"]["mean_sharpe"], TOL_SHARPE),
        ("wf_min_sharpe", new["walk_forward"]["min_sharpe"],
         ref["walk_forward"]["min_sharpe"], TOL_SHARPE),
    ]
    for name, n, r, tol in checks:
        ok, msg = cmp_metric(name, float(n), float(r), tol)
        print(msg)
        all_ok = all_ok and ok

    n_new = new["metrics"]["n_trades"]
    n_ref = ref["metrics"]["n_trades"]
    trades_ok = abs(n_new - n_ref) <= 5  # within 5 trade tolerance for path noise
    flag = "OK" if trades_ok else "**MISMATCH**"
    print(f"  {'n_trades':<22} new={n_new:>+8.0f}  ref={n_ref:>+8.0f}  "
          f"diff={n_new-n_ref:>+6.0f}  {flag}")
    all_ok = all_ok and trades_ok

    # Parameters dump (new is now self-describing)
    if "parameters" in new:
        print(f"  new parameters: {new['parameters']}")
    return all_ok


def main() -> int:
    all_ok = True
    for new_rel, ref_rel in PAIRS:
        ok = check_pair(REPO / new_rel, REPO / ref_rel)
        all_ok = all_ok and ok
    print()
    if all_ok:
        print("[align] PASS — backtest defaults match d03 ablation reference.")
        print("        Safe to ship the default change.")
        return 0
    print("[align] FAIL — at least one metric drifted beyond tolerance.")
    print("        DO NOT ship the default change until investigated.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
