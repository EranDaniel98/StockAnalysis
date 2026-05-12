"""add notes column to paper_trades for the trade journal

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-12

Single-column add. Nullable + no default — existing rows stay empty until
the user writes a note via PATCH /api/trades/{id}.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("paper_trades", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("paper_trades", "notes")
