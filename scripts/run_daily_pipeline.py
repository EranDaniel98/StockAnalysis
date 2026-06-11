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
    "mark_ai_book",
    "mark_momval_book",
    "momval_picks",
    "sma_watch",
    "kill_switch_check",
]

# Research / advisory steps — surfaced in the summary but never fail the run.
# The AI + momentum-value forward books are research books isolated from the
# live config; a hiccup marking one must not flip the daily exit code.
_ADVISORY = {"mark_ai_book", "mark_momval_book", "momval_picks", "sma_watch"}


def _step_timeout_seconds() -> float | None:
    """Per-step wall-clock cap from config. None disables the cap."""
    try:
        from src.config_loader import Config

        minutes = float(Config().get(
            "pipeline", "step_timeout_minutes", default=30,
        ) or 0)
    except Exception:  # noqa: BLE001 — config trouble must not kill the run
        minutes = 30.0
    return minutes * 60.0 if minutes > 0 else None


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
            timeout=_step_timeout_seconds(),
        )
        if result.returncode != 0:
            logger.error("STEP %s exit code %d", step, result.returncode)
            return False
        # Success marker — the SSE pipeline parser (src/api/routers/pipeline.py
        # _STEP_DONE_RE) needs a "STEP <name> exit code <n>" line on EVERY
        # completion, not just failures. Without this, successful steps never
        # emit step_completed and the web step-ladder shows them stuck/failed.
        logger.info("STEP %s exit code 0", step)
        return True
    except subprocess.TimeoutExpired:
        # Keep the "STEP <name> exit code <n>" shape the SSE parser keys on.
        logger.error("STEP %s exit code -1 (timed out after %s)",
                     step, _step_timeout_seconds())
        return False
    except Exception as e:  # noqa: BLE001
        logger.error("STEP %s exception: %s", step, e)
        return False


def _db_preflight() -> bool:
    """SELECT 1 against Postgres before any step runs.

    daily_factor_picks needs the EDGAR PIT fundamentals in Postgres; a
    dead DB would crash step 1 with a stack trace half an hour into the
    run. Failing here instead gives the unattended operator one clear
    alert before anything starts.
    """
    try:
        from sqlalchemy import text

        from src.db.session import get_sessionmaker, run_with_dispose

        async def _ping():
            async with get_sessionmaker()() as session:
                await session.execute(text("SELECT 1"))

        run_with_dispose(_ping())
        logger.info("DB pre-flight OK")
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("DB pre-flight FAILED: %s", e)
        return False


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--picks-date", default=None,
                   help="YYYY-MM-DD. Defaults to today.")
    p.add_argument("--top-n", type=int, default=24,
                   help="Number of picks (default 24 = top 5%%, matches "
                        "daily_factor_picks default since 2026-05-23 d05 revert).")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    date_str = args.picks_date or datetime.now(timezone.utc).date().isoformat()
    date_us = date_str.replace("-", "_")
    Path("reports").mkdir(exist_ok=True)
    Path("data/daily_picks").mkdir(parents=True, exist_ok=True)

    if not _db_preflight():
        from src.alerts.telegram_bot import send_ops_alert

        send_ops_alert(
            f"❌ daily pipeline {date_str}: Postgres unreachable "
            f"(DB pre-flight failed). No steps ran; no trades today."
        )
        return 1

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

    # 8.5 Mark the AI forward book to live prices (research, non-gating).
    # State already holds its universe_file, so no --universe-file needed; the
    # mark is idempotent per date. Rebalances itself when its 63td cadence is due.
    results["mark_ai_book"] = _run(
        ["scripts.research.trend_forward_paper", "--book", "ai",
         "--as-of", date_str],
        "mark_ai_book",
    )

    # 8.6 Mark the momentum-value forward-paper book (research, non-gating).
    # Marks to live prices daily; rebalances on its 63td cadence via the
    # mom+val pipeline. Surfaced at /research/momval-book.
    results["mark_momval_book"] = _run(
        ["scripts.research.momval_forward_paper", "--as-of", date_str],
        "mark_momval_book",
    )

    # 8.7 Mom-value FRESH candidates screener (research, non-gating). Re-ranks
    # the mom+val top-24 daily so /research/momval-book can show held-vs-new.
    results["momval_picks"] = _run(
        ["scripts.momval_picks", "--as-of", date_str],
        "momval_picks",
    )

    # 8.8 SMA trend-line watch (research, non-gating). Flags whether the
    # watched trend proxies (USO/XLE) are holding or breaking their 50-SMA --
    # the line behind the energy-book oil-trend call.
    results["sma_watch"] = _run(
        ["scripts.research.sma_watch"],
        "sma_watch",
    )

    # 9. Kill-switch check (advisory in this pipeline -- the hard gate lives
    # in paper_trade_factor_picks.py before order submission). --soft makes
    # this step never fail the daily run; it just refreshes the report and
    # advances the strategy-rollover counter.
    results["kill_switch_check"] = _run(
        ["scripts.kill_switch_check", "--soft"],
        "kill_switch_check",
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
        advisory = " (advisory)" if step in _ADVISORY else ""
        marker = "[OK]" if ok else ("[skip]" if step in _ADVISORY else "[FAIL]")
        print(f"  {marker} {step}{advisory}")
    print()
    print(f"Outputs in: reports/ and data/daily_picks/")
    print()
    print("Next: review reports/morning_briefing_{}.md first.".format(date_us))
    print()
    # Advisory/research steps don't gate the exit code.
    failed = [s for s in STEPS if s not in _ADVISORY and not results.get(s, False)]
    if failed:
        from src.alerts.telegram_bot import send_ops_alert

        send_ops_alert(
            f"❌ daily pipeline {date_str}: {len(failed)} step(s) FAILED: "
            f"{', '.join(failed)}. Check logs before trading."
        )
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
