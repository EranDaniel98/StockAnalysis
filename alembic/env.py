"""Alembic environment for StockNew.

Reads the DSN from src.db.session.get_dsn() (which honors STOCKNEW_DATABASE_URL).
Uses the async engine for both online and offline modes.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config

# Make sure src/ is importable when running `alembic upgrade head` from project root
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.session import Base, get_dsn  # noqa: E402
import src.db.models  # noqa: E402,F401  (register models with Base.metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without connecting to the DB."""
    url = get_dsn()
    # Alembic's offline mode wants a sync-style DSN string. Strip the +asyncpg.
    url_offline = url.replace("+asyncpg", "")
    context.configure(
        url=url_offline,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Connect to the live DB and apply migrations."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_dsn()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        future=True,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
