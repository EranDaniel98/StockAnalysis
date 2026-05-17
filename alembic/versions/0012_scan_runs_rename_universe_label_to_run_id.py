"""scan_runs: rename universe_label → run_id, add unique constraint

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-17

Closes the audit's universe_label-overload finding. scan_runs has been
stuffing a fresh UUID into universe_label since the table was born —
but universe_label is a column intended for descriptors like
"sp500_pit" / "watchlist" / "themes" (and that IS how the other tables
backtest_runs / ic_diagnostics use it). Conflating the two makes it
structurally impossible to query "all sp500_pit scans" later, and a
future caller writing a real descriptor would collide with the UUID
namespace.

This migration only touches scan_runs. backtest_runs.universe_label /
ic_diagnostics.universe_label are correctly named and stay.

Adds a unique constraint so duplicate run_ids fail loudly at write
time rather than producing ambiguous reads.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "scan_runs",
        "universe_label",
        new_column_name="run_id",
        existing_type=sa.String(length=64),
        existing_nullable=False,
    )
    op.create_unique_constraint(
        "uq_scan_runs_run_id", "scan_runs", ["run_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_scan_runs_run_id", "scan_runs", type_="unique")
    op.alter_column(
        "scan_runs",
        "run_id",
        new_column_name="universe_label",
        existing_type=sa.String(length=64),
        existing_nullable=False,
    )
