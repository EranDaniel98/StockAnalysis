"""One-shot driver: run a Russell-1000 scan + persist to scan_runs.

Same code path the API uses (src.api.services.scan_runner.run_scan_sync),
just invoked from a CLI process so it doesn't require uvicorn to be up.
The persisted ScanRun row is picked up by the web /scan page on next load.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from datetime import datetime, timezone

from src.api.schemas.scan import ScanResultItem
from src.api.services.scan_runner import run_scan_sync
from src.config_loader import Config
from src.db.models import ScanRun
from src.db.session import dispose_engine, get_sessionmaker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("russell_scan")


def _emit(event: dict) -> None:
    stage = event.get("stage", "?")
    n = event.get("n")
    if "ticker" in event and event["ticker"]:
        return  # too noisy at universe scale; skip per-ticker chatter
    if n is not None:
        logger.info("STAGE %s n=%d", stage, n)
    else:
        logger.info("STAGE %s", stage)


async def persist_run(strategy: str, run_id: str, results: list[ScanResultItem]) -> None:
    SL = get_sessionmaker()
    async with SL() as session:
        row = ScanRun(
            strategy=strategy,
            scan_timestamp=datetime.now(timezone.utc),
            universe_label=run_id,
            budget=None,
            n_candidates=len(results),
            recommendations=[r.model_dump() for r in results],
        )
        session.add(row)
        await session.commit()
    await dispose_engine()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", default="swing_trading")
    parser.add_argument("--universe", default="russell_1000")
    parser.add_argument("--live-signals", action="store_true")
    parser.add_argument("--top", type=int, default=None)
    args = parser.parse_args()

    config = Config()
    try:
        strategy_cfg = config.get_strategy(args.strategy)
    except KeyError:
        logger.error("unknown strategy %r", args.strategy)
        return 2

    logger.info(
        "starting scan: strategy=%s universe=%s live_signals=%s",
        args.strategy, args.universe, args.live_signals,
    )

    recs_raw = run_scan_sync(
        config,
        strategy_cfg,
        universe=args.universe,
        theme=None,
        sector=None,
        fresh=False,
        live_signals=args.live_signals,
        on_event=_emit,
    )

    if args.top is not None:
        recs_raw = recs_raw[: args.top]

    results = [ScanResultItem.model_validate(r) for r in recs_raw]
    run_id = str(uuid.uuid4())

    logger.info("persisting %d results as run_id=%s", len(results), run_id)
    asyncio.run(persist_run(args.strategy, run_id, results))

    # Print top 20 + STRONG BUY shortlist.
    grades: dict[str, int] = {}
    for r in results:
        grades[r.action] = grades.get(r.action, 0) + 1
    logger.info("Grade breakdown: %s", grades)

    strong_buys = [r for r in results if r.action == "STRONG BUY"]
    buys = [r for r in results if r.action == "BUY"]

    print()
    print("=" * 70)
    print(f"RUSSELL 1000 SCAN — strategy={args.strategy} live_signals={args.live_signals}")
    print(f"run_id: {run_id}")
    print(f"n_results: {len(results)}")
    print(f"grades: {grades}")
    print("=" * 70)
    print()
    print(f"STRONG BUY ({len(strong_buys)}):")
    if strong_buys:
        print(f"  {'TICKER':<8} {'SCORE':>6}  {'SECTOR':<22} {'NAME'}")
        for r in strong_buys[:20]:
            name = (r.name or "")[:40]
            print(
                f"  {r.ticker:<8} {r.composite_score:>6.1f}  "
                f"{r.sector[:22]:<22} {name}"
            )
    else:
        print("  (none)")
    print()
    print(f"BUY top-10 of {len(buys)}:")
    if buys:
        print(f"  {'TICKER':<8} {'SCORE':>6}  {'SECTOR':<22} {'NAME'}")
        for r in buys[:10]:
            name = (r.name or "")[:40]
            print(
                f"  {r.ticker:<8} {r.composite_score:>6.1f}  "
                f"{r.sector[:22]:<22} {name}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
