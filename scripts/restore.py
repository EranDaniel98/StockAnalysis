"""Restore a StockNew backup created by ``scripts.backup``.

Destructive on purpose. Postgres is *dropped and recreated* before the
dump is replayed. The OHLCV + models directories are wiped before tar
extraction. Config restore is opt-in (the user's current YAMLs usually
have edits they don't want to lose).

Usage:
    # Dry-run — prints what would happen
    uv run python -m scripts.restore --from backups/2026-05-12T120000Z

    # Actually run it
    uv run python -m scripts.restore --from backups/2026-05-12T120000Z --confirm

    # Include config restore (off by default)
    uv run python -m scripts.restore --from <dir> --confirm --include-config
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("restore")


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"

POSTGRES_SERVICE = "postgres"
POSTGRES_CONTAINER = "stocknew-postgres"
POSTGRES_USER = "stocknew"
POSTGRES_DB = "stocknew"
PG_RESTORE_PATH_IN_CONTAINER = "/tmp/stocknew_restore.dump"


def _run(cmd: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    logger.debug("$ %s", " ".join(cmd))
    return subprocess.run(cmd, check=check, text=True, capture_output=capture)


def _load_manifest(src: Path) -> dict:
    manifest_path = src / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"manifest.json missing in {src}. Is this a StockNew backup directory?"
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _restore_postgres(dump_path: Path) -> None:
    """Drop the existing DB, recreate empty, then pg_restore from the
    custom-format dump.

    DROP DATABASE has to run from a different DB on the same cluster,
    so we connect to ``postgres`` (the default maintenance DB)."""
    if not dump_path.exists():
        raise FileNotFoundError(f"dump file missing: {dump_path}")

    logger.warning("DROPPING database %s — this is destructive", POSTGRES_DB)
    _run(
        [
            "docker", "compose", "exec", "-T", POSTGRES_SERVICE,
            "psql", "-U", POSTGRES_USER, "-d", "postgres", "-v", "ON_ERROR_STOP=1",
            "-c", f'DROP DATABASE IF EXISTS "{POSTGRES_DB}" WITH (FORCE);',
        ],
    )
    _run(
        [
            "docker", "compose", "exec", "-T", POSTGRES_SERVICE,
            "psql", "-U", POSTGRES_USER, "-d", "postgres", "-v", "ON_ERROR_STOP=1",
            "-c", f'CREATE DATABASE "{POSTGRES_DB}" OWNER "{POSTGRES_USER}";',
        ],
    )

    logger.info("copying dump into container …")
    _run(
        [
            "docker", "cp",
            str(dump_path),
            f"{POSTGRES_CONTAINER}:{PG_RESTORE_PATH_IN_CONTAINER}",
        ],
    )

    logger.info("running pg_restore …")
    # --no-owner / --no-acl: ignore role mismatches when restoring across
    # environments. Custom-format dumps don't need --clean since the DB
    # is freshly recreated above.
    _run(
        [
            "docker", "compose", "exec", "-T", POSTGRES_SERVICE,
            "pg_restore",
            "-U", POSTGRES_USER,
            "-d", POSTGRES_DB,
            "--no-owner",
            "--no-acl",
            PG_RESTORE_PATH_IN_CONTAINER,
        ],
    )

    _run(
        [
            "docker", "compose", "exec", "-T", POSTGRES_SERVICE,
            "rm", "-f", PG_RESTORE_PATH_IN_CONTAINER,
        ],
        check=False,
    )


def _restore_tarball(tarball: Path, target_parent: Path, *, expected_inner: str) -> None:
    """Wipe ``target_parent/{expected_inner}`` then extract the tarball.

    The tarball was written with ``arcname=src.name``, so the top-level
    entry is named after the original directory. We verify before extract.
    """
    if not tarball.exists():
        # Backup may have written an .empty marker — nothing to restore.
        empty = tarball.with_suffix(".empty")
        if empty.exists():
            logger.info("skip %s (backup recorded as empty)", tarball.name)
            return
        logger.warning("skip %s (not in this backup)", tarball.name)
        return

    target = target_parent / expected_inner
    if target.exists():
        logger.warning("WIPING %s before restore", target)
        shutil.rmtree(target)
    target_parent.mkdir(parents=True, exist_ok=True)

    logger.info("extracting %s → %s", tarball, target_parent)
    with tarfile.open(tarball, "r:gz") as tar:
        # Safe-extract: refuse absolute paths or paths with .. so a malicious
        # tar (or a corrupted one) can't write outside target_parent.
        for member in tar.getmembers():
            name = member.name
            if name.startswith("/") or ".." in Path(name).parts:
                raise RuntimeError(f"refusing to extract suspicious path: {name}")
        tar.extractall(target_parent)


def _restore_config(src_config: Path) -> None:
    if not src_config.exists():
        logger.warning("skip config (not in this backup)")
        return
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    for yaml_file in sorted(src_config.glob("*.yaml")):
        target = DEFAULT_CONFIG_DIR / yaml_file.name
        logger.info("overwriting %s", target.name)
        shutil.copy2(yaml_file, target)


def run_restore(
    *,
    src: Path,
    confirm: bool,
    include_config: bool = False,
) -> None:
    """Top-level orchestrator."""
    manifest = _load_manifest(src)
    logger.info("restoring from %s", src)
    logger.info("  created_at:    %s", manifest.get("created_at"))
    logger.info("  git_sha:       %s%s",
                manifest.get("git_sha") or "<unknown>",
                " (dirty)" if manifest.get("git_dirty") else "")
    logger.info("  alembic_head:  %s", manifest.get("alembic_head"))
    logger.info("  components:    %s", ", ".join(manifest.get("components", {}).keys()))

    if not confirm:
        logger.warning("dry-run — re-run with --confirm to actually restore")
        return

    components = manifest.get("components", {})

    if "postgres" in components:
        _restore_postgres(src / components["postgres"]["file"])

    if "ohlcv" in components:
        _restore_tarball(
            src / components["ohlcv"]["file"],
            target_parent=DEFAULT_DATA_DIR,
            expected_inner="ohlcv",
        )

    if "models" in components:
        _restore_tarball(
            src / components["models"]["file"],
            target_parent=DEFAULT_DATA_DIR,
            expected_inner="models",
        )

    if include_config and "config" in components:
        _restore_config(src / "config")

    logger.info("restore complete")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from", dest="src", type=Path, required=True,
        help="Backup directory to restore from (must contain manifest.json)",
    )
    parser.add_argument(
        "--confirm", action="store_true",
        help="Required to actually run. Without it, prints the plan and exits.",
    )
    parser.add_argument(
        "--include-config", action="store_true",
        help="Also overwrite config/*.yaml. Off by default — these usually have local edits.",
    )
    args = parser.parse_args()

    try:
        run_restore(
            src=args.src,
            confirm=args.confirm,
            include_config=args.include_config,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError) as e:
        logger.error("restore failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
