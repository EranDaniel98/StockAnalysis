"""Drift-detection CLI for daily picks.

Compares today's picks JSON to the trailing N days. Exits 0 on pass
or warn, exits 2 on fail — so a wrapper can short-circuit the paper
trade flow before bad data reaches the broker.

Usage
-----

    uv run python -m scripts.check_picks_drift \\
        --picks data/daily_picks/2026-05-18.json \\
        --history-dir data/daily_picks/ \\
        --days 30

By default the report prints to stdout. Pass ``--json-out PATH`` to
also write a machine-readable copy.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from src.factors.drift_detector import (
    compute_drift_report, format_markdown,
)

logger = logging.getLogger("check_picks_drift")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--picks", required=True,
                   help="Today's picks JSON.")
    p.add_argument("--history-dir", default="data/daily_picks",
                   help="Directory containing trailing pick JSONs.")
    p.add_argument("--days", type=int, default=30,
                   help="Trailing window in days for baselines (default 30).")
    p.add_argument("--json-out", default=None,
                   help="Optional path to write the machine-readable report.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress the markdown table — only set exit code "
                        "and a one-line summary.")
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()

    report = compute_drift_report(
        today_path=Path(args.picks),
        history_dir=Path(args.history_dir),
        days=args.days,
    )

    if not args.quiet:
        print(format_markdown(report))
    summary = (
        f"Drift report: {report.overall_status.upper()} "
        f"({sum(1 for c in report.checks if c.status == 'fail')} fail, "
        f"{sum(1 for c in report.checks if c.status == 'warn')} warn)"
    )
    logger.info(summary)

    if args.json_out:
        # asdict converts the dataclass tree. checks come out as a list
        # of dicts because the report dataclass declares it that way.
        Path(args.json_out).write_text(
            json.dumps(asdict(report), indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("Wrote machine-readable report to %s", args.json_out)

    if report.overall_status == "fail":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
