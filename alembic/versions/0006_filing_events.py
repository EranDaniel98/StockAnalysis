"""filing event monitor tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-12

Two tables back the background filing-event monitor:

  monitored_tickers
    Tracks (ticker, last_seen_accession_no, last_polled_at) per
    monitored ticker. On first poll for a ticker we record its
    most recent accession without firing — otherwise the user
    gets buried in historical filings.

  filing_notifications
    One row per new filing detected. Mirrors the SSE event so
    the /research/feed page is a straight DB read on load and
    only relies on SSE for live updates.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monitored_tickers",
        sa.Column("ticker", sa.String(16), primary_key=True),
        sa.Column(
            "last_seen_accession_no", sa.String(32), nullable=True
        ),
        sa.Column(
            "last_polled_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_table(
        "filing_notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(16), nullable=False, index=True),
        sa.Column("form", sa.String(16), nullable=False),
        sa.Column("accession_no", sa.String(32), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("primary_document", sa.Text(), nullable=True),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            index=True,
        ),
        sa.Column(
            "research_run_id",
            sa.BigInteger(),
            sa.ForeignKey("research_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=True,
            comment="Cached agent synthesis if summarization was triggered",
        ),
        sa.UniqueConstraint(
            "ticker", "accession_no", name="uq_filing_notifications_ticker_accn"
        ),
    )


def downgrade() -> None:
    op.drop_table("filing_notifications")
    op.drop_table("monitored_tickers")
