"""Phase-envelope harness — report a backtest config's α/Sharpe ACROSS rebalance
phases, not a single (luck-prone) point estimate.

A 2yr / 63-day backtest has only ~8 rebalances, so WHERE the grid lands dominates
the result: the composite's headline "+9.26%" was a 2-of-9-phase outlier (median
~−19%); see memory project_phase_luck_capstone. This sweeps --rebal-offset across
the rebalance cycle and reports mean ± spread, % of phases positive, and WF-pass
rate — the honest way to judge any config. Use it before trusting ANY result.

Usage:
  uv run python scripts/phase_envelope.py --snapshot-id ed270407fd89cf60 \\
      --base-args "--factor composite --composite-factors mqv --asymmetric-trend"
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_ARGS = ("--factor composite --composite-factors mqv --top-decile 0.03 "
                "--cost-bps 5.0 --asymmetric-trend --entry-sma 75 --no-include-pead "
                "--no-sector-neutral-quality --hysteresis-bonus 0.75 --momentum-flavor raw")


def _run_one(snap: str, rebal_days: int, offset: int, base_args: list[str]) -> dict:
    out = ROOT / "reports" / f".phase_tmp_{offset}.json"
    cmd = [sys.executable, "-m", "scripts.run_factor_backtest",
           "--snapshot-id", snap, "--rebalance-days", str(rebal_days),
           "--rebal-offset", str(offset), "--output", str(out)] + base_args
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"backtest failed at offset {offset}:\n{proc.stderr[-1500:]}")
    r = json.loads(out.read_text())
    out.unlink(missing_ok=True)
    return {"offset": offset, "alpha": r["alpha_vs_spy_pct"],
            "sharpe": r["metrics"]["ann_sharpe"], "total": r["metrics"]["total_return_pct"],
            "maxdd": r["metrics"]["max_drawdown_pct"], "wf_pass": bool(r["walk_forward"]["passed"])}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot-id", required=True)
    ap.add_argument("--rebalance-days", type=int, default=63)
    ap.add_argument("--step", type=int, default=7, help="phase step in trading days")
    ap.add_argument("--base-args", default=DEFAULT_ARGS,
                    help="backtest args to envelope (omit --rebal-offset/--output/--rebalance-days)")
    args = ap.parse_args()

    base = args.base_args.split()
    offsets = list(range(0, args.rebalance_days, args.step))
    print(f"phase envelope: {len(offsets)} phases (step {args.step}d) over a "
          f"{args.rebalance_days}d cycle | snap={args.snapshot_id}")
    rows = [_run_one(args.snapshot_id, args.rebalance_days, o, base) for o in offsets]

    alphas = [r["alpha"] for r in rows]
    sharpes = [r["sharpe"] for r in rows]
    n = len(rows)
    pct_pos = 100 * sum(a > 0 for a in alphas) / n
    wf_rate = 100 * sum(r["wf_pass"] for r in rows) / n
    env = {
        "alpha": {"mean": round(statistics.mean(alphas), 2),
                  "median": round(statistics.median(alphas), 2),
                  "std": round(statistics.pstdev(alphas), 2),
                  "min": round(min(alphas), 2), "max": round(max(alphas), 2),
                  "pct_phases_positive": round(pct_pos, 0)},
        "sharpe": {"mean": round(statistics.mean(sharpes), 2),
                   "median": round(statistics.median(sharpes), 2),
                   "min": round(min(sharpes), 2), "max": round(max(sharpes), 2)},
        "wf_pass_rate_pct": round(wf_rate, 0),
    }
    # robustness verdict: an edge should be mostly-positive with a spread small
    # relative to the mean. Phase-luck = wide spread, mean near/below zero.
    a = env["alpha"]
    robust = a["median"] > 0 and pct_pos >= 70 and a["std"] < abs(a["mean"]) * 1.5 + 5
    verdict = ("ROBUST across phases" if robust
               else "PHASE-LUCK / FRAGILE -- do not trust a single offset")

    report = {"snapshot": args.snapshot_id, "base_args": args.base_args,
              "n_phases": n, "per_phase": rows, "envelope": env, "verdict": verdict}
    out = ROOT / "reports" / f"phase_envelope_{args.snapshot_id}.json"
    out.write_text(json.dumps(report, indent=2))

    print(f"\n{'offset':>7}{'alpha%':>10}{'sharpe':>8}{'maxDD%':>9}{'WF':>5}")
    for r in rows:
        print(f"{r['offset']:>7}{r['alpha']:>+10.2f}{r['sharpe']:>8.2f}{r['maxdd']:>9.2f}"
              f"{'  ok' if r['wf_pass'] else '  --':>5}")
    print(f"\nALPHA envelope: mean {a['mean']:+.1f}%  median {a['median']:+.1f}%  "
          f"std {a['std']:.1f}  [{a['min']:+.1f} .. {a['max']:+.1f}]")
    print(f"  {pct_pos:.0f}% of phases positive | WF-pass {wf_rate:.0f}% | "
          f"Sharpe median {env['sharpe']['median']:.2f}")
    print(f"\nVERDICT: {verdict}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
