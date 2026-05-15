"""Daily snapshot capture for the 30-day paper-validation phase.

Run this once per trading day (Windows Task Scheduler / cron / manual).
The script:

  1. Queries Alpaca for current account equity, cash, positions.
  2. Reads PaperDB for refusal counts (orphan / safety_gate / score_valid)
     observed by the most recent `paper trade` run.
  3. Persists a row to data/validation.db keyed by (strategy, today).
  4. Optionally runs `paper trade --strategy NAME` first when
     --invoke-paper-trade is passed.

Idempotent: re-running on the same day updates the existing row.

How to schedule (Windows Task Scheduler):

  schtasks /Create /SC DAILY /TN StockNew-Validation /TR ^
      "cmd /c cd /d C:\\Users\\Eran Daniel\\Desktop\\Personal\\StockNew && ^
       uv run python -m scripts.validation_daily" /ST 16:15

Pick a time AFTER market close (16:00 ET = 21:00 UTC) so positions and
P&L are settled. 16:15 ET / 21:15 UTC is the safe default.

The harness is observation-only by default — it does NOT submit trades.
Live trading still requires:
  * trading_enabled: true (or STOCKNEW_TRADING_ENABLED=1)
  * the operator-driven `paper trade` invocation, OR
  * --invoke-paper-trade on this script (drives both together)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

logger = logging.getLogger("validation_daily")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--strategy", default="minimal_baseline",
        help="Strategy whose snapshots get tagged (default: minimal_baseline)",
    )
    p.add_argument(
        "--snapshot-date", default=None,
        help="ISO date for the snapshot row. Defaults to today. Override "
        "only for backfill or test scenarios.",
    )
    p.add_argument(
        "--invoke-paper-trade", action="store_true",
        help="Run `paper trade --strategy NAME` BEFORE the snapshot. "
        "Without this flag the script is observation-only.",
    )
    p.add_argument(
        "--note", default=None,
        help="Free-form annotation stored on the row.",
    )
    p.add_argument(
        "--db-path", default=None,
        help="Override the validation DB location (default: data/validation.db)",
    )
    return p.parse_args()


def _today_iso() -> str:
    return date.today().isoformat()


def _count_refusals_today(snapshot_date: str) -> dict:
    """Read PaperDB for refusal-related counts on ``snapshot_date``.

    We count recommendations rows whose skip_reason matches each gate so
    a sudden spike on any day is visible in the daily diff. PaperDB's
    schema doesn't carry a date-on-recommendation column directly, but
    scan_timestamp is ISO so we can prefix-match.
    """
    from src.execution.paper_db import PaperDB

    out = {
        "orphan": 0,
        "safety_gate": 0,
        "score_valid": 0,
        "submitted": 0,
    }
    try:
        with PaperDB() as db:
            # Use the underlying connection to run the prefix query so we
            # don't have to add a public method just for this counter.
            rows = db._conn.execute(
                """
                SELECT skip_reason, submitted FROM recommendations
                WHERE substr(scan_timestamp, 1, 10) = ?
                """,
                (snapshot_date,),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read PaperDB refusal counts: %s", exc)
        return out

    for r in rows:
        reason = (r["skip_reason"] or "")
        if r["submitted"]:
            out["submitted"] += 1
        if reason.startswith("orphan_"):
            out["orphan"] += 1
        elif reason.startswith("safety_gate"):
            out["safety_gate"] += 1
        elif "score_valid" in reason:
            # No skip_reason today carries score_valid (the gate intercepts
            # at the broker boundary), but keep this branch for forward-
            # compat if/when the recommender mirrors the flag.
            out["score_valid"] += 1
    return out


def _capture_alpaca_snapshot():
    """Read account equity + positions from Alpaca. Returns a dict or
    None on failure (caller decides whether to abort)."""
    from src.execution.alpaca import AlpacaClient, AlpacaClientError
    from src.execution.safety_gates import TradingSafetyGate
    from src.config_loader import Config

    config = Config()
    # Build a permissive read-only gate — we never submit from here, but
    # AlpacaClient is fail-closed without one. Read-only methods don't
    # consult the gate so any gate works; pass the config-derived one
    # for consistency.
    gate = TradingSafetyGate.from_config(config)
    try:
        client = AlpacaClient(safety_gate=gate)
    except AlpacaClientError as exc:
        logger.error("Alpaca connect failed: %s", exc)
        return None

    acct = client.get_account()
    positions = client.get_positions()
    return {
        "equity": float(acct.get("equity") or 0.0),
        "cash": float(acct.get("cash") or 0.0),
        "long_market_value": float(acct.get("long_market_value") or 0.0),
        "positions": [p["ticker"] for p in positions],
    }


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    snapshot_date = args.snapshot_date or _today_iso()
    logger.info(
        "validation_daily start — strategy=%s, date=%s, invoke_paper_trade=%s",
        args.strategy, snapshot_date, args.invoke_paper_trade,
    )

    # Step 1 (optional): run paper_trade. We invoke as a subprocess so a
    # failure inside paper_trade doesn't kill the snapshot — the harness
    # ALWAYS wants the snapshot to land, even on a no-trade day.
    if args.invoke_paper_trade:
        import subprocess
        cmd = [
            sys.executable, "-m", "src.cli.main", "paper", "trade",
            "--strategy", args.strategy,
        ]
        logger.info("invoking paper_trade: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=1800,
            )
            logger.info("paper_trade exit=%s", result.returncode)
            if result.returncode != 0:
                logger.warning("paper_trade stderr:\n%s", result.stderr[-2000:])
        except subprocess.TimeoutExpired:
            logger.error("paper_trade timed out after 30 min — snapshot anyway")
        except Exception as exc:  # noqa: BLE001
            logger.error("paper_trade invocation failed: %s — snapshot anyway", exc)

    # Step 2: capture Alpaca snapshot.
    snap = _capture_alpaca_snapshot()
    if snap is None:
        logger.error("No Alpaca snapshot captured — aborting (no DB row written).")
        return 2

    # Step 3: read refusal counts from PaperDB for this date.
    counts = _count_refusals_today(snapshot_date)

    # Step 4: persist.
    from src.validation.store import DailySnapshot, ValidationStore

    db_path = Path(args.db_path) if args.db_path else None
    with ValidationStore(db_path=db_path) as store:
        row_id = store.upsert_snapshot(DailySnapshot(
            strategy=args.strategy,
            snapshot_date=snapshot_date,
            account_equity=snap["equity"],
            account_cash=snap["cash"],
            long_market_value=snap["long_market_value"],
            n_positions=len(snap["positions"]),
            open_tickers=snap["positions"],
            refusals_orphan=counts["orphan"],
            refusals_safety_gate=counts["safety_gate"],
            refusals_score_valid=counts["score_valid"],
            submitted_today=counts["submitted"],
            notes=args.note,
        ))

    logger.info(
        "snapshot persisted row_id=%s equity=$%s positions=%d "
        "(orphan_refused=%d, safety_gate_refused=%d, submitted=%d)",
        row_id, f"{snap['equity']:,.2f}", len(snap["positions"]),
        counts["orphan"], counts["safety_gate"], counts["submitted"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
