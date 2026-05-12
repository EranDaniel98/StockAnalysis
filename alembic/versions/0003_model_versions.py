"""model registry table

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-12

One row per trained model version. Versioning is per ``model_name`` —
e.g. lightgbm_v1, lightgbm_v2 each get their own monotonic counter
under the same name. The training pipeline picks the next version and
writes the row after the artifact is on disk.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_versions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("model_name", sa.String(64), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("train_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("train_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("factor_set", sa.String(32), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("model_name", "version", name="uq_model_versions_name_version"),
    )


def downgrade() -> None:
    op.drop_table("model_versions")
