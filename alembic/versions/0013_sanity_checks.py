"""sanity_checks: persist pre-trade AI sanity-check results

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-17

Pre-trade sanity check (src/research_agent/sanity_check.py) is a
defensive LLM pass that can downgrade a BUY to CAUTION or REJECT, but
never upgrade. Results are keyed by (ticker, run_id) so they tie to the
specific scan_run that produced the BUY — re-running on the same run
upserts, guaranteeing one row per check.

The ON DELETE CASCADE link to scan_runs.run_id keeps the table tidy:
when an operator deletes a scan, its sanity checks go with it. The
existing unique constraint on scan_runs.run_id (added in 0012) is what
makes the foreign key viable.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sanity_checks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("catalysts_found", JSONB(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("model_used", sa.String(length=64), nullable=False),
        sa.Column("mocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("ticker", "run_id", name="uq_sanity_checks_ticker_run"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["scan_runs.run_id"],
            name="fk_sanity_checks_run_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_sanity_checks_run_id",
        "sanity_checks",
        ["run_id"],
    )
    op.create_index(
        "ix_sanity_checks_ticker_checked_at",
        "sanity_checks",
        ["ticker", sa.text("checked_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_sanity_checks_ticker_checked_at", table_name="sanity_checks")
    op.drop_index("ix_sanity_checks_run_id", table_name="sanity_checks")
    op.drop_table("sanity_checks")
