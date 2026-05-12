"""research agent runs table

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-12

One row per autonomous research run kicked off via /api/research/ask.
The full conversation transcript (user prompt, assistant turns with
tool_use blocks, tool_result blocks, final answer) is stored in JSONB
so we can rebuild the agent's reasoning later — and so we can replay
it as fixtures for offline regression testing.

Token + cost accounting is denormalized onto the row so the registry
itself answers "what did this run cost" without re-parsing the
transcript.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.String(24),
            nullable=False,
            index=True,
            server_default="pending",
        ),
        sa.Column("final_answer", sa.Text(), nullable=True),
        sa.Column("transcript", postgresql.JSONB(), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(), nullable=False),
        sa.Column("n_turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "cache_read_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "cache_write_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "estimated_cost_usd",
            sa.Numeric(10, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("research_runs")
