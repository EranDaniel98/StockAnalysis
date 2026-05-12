"""Backup the StockNew local stack to a single timestamped directory.

What's captured:

  - Postgres logical dump (custom format → fast parallel restore)
  - data/ohlcv/  Parquet OHLCV store
  - data/models/ ML model artifacts (joblib + manifest)
  - config/*.yaml snapshot
  - manifest.json with git SHA, alembic head, byte sizes, timestamps

What's *not* captured:
  - Redis (it's a cache — disposable by design)
  - .env (the user's secrets stay with the user)
  - data/cache.db (legacy Phase 0; superseded by Parquet + Redis)
  - .next/, node_modules/, .venv/

Layout:
    backups/YYYY-MM-DDTHHMMSSZ/
      stocknew.dump         # pg_dump -F c
      ohlcv.tar.gz
      models.tar.gz
      config/
        settings.yaml
        ...
      manifest.json

Usage:
    uv run python -m scripts.backup
    uv run python -m scripts.backup --output backups/before-migration
    uv run python -m scripts.backup --skip-ohlcv     # smaller, DB-only

Postgres lives in the docker-compose container; pg_dump runs *inside* the
container to guarantee version match with the server, then we copy the
file out via ``docker cp``.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backup")


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"
DEFAULT_BACKUP_ROOT = REPO_ROOT / "backups"

POSTGRES_SERVICE = "postgres"        # docker compose service name
POSTGRES_CONTAINER = "stocknew-postgres"  # actual container name (for docker cp)
POSTGRES_USER = "stocknew"
POSTGRES_DB = "stocknew"
PG_DUMP_PATH_IN_CONTAINER = "/tmp/stocknew.dump"


def _run(cmd: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Wrapper around subprocess.run with consistent logging.

    ``capture=True`` keeps stdout/stderr off the terminal so manifest
    builders don't get spammed.
    """
    logger.debug("$ %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=capture,
    )


def _git_sha() -> Optional[str]:
    try:
        result = _run(["git", "rev-parse", "HEAD"], capture=True)
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _git_dirty() -> bool:
    try:
        result = _run(["git", "status", "--porcelain"], capture=True)
        return bool(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _alembic_head() -> Optional[str]:
    """Current alembic revision (matches what's actually applied)."""
    try:
        result = _run(["alembic", "current"], capture=True)
        # Output looks like "0006 (head)" — first token is the revision.
        line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        return line.split(" ")[0] if line else None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _dump_postgres(out_path: Path) -> None:
    """pg_dump in the container, then docker cp out. We use ``-F c``
    (custom format) for parallel-friendly pg_restore on the way back."""
    logger.info("running pg_dump inside %s …", POSTGRES_CONTAINER)
    _run(
        [
            "docker", "compose", "exec", "-T", POSTGRES_SERVICE,
            "pg_dump",
            "-U", POSTGRES_USER,
            "-d", POSTGRES_DB,
            "-F", "c",
            "-f", PG_DUMP_PATH_IN_CONTAINER,
        ],
    )
    logger.info("copying dump out of container → %s", out_path)
    _run(
        [
            "docker", "cp",
            f"{POSTGRES_CONTAINER}:{PG_DUMP_PATH_IN_CONTAINER}",
            str(out_path),
        ],
    )
    # Tidy up inside the container so we don't leave stale dumps.
    _run(
        [
            "docker", "compose", "exec", "-T", POSTGRES_SERVICE,
            "rm", "-f", PG_DUMP_PATH_IN_CONTAINER,
        ],
        check=False,
    )


def _tar_directory(src: Path, out_path: Path) -> int:
    """Write a tarball of ``src`` to ``out_path``. Returns byte size."""
    if not src.exists() or not any(src.iterdir()):
        logger.info("skip %s (empty or missing)", src)
        # Create an empty marker so the manifest can still record presence
        # without a missing-file restore failure.
        out_path.with_suffix(".empty").touch()
        return 0
    logger.info("tar+gz %s → %s", src, out_path)
    with tarfile.open(out_path, "w:gz") as tar:
        tar.add(src, arcname=src.name)
    return out_path.stat().st_size


def _copy_config(config_dir: Path, dest: Path) -> int:
    """Copy YAML config files. Returns total byte size."""
    dest.mkdir(parents=True, exist_ok=True)
    total = 0
    for yaml_file in sorted(config_dir.glob("*.yaml")):
        target = dest / yaml_file.name
        shutil.copy2(yaml_file, target)
        total += target.stat().st_size
    return total


def run_backup(
    *,
    output: Path,
    skip_ohlcv: bool = False,
    skip_models: bool = False,
    skip_config: bool = False,
) -> Path:
    """Top-level orchestrator. Returns the backup directory path."""
    output.mkdir(parents=True, exist_ok=True)
    logger.info("backup target: %s", output)

    manifest: dict = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "git_dirty": _git_dirty(),
        "alembic_head": _alembic_head(),
        "components": {},
    }

    # Postgres dump
    dump_path = output / "stocknew.dump"
    _dump_postgres(dump_path)
    manifest["components"]["postgres"] = {
        "file": "stocknew.dump",
        "bytes": dump_path.stat().st_size,
        "format": "pg_dump -F c (custom)",
    }

    # Parquet OHLCV
    if not skip_ohlcv:
        ohlcv_path = output / "ohlcv.tar.gz"
        size = _tar_directory(DEFAULT_DATA_DIR / "ohlcv", ohlcv_path)
        manifest["components"]["ohlcv"] = {
            "file": "ohlcv.tar.gz",
            "bytes": size,
        }

    # ML artifacts
    if not skip_models:
        models_path = output / "models.tar.gz"
        size = _tar_directory(DEFAULT_DATA_DIR / "models", models_path)
        manifest["components"]["models"] = {
            "file": "models.tar.gz",
            "bytes": size,
        }

    # Config YAMLs
    if not skip_config:
        cfg_dest = output / "config"
        size = _copy_config(DEFAULT_CONFIG_DIR, cfg_dest)
        manifest["components"]["config"] = {
            "dir": "config",
            "bytes": size,
        }

    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    logger.info("backup complete (%s)", output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Backup directory (default: backups/{ISO_TIMESTAMP})",
    )
    parser.add_argument("--skip-ohlcv", action="store_true")
    parser.add_argument("--skip-models", action="store_true")
    parser.add_argument("--skip-config", action="store_true")
    args = parser.parse_args()

    if args.output is None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        args.output = DEFAULT_BACKUP_ROOT / ts

    try:
        run_backup(
            output=args.output,
            skip_ohlcv=args.skip_ohlcv,
            skip_models=args.skip_models,
            skip_config=args.skip_config,
        )
    except subprocess.CalledProcessError as e:
        logger.error("subcommand failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
