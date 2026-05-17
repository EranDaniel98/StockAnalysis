"""Wait for a running PID to exit, then launch a named sweep battery.

Mirrors scripts.wait_then_sweep but targets run_sweep_battery instead of
a single sweep — used today to chain the heavy-fundamental battery
behind the light battery without overlapping CPU saturation.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def _setup_logger(path: Path) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("wait_then_battery")
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(path, mode="a", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(sh)
    return logger


def _pid_alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        if sys.platform == "win32":
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--battery", required=True,
                        help="Preset name passed to run_sweep_battery --battery")
    parser.add_argument("--bootstrap-resamples", type=int, default=2000)
    parser.add_argument("--out-dir", default="data/sweep_battery")
    parser.add_argument("--log-path", default="data/sweep_battery_chain.log")
    args = parser.parse_args()

    log = _setup_logger(Path(args.log_path))
    log.info("chain launcher started — args: %s", vars(args))
    log.info("waiting for PID %d to exit (poll every %ds)", args.pid, args.poll_seconds)
    while _pid_alive(args.pid):
        time.sleep(args.poll_seconds)
    log.info("PID %d exited at %s", args.pid, datetime.now().isoformat())

    cmd = [
        "uv", "run", "python", "-m", "scripts.run_sweep_battery",
        "--battery", args.battery,
        "--bootstrap-resamples", str(args.bootstrap_resamples),
        "--out-dir", args.out_dir,
    ]
    log.info("launching battery: %s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        bufsize=1, text=True,
        cwd=str(Path(__file__).parent.parent),
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        log.info(line.rstrip())
    rc = proc.wait()
    log.info("battery finished with exit code %d", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
