"""Wait for a running PID to exit, then kick off the Russell-1000 insider-flow A/B sweep.

Designed to be detached from any shell:

    Start-Process pwsh -ArgumentList '-NoProfile','-Command','uv run python -m scripts.wait_then_sweep --pid 32056' -WindowStyle Hidden

The poll loop is OS-agnostic (psutil is in uv's runtime env). Logs to
``data/sweep_insider_flow_russell1000.log`` so progress is visible after
the parent terminal is closed.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

DEFAULT_LOG_PATH = Path("data/sweep_insider_flow_russell1000.log")
DEFAULT_JSON_PATH = Path("data/sweep_insider_flow_russell1000.json")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _setup_logger(path: Path) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("wait_then_sweep")
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(path, mode="a", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(sh)
    return logger


def _pid_alive(pid: int) -> bool:
    """Cross-platform `is process N still running` without psutil dependency."""
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:
        if sys.platform == "win32":
            # subprocess fallback — tasklist returns INFO message when missing
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True,
            )
            return str(pid) in r.stdout
        try:
            import os
            os.kill(pid, 0)
            return True
        except (PermissionError, OSError):
            return False


def wait_for_pid(pid: int, poll_seconds: int, logger: logging.Logger) -> None:
    logger.info("waiting for PID %d to exit (poll every %ds)", pid, poll_seconds)
    if not _pid_alive(pid):
        logger.info("PID %d is not running — proceeding immediately", pid)
        return
    while _pid_alive(pid):
        time.sleep(poll_seconds)
    logger.info("PID %d exited", pid)


def run_sweep(
    strategy: str,
    universe: str,
    years: float,
    save_path: Path,
    save_full_path: Path | None,
    bootstrap_resamples: int,
    logger: logging.Logger,
) -> int:
    cmd = [
        "uv", "run", "python", "-m", "scripts.sweep_insider_flow",
        "--strategy", strategy,
        "--universe", universe,
        "--years", str(years),
        "--save", str(save_path),
        "--bootstrap-resamples", str(bootstrap_resamples),
    ]
    if save_full_path is not None:
        cmd.extend(["--save-full", str(save_full_path)])
    logger.info("starting sweep: %s", " ".join(cmd))
    # Stream stdout to the log file in real time so the user sees progress.
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        logger.info(line.rstrip())
    rc = proc.wait()
    logger.info("sweep finished with exit code %d", rc)
    return rc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True, help="PID to wait for before starting the sweep")
    parser.add_argument("--poll-seconds", type=int, default=60, help="Poll interval (seconds)")
    parser.add_argument("--strategy", default="swing_trading")
    parser.add_argument("--universe", default="russell_1000")
    parser.add_argument("--years", type=float, default=2.0)
    parser.add_argument("--save", default=str(DEFAULT_JSON_PATH))
    parser.add_argument("--save-full", default=None)
    parser.add_argument("--bootstrap-resamples", type=int, default=0)
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    args = parser.parse_args()

    log_path = Path(args.log_path)
    save_path = Path(args.save)
    save_full = Path(args.save_full) if args.save_full else None
    logger = _setup_logger(log_path)
    logger.info("launcher started — args: %s", vars(args))
    wait_for_pid(args.pid, args.poll_seconds, logger)
    rc = run_sweep(
        args.strategy, args.universe, args.years,
        save_path, save_full, args.bootstrap_resamples,
        logger,
    )
    return rc


if __name__ == "__main__":
    sys.exit(main())
