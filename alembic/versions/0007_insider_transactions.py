"""insider transactions table

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-13

Stores parsed SEC Form 4 transactions. One row per non-derivative
transaction reported on a Form 4 filing (a single filing can include
multiple transactions — different securities, different dates within
the report period, etc.).

Primary read pattern: "all open-market buys for ticker X over date
range Y" — backs the insider_flow analyzer's cluster detection.

Why a (accession_no, owner_cik, transaction_date, transaction_code,
shares) composite uniqueness instead of relying on accession alone:
the SEC allows an amended Form 4/A to be filed with the same accession
on a small subset of transactions — we want to keep each transaction
distinct without double-counting on re-ingestion of the same filing.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "insider_transactions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        # Issuer identification
        sa.Column("ticker", sa.String(16), nullable=False, index=True),
        sa.Column("issuer_cik", sa.String(16), nullable=False),
        sa.Column("issuer_name", sa.Text(), nullable=True),
        # Filing metadata
        sa.Column("accession_no", sa.String(32), nullable=False, index=True),
        sa.Column("filing_date", sa.Date(), nullable=False),
        # Insider identification
        sa.Column("owner_cik", sa.String(16), nullable=False),
        sa.Column("owner_name", sa.Text(), nullable=False),
        sa.Column(
            "owner_role",
            sa.String(64),
            nullable=False,
            comment="comma-joined: officer,director,ten_percent_owner",
        ),
        sa.Column(
            "officer_title",
            sa.Text(),
            nullable=True,
            comment="raw officer title text, e.g. 'Chief Executive Officer'",
        ),
        # Transaction details
        sa.Column("transaction_date", sa.Date(), nullable=False, index=True),
        sa.Column(
            "transaction_code",
            sa.String(8),
            nullable=False,
            comment="SEC Form 4 transaction code: P=open-market buy, "
            "S=open-market sell, A=grant, F=tax withholding, "
            "M=option exercise, G=gift, etc.",
        ),
        sa.Column(
            "acquired_disposed",
            sa.String(1),
            nullable=False,
            comment="A=acquired (long), D=disposed (sold)",
        ),
        sa.Column("shares", sa.Numeric(18, 4), nullable=False),
        sa.Column(
            "price_per_share",
            sa.Numeric(18, 4),
            nullable=True,
            comment="NULL for non-cash transactions (grants, gifts)",
        ),
        sa.Column(
            "value_usd",
            sa.Numeric(18, 2),
            nullable=True,
            comment="shares * price; NULL when price is NULL",
        ),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "accession_no",
            "owner_cik",
            "transaction_date",
            "transaction_code",
            "shares",
            name="uq_insider_tx_natural_key",
        ),
    )
    # Composite index for the dominant read pattern: cluster detection
    # filters by (ticker, transaction_code in {P, S}, transaction_date range).
    op.create_index(
        "ix_insider_tx_ticker_code_date",
        "insider_transactions",
        ["ticker", "transaction_code", "transaction_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_insider_tx_ticker_code_date", table_name="insider_transactions"
    )
    op.drop_table("insider_transactions")
