"""short_interest table — FINRA Reg SHO daily short-sale volume

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-13

One row per (ticker, settlement_date) of daily short-sale volume from
FINRA's CNMS (Consolidated NMS) Reg SHO files. URL pattern:

    https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt

Columns: Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market

The downstream short_interest analyzer reads biweekly-style rows with
``short_interest_shares`` + ``avg_daily_volume`` — the loader synthesizes
those from rolling 30-day windows of these daily rows. See
``src.market_data.short_interest_finra.loader`` for the conversion.

Index on ticker (for the loader's "all rows for these tickers in a
window" query). settlement_date stays inside the composite unique
constraint — that constraint doubles as an index for range scans.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "short_interest",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("settlement_date", sa.Date(), nullable=False),
        sa.Column(
            "short_volume",
            sa.BigInteger(),
            nullable=False,
            comment="Shares sold short that day on the consolidated tape",
        ),
        sa.Column(
            "total_volume",
            sa.BigInteger(),
            nullable=False,
            comment="Total shares traded that day on the consolidated tape",
        ),
        sa.Column(
            "short_exempt_volume",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Short-exempt volume (market-maker exempt sales); subset of short_volume",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "ticker", "settlement_date", name="uq_short_interest_ticker_date"
        ),
    )
    op.create_index(
        "ix_short_interest_ticker",
        "short_interest",
        ["ticker"],
    )
    # Composite read pattern: loader filters by (ticker IN ..., date BETWEEN).
    # Postgres can use this for the range scan without re-sorting.
    op.create_index(
        "ix_short_interest_ticker_date",
        "short_interest",
        ["ticker", "settlement_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_short_interest_ticker_date", table_name="short_interest")
    op.drop_index("ix_short_interest_ticker", table_name="short_interest")
    op.drop_table("short_interest")
