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
import os
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_ARGS = ("--factor composite --composite-factors mqv --top-decile 0.03 "
                "--cost-bps 5.0 --asymmetric-trend --entry-sma 75 --no-include-pead "
                "--no-sector-neutral-quality --hysteresis-bonus 0.75 --momentum-flavor raw")


def _run_one(snap: str, rebal_days: int, offset: int, base_args: list[str]) -> dict:
    out = ROOT / "reports" / f".phase_tmp_{os.getpid()}_{offset}.json"
    cmd = [sys.executable, "-m", "scripts.run_factor_backtest",
           "--snapshot-id", snap, "--rebalance-days", str(rebal_days),
           "--rebal-offset", str(offset), "--output", str(out)] + base_args
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"backtest failed at offset {offset}:\n{proc.stderr[-1500:]}")
    r = json.loads(out.read_text())
    out.unlink(missing_ok=True)
    return {"offset": offset, "alpha": r["alpha_vs_spy_pct"],
            "capm": r.get("capm_alpha_pct", 0.0), "beta": r.get("beta", 0.0),
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
    # Each _run_one spawns an independent run_factor_backtest subprocess, so the
    # offsets are embarrassingly parallel. Run them concurrently across cores
    # (subprocess.run releases the GIL while waiting) instead of one-at-a-time.
    # Cap workers to bound RAM (each child loads the snapshot panel).
    from concurrent.futures import ThreadPoolExecutor
    workers = max(1, min(len(offsets), (os.cpu_count() or 4) // 2))
    print(f"phase envelope: {len(offsets)} phases (step {args.step}d) over a "
          f"{args.rebalance_days}d cycle | snap={args.snapshot_id} | {workers} parallel workers")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(
            lambda o: _run_one(args.snapshot_id, args.rebalance_days, o, base), offsets
        ))

    n = len(rows)
    capms = [r["capm"] for r in rows]     # Jensen alpha — primary, beta-adjusted
    alphas = [r["alpha"] for r in rows]   # raw excess return — secondary, beta-blind
    sharpes = [r["sharpe"] for r in rows]
    pct_pos_capm = 100 * sum(c > 0 for c in capms) / n
    pct_pos_excess = 100 * sum(a > 0 for a in alphas) / n
    wf_rate = 100 * sum(r["wf_pass"] for r in rows) / n

    def _stats(xs: list[float]) -> dict:
        return {"mean": round(statistics.mean(xs), 2), "median": round(statistics.median(xs), 2),
                "std": round(statistics.pstdev(xs), 2), "min": round(min(xs), 2), "max": round(max(xs), 2)}

    env = {
        "capm_alpha": {**_stats(capms), "pct_phases_positive": round(pct_pos_capm, 0)},
        "excess_return": {**_stats(alphas), "pct_phases_positive": round(pct_pos_excess, 0)},
        "sharpe": _stats(sharpes),
        "wf_pass_rate_pct": round(wf_rate, 0),
    }
    # Judge on CAPM alpha, not excess return: a regime-gated/cash-heavy book's
    # excess return flatters it (sitting in cash through a selloff beats a
    # falling SPY = "alpha" with zero skill), Jensen's alpha doesn't. An edge
    # should be mostly-positive with spread small relative to the mean.
    c = env["capm_alpha"]
    robust = c["median"] > 0 and pct_pos_capm >= 70 and c["std"] < abs(c["mean"]) * 1.5 + 5
    verdict = ("ROBUST across phases" if robust
               else "PHASE-LUCK / FRAGILE -- do not trust a single offset")

    report = {"snapshot": args.snapshot_id, "base_args": args.base_args,
              "n_phases": n, "per_phase": rows, "envelope": env, "verdict": verdict}
    out = ROOT / "reports" / f"phase_envelope_{args.snapshot_id}.json"
    out.write_text(json.dumps(report, indent=2))

    print(f"\n{'offset':>7}{'capmA%':>9}{'excess%':>9}{'beta':>6}{'sharpe':>8}{'maxDD%':>9}{'WF':>5}")
    for r in rows:
        print(f"{r['offset']:>7}{r['capm']:>+9.2f}{r['alpha']:>+9.2f}{r['beta']:>6.2f}"
              f"{r['sharpe']:>8.2f}{r['maxdd']:>9.2f}{'  ok' if r['wf_pass'] else '  --':>5}")
    print(f"\nCAPM-ALPHA envelope: mean {c['mean']:+.1f}%  median {c['median']:+.1f}%  "
          f"std {c['std']:.1f}  [{c['min']:+.1f} .. {c['max']:+.1f}]")
    a = env["excess_return"]
    print(f"excess-return (beta-blind): mean {a['mean']:+.1f}%  median {a['median']:+.1f}%")
    print(f"  {pct_pos_capm:.0f}% of phases CAPM-positive | WF-pass {wf_rate:.0f}% | "
          f"Sharpe median {env['sharpe']['median']:.2f}")
    print(f"\nVERDICT: {verdict}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
