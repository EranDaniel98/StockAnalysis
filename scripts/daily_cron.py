"""Unattended daily trading orchestrator — the Railway cron entrypoint.

Cross-platform successor to scripts/run_paper.ps1: one process that runs
the full trading day and pages (Telegram) on anything an operator would
need to know, so silence == something is wrong.

Flow (see docs/railway_deploy.md):
  1. Alpaca clock check — holidays/weekends exit 0 silently. The cron
     schedule (30 12 * * 1-5 UTC) is DST-naive on purpose; this step +
     the wait-for-open below absorb the EST/EDT drift.
  2. scripts.run_daily_pipeline --top-n N  (picks from last close; runs
     pre-open). The pipeline does its own DB pre-flight, per-step
     timeouts, and failure alerting.
  3. Refuse to trade if today's picks file is missing (the picks step
     failed) — alert + exit 1.
  4. Wait until market open + settle_minutes, then run the execution
     script for STOCKNEW_EXECUTION_MODE: paper (default) ->
     scripts.paper_trade_factor_picks, live ->
     scripts.live_trade_factor_picks. Always --execute (the dry-run
     safety lives in this script's --dry-run flag, not in forgetting a
     flag). Gate refusals inside the script alert on their own; a
     nonzero exit here is also alerted with the output tail.
  5. Mondays in paper mode: live-path dry-run smoke (no orders) so the
     dormant live wiring is exercised weekly before the Aug-27 verdict.
  6. One Telegram heartbeat with picks date/count, regime-gate + kill-
     switch status, order counts, and account equity.

Usage
-----

    uv run python -m scripts.daily_cron                # the real thing
    uv run python -m scripts.daily_cron --dry-run      # no orders
    uv run python -m scripts.daily_cron --force        # skip calendar +
                                                       # open-wait (drills)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("daily_cron")

PICKS_DIR = Path("data/daily_picks")
KILL_SWITCH_REPORT = Path("reports/kill_switch.json")

# Hard ceiling on the wait-for-open loop. 12:30 UTC cron + 14:30 UTC
# winter open + settle leaves ~2.5h of legitimate waiting; 6h means the
# clock API is lying to us and we'd rather alert than spin all day.
MAX_OPEN_WAIT_HOURS = 6


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--top-n", type=int, default=24,
                   help="Picks count forwarded to run_daily_pipeline.")
    p.add_argument("--dry-run", action="store_true",
                   help="Run everything except order submission (the "
                        "execution script runs WITHOUT --execute).")
    p.add_argument("--force", action="store_true",
                   help="Skip the trading-day check and the wait-for-open "
                        "(failure drills / weekend testing). Combine with "
                        "--dry-run unless you mean it.")
    p.add_argument("--settle-minutes", type=float, default=5.0,
                   help="Minutes after the opening bell before submitting "
                        "(default 5 -- skip the opening auction noise).")
    return p.parse_args()


def _alert(message: str) -> None:
    from src.alerts.telegram_bot import send_ops_alert

    send_ops_alert(message)


def _execution_mode() -> str:
    mode = (os.getenv("STOCKNEW_EXECUTION_MODE") or "paper").strip().lower()
    if mode not in ("paper", "live"):
        logger.warning("Unknown STOCKNEW_EXECUTION_MODE=%r -> paper", mode)
        return "paper"
    return mode


def _clock_client():
    """Paper AlpacaClient for read-only clock/account calls. The default
    fail-closed safety gate is fine -- nothing here submits orders."""
    from src.execution.alpaca import AlpacaClient

    return AlpacaClient()


def _is_trading_day(clock: dict) -> bool:
    """True when the market opens (or is open) on today's market-local
    date. Weekend/holiday: next_open lands on a different date."""
    if clock["is_open"]:
        return True
    if not clock.get("next_open"):
        return False
    next_open = datetime.fromisoformat(clock["next_open"])
    today_market = datetime.now(next_open.tzinfo).date()
    return next_open.date() == today_market


def _wait_for_open(client, settle_minutes: float) -> bool:
    """Block until the market is open and >= settle_minutes past the bell.
    Returns False if the MAX_OPEN_WAIT_HOURS budget is exhausted."""
    deadline = time.monotonic() + MAX_OPEN_WAIT_HOURS * 3600
    settle = timedelta(minutes=settle_minutes)
    settle_target = None  # known only if we observed the pre-open clock
    while time.monotonic() < deadline:
        clock = client.get_clock()
        if clock["is_open"]:
            if settle_target is not None:
                remaining = (settle_target
                             - datetime.now(settle_target.tzinfo)).total_seconds()
                if remaining > 0:
                    logger.info("Open -- settling %.0fs past the bell", remaining)
                    time.sleep(remaining)
            # No settle_target == we started mid-session (cron fired
            # late); the bell is long past, submit immediately.
            return True
        next_open = datetime.fromisoformat(clock["next_open"])
        settle_target = next_open + settle
        wait_s = (settle_target - datetime.now(next_open.tzinfo)).total_seconds()
        wait_s = max(30.0, min(wait_s, 15 * 60))
        logger.info("Market closed; next_open=%s -- sleeping %.0fs",
                    clock["next_open"], wait_s)
        time.sleep(wait_s)
    return False


def _run_step(args: list[str], *, capture: bool = False):
    """Run a child module with the current interpreter. Returns
    (returncode, tail_of_output) -- tail is '' unless capture=True."""
    cmd = [sys.executable, "-m", *args]
    logger.info("RUN: %s", " ".join(cmd))
    if not capture:
        return subprocess.run(cmd, check=False).returncode, ""
    res = subprocess.run(cmd, check=False, capture_output=True, text=True)
    out = (res.stdout or "") + (res.stderr or "")
    print(out, end="")  # keep the full transcript in the cron logs
    tail = "\n".join(out.strip().splitlines()[-12:])
    return res.returncode, tail


def _heartbeat(args, mode: str, today: str, pipeline_rc: int,
               trade_rc: int | None, smoke_note: str | None) -> str:
    """Compose the daily heartbeat. Every read is best-effort -- a partial
    heartbeat that arrives beats a perfect one that throws."""
    parts: list[str] = []

    picks_path = PICKS_DIR / f"{today}.json"
    try:
        payload = json.loads(picks_path.read_text(encoding="utf-8"))
        gate = payload.get("gate", {})
        if gate.get("trend_blocked") or gate.get("vix_blocked"):
            parts.append("REGIME GATE OFF -> flatten/stay-cash")
        else:
            parts.append(f"picks {len(payload.get('picks') or [])}")
    except Exception:  # noqa: BLE001
        parts.append("picks file MISSING")

    try:
        ks = json.loads(KILL_SWITCH_REPORT.read_text(encoding="utf-8"))
        parts.append(f"kill-switch {ks.get('status', '?')}")
    except Exception:  # noqa: BLE001
        parts.append("kill-switch report unread")

    log_path = PICKS_DIR / "execution_log" / f"{today}.json"
    try:
        ex = json.loads(log_path.read_text(encoding="utf-8"))
        parts.append(
            f"orders {len(ex.get('submitted') or [])} submitted / "
            f"{len(ex.get('skipped') or [])} skipped / "
            f"{len(ex.get('failed') or [])} failed"
        )
    except Exception:  # noqa: BLE001
        if trade_rc == 0:
            parts.append("no orders (flatten or already-aligned)")

    try:
        equity = _clock_client().get_account()["equity"]
        parts.append(f"equity ${equity:,.0f}")
    except Exception:  # noqa: BLE001
        pass

    status = "✅" if pipeline_rc == 0 and (trade_rc in (0, None)) else "⚠️"
    line = (
        f"{status} daily run {today} [{mode}"
        f"{', dry-run' if args.dry_run else ''}]: " + ", ".join(parts)
        + f". pipeline rc={pipeline_rc}"
    )
    if trade_rc is not None:
        line += f", trade rc={trade_rc}"
    if smoke_note:
        line += f". {smoke_note}"
    return line


def _live_smoke_due(mode: str, today_utc: datetime) -> bool:
    """Weekly (Monday) live-path dry-run while we run paper -- keeps the
    dormant live wiring exercised before the funding decision."""
    return mode == "paper" and today_utc.weekday() == 0


def _run_live_smoke() -> str:
    if not (os.getenv("ALPACA_LIVE_API_KEY")
            and os.getenv("ALPACA_LIVE_TRADING_CONFIRMED") == "1"):
        logger.info("live smoke skipped (no live keys in env)")
        return "live smoke: skipped (no live keys)"
    rc, _ = _run_step(["scripts.live_trade_factor_picks"], capture=True)
    return f"live smoke: rc={rc}"


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()
    mode = _execution_mode()
    now_utc = datetime.now(timezone.utc)
    today = now_utc.date().isoformat()

    # 1. Calendar gate.
    if not args.force:
        try:
            clock_client = _clock_client()
            clock = clock_client.get_clock()
        except Exception as e:  # noqa: BLE001
            logger.error("Alpaca clock unavailable: %s", e)
            _alert(f"❌ daily_cron {today}: Alpaca clock unavailable ({e}). "
                   f"No pipeline, no trades.")
            return 1
        if not _is_trading_day(clock):
            logger.info("Not a trading day (next_open=%s) -- exiting.",
                        clock.get("next_open"))
            return 0

    # 2. Pipeline (pre-open; picks come from the last close). It alerts
    # on its own failures; rc!=0 with a good picks file still trades.
    pipeline_rc, _ = _run_step(
        ["scripts.run_daily_pipeline", "--top-n", str(args.top_n)],
    )

    # 3. Picks-or-refuse. _load_picks would refuse too, but failing here
    # gives one precise alert instead of a generic trade-step failure.
    if not (PICKS_DIR / f"{today}.json").exists():
        logger.error("No picks file for %s -- refusing to trade.", today)
        _alert(f"🛑 daily_cron {today}: daily_factor_picks produced no picks "
               f"file (pipeline rc={pipeline_rc}). NOT trading today.")
        return 1

    # 4. Wait for the bell, then execute.
    if not args.force:
        if not _wait_for_open(clock_client, args.settle_minutes):
            _alert(f"❌ daily_cron {today}: market never opened within "
                   f"{MAX_OPEN_WAIT_HOURS}h of waiting. NOT trading.")
            return 1

    trade_module = ("scripts.paper_trade_factor_picks" if mode == "paper"
                    else "scripts.live_trade_factor_picks")
    trade_args = [trade_module, "--picks-date", today]
    if not args.dry_run:
        trade_args.append("--execute")
    trade_rc, tail = _run_step(trade_args, capture=True)
    if trade_rc != 0:
        _alert(f"🛑 daily_cron {today} [{mode}]: execution step failed "
               f"(rc={trade_rc}). Tail:\n{tail}")

    # 5. Weekly live-path smoke (paper mode only, Mondays, never orders).
    smoke_note = None
    if _live_smoke_due(mode, now_utc):
        smoke_note = _run_live_smoke()

    # 6. Heartbeat -- sent on every trading day, success or not.
    _alert(_heartbeat(args, mode, today, pipeline_rc, trade_rc, smoke_note))
    return 0 if (pipeline_rc == 0 and trade_rc == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
