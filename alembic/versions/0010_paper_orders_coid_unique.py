"""paper_orders.client_order_id: backfill, widen, NOT NULL + UNIQUE

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-15

Closes Tier-1 audit finding E#1/E#25/T#21. Before this migration,
`paper_orders.client_order_id` was nullable and unconstrained, so a
retry that bypassed Alpaca's duplicate check could double-write the
orders table with no error. After this migration:

  * legacy NULL rows are backfilled with `legacy-{id}` so the column
    can be tightened without dropping history
  * column is widened to 128 chars to match Alpaca's max
  * NOT NULL is enforced
  * UNIQUE constraint enforces idempotency at the database, not just at
    the application layer

Downgrade re-relaxes the column but does NOT remove the backfill values.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfill NULL rows so the NOT NULL alter doesn't fail.
    op.execute(
        "UPDATE paper_orders SET client_order_id = 'legacy-' || id "
        "WHERE client_order_id IS NULL"
    )

    # Widen + tighten in one alter. server_default is intentionally absent;
    # the application always sets the value, NOT NULL enforces that.
    op.alter_column(
        "paper_orders",
        "client_order_id",
        existing_type=sa.String(length=64),
        type_=sa.String(length=128),
        existing_nullable=True,
        nullable=False,
    )

    op.create_unique_constraint(
        "uq_paper_orders_client_order_id",
        "paper_orders",
        ["client_order_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_paper_orders_client_order_id", "paper_orders", type_="unique"
    )
    op.alter_column(
        "paper_orders",
        "client_order_id",
        existing_type=sa.String(length=128),
        type_=sa.String(length=64),
        existing_nullable=False,
        nullable=True,
    )
