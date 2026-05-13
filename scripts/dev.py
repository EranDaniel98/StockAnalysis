"""Dev launcher — runs the FastAPI backend and the Next.js frontend together.

Streams both stdouts to one terminal with [api] / [web] prefixes so you can
watch them side by side. Ctrl+C stops both cleanly.

Usage:
    uv run python -m scripts.dev

API: http://127.0.0.1:8000  (FastAPI + /docs)
Web: http://localhost:3000  (Next.js dev server)

Implementation notes:
  - Each child runs in its own process group so Ctrl+C in the parent
    propagates to the subtree (npm spawns node + esbuild workers).
  - Output threads read stdout line-by-line. We don't try to merge stderr
    separately — uvicorn and Next.js both log to stdout in dev mode.
  - On Windows, npm is npm.cmd; shell=True handles the .cmd discovery.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import IO

# ANSI colors for the [api] / [web] prefixes. Falls through to no-color when
# stdout isn't a TTY (CI logs, redirected files).
_USE_COLOR = sys.stdout.isatty()
_RESET = "\033[0m" if _USE_COLOR else ""
_CYAN = "\033[36m" if _USE_COLOR else ""
_MAGENTA = "\033[35m" if _USE_COLOR else ""
_BOLD = "\033[1m" if _USE_COLOR else ""
_DIM = "\033[2m" if _USE_COLOR else ""


def _label(name: str, color: str, width: int = 5) -> str:
    return f"{color}{_BOLD}[{name:^{width-2}}]{_RESET}"


def _pump_output(stream: IO[bytes], label: str) -> None:
    """Read stream line-by-line and re-emit with a labeled prefix. Blocks
    until the child closes its stdout."""
    try:
        for raw in iter(stream.readline, b""):
            try:
                line = raw.decode("utf-8", errors="replace").rstrip()
            except Exception:
                line = repr(raw)
            print(f"{label} {line}", flush=True)
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _spawn(cmd: list[str] | str, cwd: Path, *, shell: bool) -> subprocess.Popen:
    """Spawn a child with merged stdout/stderr in its own process group.

    On Windows we set CREATE_NEW_PROCESS_GROUP so we can send CTRL_BREAK
    later; on POSIX we use os.setsid so SIGINT propagates to the subtree."""
    if os.name == "nt":
        kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        kwargs = {"preexec_fn": os.setsid}
    return subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        shell=shell,
        **kwargs,
    )


def _terminate(p: subprocess.Popen, name: str) -> None:
    """Best-effort shutdown: SIGINT/CTRL_BREAK first, SIGKILL after a grace
    window. Avoids dangling node / uvicorn processes after Ctrl+C."""
    if p.poll() is not None:
        return
    try:
        if os.name == "nt":
            p.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(os.getpgid(p.pid), signal.SIGINT)
    except (ProcessLookupError, OSError):
        pass
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        print(f"{_DIM}[{name}] did not exit on SIGINT — killing.{_RESET}", flush=True)
        try:
            p.kill()
        except Exception:
            pass


def main() -> int:
    root = Path(__file__).parent.parent.resolve()
    web_dir = root / "web"
    if not (web_dir / "package.json").exists():
        print(f"{_DIM}error:{_RESET} {web_dir} has no package.json — wrong root?", file=sys.stderr)
        return 2

    print(f"{_DIM}{_BOLD}stocknew dev launcher{_RESET}{_DIM}  -  Ctrl+C to stop both{_RESET}")
    print(f"{_DIM}  api -> http://127.0.0.1:8000{_RESET}")
    print(f"{_DIM}  web -> http://localhost:3000{_RESET}")
    print()

    # uv run keeps us inside the project's venv. The --reload flag matches
    # what the user would have typed by hand in a single-terminal session.
    api_cmd: list[str] = ["uv", "run", "python", "-m", "scripts.run_api", "--reload"]
    # npm.cmd discovery on Windows wants shell=True.
    web_cmd = "npm run dev"

    api = _spawn(api_cmd, root, shell=False)
    web = _spawn(web_cmd, web_dir, shell=True)

    api_label = _label("api", _CYAN)
    web_label = _label("web", _MAGENTA)

    api_thread = threading.Thread(target=_pump_output, args=(api.stdout, api_label), daemon=True)
    web_thread = threading.Thread(target=_pump_output, args=(web.stdout, web_label), daemon=True)
    api_thread.start()
    web_thread.start()

    rc = 0
    try:
        # Block until either child exits. If one dies, take the other down
        # too — running half a dev stack just confuses things.
        while True:
            api_rc = api.poll()
            web_rc = web.poll()
            if api_rc is not None:
                rc = api_rc
                print(f"{_DIM}[api] exited with code {api_rc}{_RESET}", flush=True)
                break
            if web_rc is not None:
                rc = web_rc
                print(f"{_DIM}[web] exited with code {web_rc}{_RESET}", flush=True)
                break
            try:
                api.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
    except KeyboardInterrupt:
        print(f"\n{_DIM}stopping...{_RESET}", flush=True)
    finally:
        _terminate(api, "api")
        _terminate(web, "web")
        # Let the pump threads flush trailing output.
        api_thread.join(timeout=2)
        web_thread.join(timeout=2)

    return rc


if __name__ == "__main__":
    sys.exit(main())
