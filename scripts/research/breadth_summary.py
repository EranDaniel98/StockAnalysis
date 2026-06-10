# /// script
# dependencies = ["numpy"]
# ///
"""Roll up per-window phase-envelope reports into one breadth verdict.

The 3-window validation (project_xwindow_validation) left the edge "positive
CAPM-a in all regimes but fold-fragile everywhere" — unresolvable with one
window per regime. This aggregates the rolling-window sweep (2018-2026,
12-month step, production config) into the distribution that actually answers
"is the edge real or a coin-flip": fraction of windows with positive median
CAPM-a, the median-of-medians, and whether walk-forward improves in aggregate.

Pass windows as 'label=snapshot_id' (reads reports/phase_envelope_<id>.json):

    uv run python -m scripts.research.breadth_summary \\
        "2018-20=acd1e7401c6484cf" "2019-21=<id>" ...
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(snap: str) -> dict | None:
    p = ROOT / "reports" / f"phase_envelope_{snap}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: breadth_summary.py 'label=snapshot_id' ...")
        return 2

    rows = []
    for arg in argv:
        label, _, snap = arg.partition("=")
        d = _load(snap)
        if d is None:
            print(f"  WARN missing report for {label} ({snap})")
            continue
        c = d["envelope"]["capm_alpha"]
        rows.append({
            "label": label, "snap": snap,
            "med": c["median"], "mean": c["mean"], "min": c["min"], "max": c["max"],
            "pos": c["pct_phases_positive"],
            "wf": d["envelope"]["wf_pass_rate_pct"],
            "wfa": d["envelope"].get("wf_capm_pass_rate_pct"),
            "sharpe": d["envelope"]["sharpe"]["median"],
            "excess": d["envelope"]["excess_return"]["median"],
            "robust": "ROBUST" in d["verdict"],
            "robust_bn": "ROBUST" in d.get("verdict_beta_neutral", ""),
        })

    if not rows:
        print("no reports found")
        return 1

    print(f"\n{'window':10}{'CAPMa med':>10}{'mean':>7}{'[min..max]':>14}"
          f"{'%pos':>6}{'WF%':>5}{'WFa%':>6}{'Shrp':>6}{'excess':>8}  verdict (path | beta-neutral)")
    for r in rows:
        wfa = f"{r['wfa']:>6.0f}" if r["wfa"] is not None else f"{'—':>6}"
        print(f"{r['label']:10}{r['med']:>+10.1f}{r['mean']:>+7.1f}"
              f"{('['+format(r['min'],'+.0f')+'..'+format(r['max'],'+.0f')+']'):>14}"
              f"{r['pos']:>5.0f}%{r['wf']:>5.0f}{wfa}{r['sharpe']:>6.2f}{r['excess']:>+8.1f}"
              f"  {'ROBUST' if r['robust'] else 'fragile'} | "
              f"{'ROBUST' if r['robust_bn'] else 'fragile'}")

    meds = [r["med"] for r in rows]
    n = len(rows)
    n_pos = sum(m > 0 for m in meds)
    n_robust = sum(r["robust"] for r in rows)
    print(f"\n=== BREADTH ({n} windows) ===")
    print(f"  windows with positive median CAPM-a : {n_pos}/{n} ({100*n_pos/n:.0f}%)")
    print(f"  median-of-window-medians            : {statistics.median(meds):+.1f}%")
    print(f"  mean-of-window-medians              : {statistics.mean(meds):+.1f}%  "
          f"(spread {min(meds):+.0f}..{max(meds):+.0f})")
    print(f"  mean WF-pass rate across windows    : {statistics.mean(r['wf'] for r in rows):.0f}%")
    wfas = [r["wfa"] for r in rows if r["wfa"] is not None]
    if wfas:
        print(f"  mean BETA-NEUTRAL WF-pass rate      : {statistics.mean(wfas):.0f}%")
    print(f"  windows ROBUST (WF>=60 & >=70% pos) : {n_robust}/{n}")
    n_robust_bn = sum(r["robust_bn"] for r in rows)
    print(f"  windows ROBUST under beta-neutral WF: {n_robust_bn}/{n}")
    print(f"  mean phases-positive across windows  : {statistics.mean(r['pos'] for r in rows):.0f}%")
    print("\nCAVEAT: rolling 2yr windows on a 12-month step OVERLAP (adjacent share 1yr) "
          "-> not independent; effective N < window count. Polygon 10yr horizon caps the "
          "range at ~2017-2026. Production config (mqv+PEAD+daily-regime).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
