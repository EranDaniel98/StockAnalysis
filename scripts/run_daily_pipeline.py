"""Run the full daily pipeline in one command.

Sequences:
  1. daily_factor_picks      → today's top-N composite picks
  2. comprehensive_analysis  → 24 per-stock trading plans
  3. exit_analysis           → sell plan for current paper positions
  4. position_monitor        → stop/target check on held positions
  5. morning_briefing        → single-page summary (reads #1 + #2 outputs)

Each step writes its own file under `reports/` and `data/daily_picks/`.
If any step fails, the pipeline continues so partial results are
still usable.

Usage
-----

    uv run python -m scripts.run_daily_pipeline                 # today
    uv run python -m scripts.run_daily_pipeline --top-n 24
    uv run python -m scripts.run_daily_pipeline --picks-date 2026-05-16
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("run_daily_pipeline")


STEPS = [
    "daily_factor_picks",
    "comprehensive_analysis",
    "exit_analysis",
    "position_monitor",
    "stress_test",
    "generate_watchlist",
    "ai_sanity_check",
    "morning_briefing",
    "paper_vs_spy_snapshot",
]


def _run(args: list[str], step: str) -> bool:
    logger.info("=" * 60)
    logger.info("STEP: %s", step)
    logger.info("CMD : uv run python -m %s", " ".join(args))
    logger.info("=" * 60)
    try:
        # Inherit stdout/stderr so the user sees progress live.
        result = subprocess.run(
            ["uv", "run", "python", "-m", *args],
            check=False,
            shell=False,
        )
        if result.returncode != 0:
            logger.error("STEP %s exit code %d", step, result.returncode)
            return False
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("STEP %s exception: %s", step, e)
        return False


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--picks-date", default=None,
                   help="YYYY-MM-DD. Defaults to today.")
    p.add_argument("--top-n", type=int, default=15,
                   help="Number of picks (default 15 = top 3%%, matches "
                        "daily_factor_picks default since 2026-05-19 d03 ship).")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    date_str = args.picks_date or datetime.now(timezone.utc).date().isoformat()
    date_us = date_str.replace("-", "_")
    Path("reports").mkdir(exist_ok=True)
    Path("data/daily_picks").mkdir(parents=True, exist_ok=True)

    results: dict[str, bool] = {}

    # 1. Daily picks (live yfinance — slowest step)
    results["daily_factor_picks"] = _run(
        ["scripts.daily_factor_picks", "--top-n", str(args.top_n),
         "--as-of", date_str, "--output-dir", "data/daily_picks"],
        "daily_factor_picks",
    )

    # 2. Comprehensive analysis
    results["comprehensive_analysis"] = _run(
        ["scripts.comprehensive_analysis",
         "--picks-date", date_str,
         "--output", f"reports/portfolio_analysis_{date_us}.md"],
        "comprehensive_analysis",
    )

    # 3. Exit analysis (needs alpaca; harmless if no positions)
    results["exit_analysis"] = _run(
        ["scripts.exit_analysis",
         "--picks-date", date_str,
         "--output", f"reports/exit_plan_{date_us}.md"],
        "exit_analysis",
    )

    # 4. Position monitor (uses the comprehensive analysis JSON)
    results["position_monitor"] = _run(
        ["scripts.position_monitor",
         "--output", f"reports/position_monitor_{date_us}.md"],
        "position_monitor",
    )

    # 5. Stress test (uses the comprehensive analysis JSON)
    results["stress_test"] = _run(
        ["scripts.stress_test",
         "--output", f"reports/stress_test_{date_us}.md"],
        "stress_test",
    )

    # 6. Watchlist (ranks 25-75 — names on the bubble)
    results["generate_watchlist"] = _run(
        ["scripts.generate_watchlist",
         "--as-of", date_str,
         "--start-rank", "25", "--end-rank", "75",
         "--output", f"reports/watchlist_{date_us}.md"],
        "generate_watchlist",
    )

    # 7. AI sanity check (advisory only, runs before morning briefing so
    #    the briefing can pull from it if extended later).
    results["ai_sanity_check"] = _run(
        ["scripts.ai_sanity_check",
         "--picks-date", date_str,
         "--output-dir", "reports"],
        "ai_sanity_check",
    )

    # 8. Morning briefing (reads picks JSON + analysis JSON)
    results["morning_briefing"] = _run(
        ["scripts.morning_briefing",
         "--picks-date", date_str,
         "--output", f"reports/morning_briefing_{date_us}.md"],
        "morning_briefing",
    )

    # 8. Paper-vs-SPY snapshot (single live file, refreshed every run).
    # Read-only with respect to Alpaca; failure modes are graceful.
    results["paper_vs_spy_snapshot"] = _run(
        ["scripts.paper_vs_spy_snapshot"],
        "paper_vs_spy_snapshot",
    )

    # Force UTF-8 stdout so unicode summary markers don't crash on
    # cp1252 Windows consoles.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    print()
    print("=" * 60)
    print("DAILY PIPELINE RESULT")
    print("=" * 60)
    for step in STEPS:
        ok = results.get(step, False)
        marker = "[OK]" if ok else "[FAIL]"
        print(f"  {marker} {step}")
    print()
    print(f"Outputs in: reports/ and data/daily_picks/")
    print()
    print("Next: review reports/morning_briefing_{}.md first.".format(date_us))
    print()
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
