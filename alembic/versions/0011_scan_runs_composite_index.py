"""scan_runs: composite (strategy, scan_timestamp DESC) index

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-17

Closes the audit's DB-architecture finding on /api/scans/latest-buys:
the endpoint wants "latest scan per strategy", which without a composite
index requires a sequential scan or two separate index seeks. With this
composite, ``SELECT DISTINCT ON (strategy) ... ORDER BY strategy,
scan_timestamp DESC`` is an index-only skip scan.

The old single-column ``ix_scan_runs_strategy`` is dropped because the
new composite is a strict superset for any query that filters on
strategy (including the existing ``list_scans?strategy=...`` path).
``ix_scan_runs_scan_timestamp`` is kept because some queries
(e.g. dashboard "what was active in this window") filter on
scan_timestamp without strategy.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Composite index. Postgres natively supports per-column ASC/DESC,
    # and DISTINCT ON skip-scans love a matching order. Using
    # sa.text("scan_timestamp DESC") because alembic's
    # create_index doesn't accept the index_element form directly.
    op.create_index(
        "ix_scan_runs_strategy_ts_desc",
        "scan_runs",
        ["strategy", sa.text("scan_timestamp DESC")],
    )

    # Drop the now-redundant single-column index on strategy.
    op.drop_index("ix_scan_runs_strategy", table_name="scan_runs")


def downgrade() -> None:
    op.create_index(
        "ix_scan_runs_strategy",
        "scan_runs",
        ["strategy"],
    )
    op.drop_index("ix_scan_runs_strategy_ts_desc", table_name="scan_runs")
