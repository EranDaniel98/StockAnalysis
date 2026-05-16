"""Ablation runner: same strategy + snapshot, each engine mechanic
disabled in turn.

Answers the user's hypothesis "non-score machinery (ATR stop, time
stop, min_score gate) might be delivering the apparent alpha, not the
score itself." Each ablation toggles ONE mechanic via the CLI overrides
shipped on scripts/run_minimal_baseline.py, keeping everything else
fixed (same strategy YAML, same snapshot, same regime mode).

Outputs:
  * data/baseline/ablation_<strategy>_<label>_<snapshot_id>.json
    (one per ablation, full slim result)
  * data/baseline/ablation_<strategy>_<label>_<snapshot_id>.err
    (each strategy's stderr)

Usage
-----
    uv run python -m scripts.run_ablations \\
        --snapshot-id <id> \\
        --strategy minimal_baseline_v2 \\
        [--end-date 2024-05-13] \\
        [--years 2]
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path


logger = logging.getLogger("run_ablations")


# Each row: (label, extra CLI args for run_minimal_baseline.py).
# baseline (no overrides) is included so the comparison sits on the
# same exact code path; we don't reuse a separately-produced JSON.
ABLATIONS: list[tuple[str, list[str]]] = [
    ("baseline", []),
    ("no_min_score", ["--min-score-override", "0"]),
    ("no_atr_stop", ["--atr-stop-mult-override", "99"]),
    ("no_time_stop", ["--max-hold-days-override", "9999"]),
    ("all_mechanics_off", [
        "--min-score-override", "0",
        "--atr-stop-mult-override", "99",
        "--max-hold-days-override", "9999",
    ]),
]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ablation harness.")
    p.add_argument("--snapshot-id", required=True)
    p.add_argument("--strategy", required=True,
                   help="Strategy from config/strategies.yaml.")
    p.add_argument("--years", type=float, default=2.0)
    p.add_argument("--end-date", default=None)
    p.add_argument("--starting-cash", type=float, default=10_000.0)
    p.add_argument("--pit-fundamentals", action="store_true")
    p.add_argument("--results-dir", default="data/baseline")
    p.add_argument(
        "--include-baseline", action="store_true",
        help="Also run the 'baseline' (no overrides) variant — set "
             "this only if you don't already have a clean run on the "
             "same strategy+snapshot. Default skips it (compare_*.json "
             "from compare_strategies.py serves as the baseline).",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    results = Path(args.results_dir)
    results.mkdir(parents=True, exist_ok=True)

    queued = [
        (label, extra) for (label, extra) in ABLATIONS
        if label != "baseline" or args.include_baseline
    ]
    logger.info("Running %d ablations on %s (snapshot %s)",
                len(queued), args.strategy, args.snapshot_id)

    for label, extra in queued:
        out = results / f"ablation_{args.strategy}_{label}_{args.snapshot_id}.json"
        err = out.with_suffix(".err")
        cmd = [
            "uv", "run", "python", "-m", "scripts.run_minimal_baseline",
            "--snapshot-id", args.snapshot_id,
            "--strategy", args.strategy,
            "--years", str(args.years),
            "--starting-cash", str(args.starting_cash),
            "--ablation-label", label,
            "--output", str(out),
        ]
        if args.pit_fundamentals:
            cmd.append("--pit-fundamentals")
        if args.end_date:
            cmd.extend(["--end-date", args.end_date])
        cmd.extend(extra)
        logger.info("[%s] -> %s ...", label, out)
        with err.open("wb") as ef:
            rc = subprocess.call(cmd, stdout=ef, stderr=subprocess.STDOUT)
        if rc != 0:
            logger.error("[%s] FAILED rc=%d (see %s)", label, rc, err)
            return rc
        logger.info("[%s] DONE", label)

    logger.info("All ablations complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
