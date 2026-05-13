"""insider narrative snapshots — proactive catalyst features

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-13

One row per (ticker, cluster_end_date) snapshot, computed offline.
Stores anchor-similarity features that the ML feature store can pull
into training sets. Computed once per cluster; idempotent re-runs
update the row in place rather than appending.

The anchor library lives in src/scoring/catalyst_anchors.py — keep the
``sim_*`` column list there in sync with the ANCHORS tuple. If anchors
are added, a new migration adds new ``sim_*`` columns rather than
changing existing ones (preserves backfilled history).

Lookahead safety: ``nearest_filing_date <= cluster_end_date`` is
enforced at the producer (backfill job), not the schema — schema can't
express that cross-column inequality cheaply.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Match the ANCHORS tuple in src/scoring/catalyst_anchors.py. Adding
# a new anchor → add a new column here in a follow-up migration; do
# not rename existing columns or backfilled rows become unreadable.
ANCHOR_KEYS = (
    "buyback_authorization",
    "guidance_raised",
    "product_approval",
    "acquisition_announced",
    "major_contract_win",
    "going_concern",
    "executive_departure",
    "litigation_settlement",
    "guidance_lowered",
    "restructuring_layoffs",
)


def upgrade() -> None:
    cols = [
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("cluster_end_date", sa.Date(), nullable=False),
        # Cluster metadata duplicated here so feature joins don't need
        # to re-query insider_transactions. Tiny denormalization, fixed
        # at snapshot time.
        sa.Column("insider_count", sa.Integer(), nullable=False),
        sa.Column("senior_count", sa.Integer(), nullable=False),
        sa.Column("cluster_value_usd", sa.Numeric(20, 2), nullable=False),
        # Nearest filing — NULL when there's no 8-K in 14d AND no
        # 10-Q/K in 90d. ``has_recent_8k`` is a tighter flag (8-K only
        # within 14d) so the ML model can distinguish "fresh news"
        # from "stale periodic report".
        sa.Column("has_recent_8k", sa.Boolean(), nullable=False),
        sa.Column("nearest_filing_form", sa.String(16), nullable=True),
        sa.Column("nearest_filing_date", sa.Date(), nullable=True),
        sa.Column("nearest_filing_accession", sa.String(32), nullable=True),
        sa.Column("days_to_filing", sa.Integer(), nullable=True),
        # Aggregates (NULL when no filing was found)
        sa.Column("top_bullish_anchor", sa.String(64), nullable=True),
        sa.Column("top_bearish_anchor", sa.String(64), nullable=True),
        sa.Column("top_bullish_sim", sa.Float(), nullable=True),
        sa.Column("top_bearish_sim", sa.Float(), nullable=True),
        sa.Column("narrative_skew", sa.Float(), nullable=True),
        # Provenance
        sa.Column("embedding_model", sa.String(64), nullable=False),
        sa.Column(
            "computed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    ]
    # 10 anchor-similarity columns, one per anchor key. Float (not
    # Numeric) because these are model outputs, not money — precision
    # beyond 6 sig figs is noise from the embedder.
    cols.extend(
        sa.Column(f"sim_{k}", sa.Float(), nullable=True)
        for k in ANCHOR_KEYS
    )

    op.create_table("insider_narrative_snapshots", *cols)

    # Idempotency: re-running the backfill for an already-seen cluster
    # UPDATEs in place rather than appending a duplicate row. The
    # unique constraint enforces it at the DB level.
    op.create_unique_constraint(
        "uq_narrative_snap_natural",
        "insider_narrative_snapshots",
        ["ticker", "cluster_end_date"],
    )
    op.create_index(
        "ix_narrative_snap_ticker_date",
        "insider_narrative_snapshots",
        ["ticker", "cluster_end_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_narrative_snap_ticker_date",
        table_name="insider_narrative_snapshots",
    )
    op.drop_constraint(
        "uq_narrative_snap_natural",
        "insider_narrative_snapshots",
        type_="unique",
    )
    op.drop_table("insider_narrative_snapshots")
