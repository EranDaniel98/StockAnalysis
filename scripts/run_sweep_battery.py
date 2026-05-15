"""Run a battery of insider-flow A/B sweeps sequentially.

For each (universe, strategy) entry, invokes scripts.sweep_insider_flow
with bootstrap CIs + full-result dump enabled, then aggregates a
single consolidated summary at the end.

Designed to be launched detached:

    powershell Start-Process -FilePath 'uv' -ArgumentList @(
        'run','python','-m','scripts.run_sweep_battery'
    ) -RedirectStandardOutput 'data\sweep_battery.log' \
      -RedirectStandardError 'data\sweep_battery.err' -WindowStyle Hidden

The orchestrator prints a banner around each sweep so the log is
greppable for stage transitions.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# (universe, strategy, years, pit). When ``pit`` is True the sweep loads
# EDGAR PIT fundamentals from Postgres — required for strategies with
# fundamental weight > 0.05, otherwise the engine's lookahead guard fires.
BATTERIES: dict[str, list[tuple[str, str, float, bool]]] = {
    "light": [
        ("russell_1000", "swing_trading", 2.0, False),
        ("russell_1000", "short_term_momentum", 2.0, False),
        ("russell_1000", "mean_reversion", 2.0, False),
    ],
    "heavy": [
        ("russell_1000", "long_term_growth", 2.0, True),
        ("russell_1000", "value_investing", 2.0, True),
        ("russell_1000", "dividend_income", 2.0, True),
    ],
    "all": [
        ("russell_1000", "swing_trading", 2.0, False),
        ("russell_1000", "short_term_momentum", 2.0, False),
        ("russell_1000", "mean_reversion", 2.0, False),
        ("russell_1000", "long_term_growth", 2.0, True),
        ("russell_1000", "value_investing", 2.0, True),
        ("russell_1000", "dividend_income", 2.0, True),
    ],
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sweep_battery")


def _slug(universe: str, strategy: str, years: float) -> str:
    return f"{universe}_{strategy}_{int(years)}y"


def run_one(
    universe: str,
    strategy: str,
    years: float,
    pit: bool,
    bootstrap_resamples: int,
    out_dir: Path,
) -> tuple[str, int, float, Path]:
    slug = _slug(universe, strategy, years)
    save_path = out_dir / f"sweep_{slug}.json"
    full_path = out_dir / f"sweep_{slug}.full.json"
    log_path = out_dir / f"sweep_{slug}.console.log"
    cmd = [
        "uv", "run", "python", "-m", "scripts.sweep_insider_flow",
        "--universe", universe,
        "--strategy", strategy,
        "--years", str(years),
        "--bootstrap-resamples", str(bootstrap_resamples),
        "--save", str(save_path),
        "--save-full", str(full_path),
    ]
    if pit:
        cmd.append("--pit-fundamentals")
    logger.info("=" * 72)
    logger.info("SWEEP %s × %s × %sy %s starting",
                universe, strategy, years, "(PIT)" if pit else "")
    logger.info("cmd: %s", " ".join(cmd))
    t0 = time.time()
    with log_path.open("w", encoding="utf-8") as logf:
        proc = subprocess.run(
            cmd, stdout=logf, stderr=subprocess.STDOUT,
            cwd=str(Path(__file__).parent.parent),
        )
    elapsed = time.time() - t0
    logger.info("SWEEP %s done in %.1fs (exit %d)", slug, elapsed, proc.returncode)
    return slug, proc.returncode, elapsed, save_path


def _read_summary(save_path: Path) -> list[dict] | None:
    if not save_path.exists():
        return None
    try:
        return json.loads(save_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _print_battery_summary(results: list[dict]) -> None:
    print("\n" + "=" * 96)
    print("INSIDER-FLOW SWEEP BATTERY — consolidated summary")
    print("=" * 96)
    print(
        f"  {'Universe':<14} {'Strategy':<22} {'Mode':<12} "
        f"{'OOS Sharpe':>10} {'Full Sharpe':>11} {'Trades':>7} {'Win %':>6}"
    )
    print("  " + "-" * 92)
    for r in results:
        slug = r["slug"]
        if r["rows"] is None:
            print(f"  [{slug}] FAILED (exit {r['exit']})")
            continue
        universe, strategy = r["universe"], r["strategy"]
        for row in r["rows"]:
            print(
                f"  {universe:<14} {strategy:<22} {row['mode']:<12} "
                f"{row['oos_sharpe']:>+10.2f} {row['full_sharpe']:>+11.2f} "
                f"{row['n_trades']:>7} {row['win_rate_pct']:>5.1f}"
            )
        print("  " + "-" * 92)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--battery", default="light", choices=sorted(BATTERIES.keys()),
        help="Which preset to run: light (no PIT) / heavy (PIT) / all (both)",
    )
    parser.add_argument(
        "--bootstrap-resamples", type=int, default=500,
        help="Bootstrap iterations per mode (0 disables; default 500). "
             "Was 2000; dropped because the headline metrics are point "
             "estimates and only the CIs widen modestly. Trade ~5%% of "
             "wall time for tighter CI precision if you need it.",
    )
    parser.add_argument(
        "--parallelism", type=int, default=1,
        help="How many sweeps to run concurrently (default 1 = sequential). "
             "Each sweep already spawns 8 worker threads internally, so a "
             "machine with 12-16 cores comfortably runs --parallelism 2-3. "
             "Sweeps have no shared state — output files, score caches, "
             "and DB connections are all per-process.",
    )
    parser.add_argument(
        "--skip-existing", action="store_true",
        help="Skip strategies whose JSON output already exists in --out-dir. "
             "Useful to resume a battery after a kill or crash without "
             "redoing completed work.",
    )
    parser.add_argument(
        "--out-dir", default="data/sweep_battery",
        help="Directory to write per-sweep outputs",
    )
    args = parser.parse_args()

    battery = BATTERIES[args.battery]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.skip_existing:
        before = len(battery)
        battery = [
            (u, s, y, pit) for (u, s, y, pit) in battery
            if not (out_dir / f"sweep_{_slug(u, s, y)}.json").exists()
        ]
        skipped = before - len(battery)
        if skipped:
            logger.info("--skip-existing: skipping %d already-complete sweep(s)", skipped)

    logger.info(
        "battery '%s' starting — %d sweeps, parallelism=%d, "
        "bootstrap_resamples=%d, output to %s",
        args.battery, len(battery), args.parallelism,
        args.bootstrap_resamples, out_dir,
    )

    results: list[dict] = []
    t_total = time.time()

    if args.parallelism <= 1:
        # Sequential path — preserved for back-compat and easy log-reading.
        for universe, strategy, years, pit in battery:
            slug, rc, elapsed, save_path = run_one(
                universe, strategy, years, pit, args.bootstrap_resamples, out_dir
            )
            rows = _read_summary(save_path)
            results.append({
                "slug": slug,
                "universe": universe,
                "strategy": strategy,
                "years": years,
                "exit": rc,
                "elapsed_sec": elapsed,
                "rows": rows,
            })
    else:
        # Parallel path — submit all sweeps to a pool sized at --parallelism.
        # Subprocesses are independent (each writes a distinct slug.json
        # under out_dir; the score cache is per-process so no shared
        # state to coordinate). Each worker thread blocks on its child
        # subprocess via subprocess.run, so the thread count just gates
        # how many child processes run concurrently.
        params_by_slug = {
            _slug(u, s, y): (u, s, y, pit) for (u, s, y, pit) in battery
        }
        with ThreadPoolExecutor(max_workers=args.parallelism) as ex:
            futures = {
                ex.submit(
                    run_one, u, s, y, pit, args.bootstrap_resamples, out_dir,
                ): _slug(u, s, y)
                for (u, s, y, pit) in battery
            }
            for fut in as_completed(futures):
                expected_slug = futures[fut]
                try:
                    slug, rc, elapsed, save_path = fut.result()
                except Exception as e:
                    logger.error(
                        "SWEEP %s crashed in worker: %s: %s",
                        expected_slug, type(e).__name__, e,
                    )
                    universe, strategy, years, _pit = params_by_slug[expected_slug]
                    results.append({
                        "slug": expected_slug,
                        "universe": universe,
                        "strategy": strategy,
                        "years": years,
                        "exit": -1,
                        "elapsed_sec": 0.0,
                        "rows": None,
                        "worker_error": f"{type(e).__name__}: {e}",
                    })
                    continue
                rows = _read_summary(save_path)
                universe, strategy, years, _pit = params_by_slug[slug]
                results.append({
                    "slug": slug,
                    "universe": universe,
                    "strategy": strategy,
                    "years": years,
                    "exit": rc,
                    "elapsed_sec": elapsed,
                    "rows": rows,
                })

    total_elapsed = time.time() - t_total
    logger.info("battery done in %.1fs (%.1fm)", total_elapsed, total_elapsed / 60)

    _print_battery_summary(results)

    consolidated = out_dir / "battery_consolidated.json"
    consolidated.write_text(
        json.dumps({
            "completed_at": datetime.now().isoformat(),
            "total_elapsed_sec": round(total_elapsed, 1),
            "results": results,
        }, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("consolidated summary written to %s", consolidated)
    return 0 if all(r["exit"] == 0 for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
