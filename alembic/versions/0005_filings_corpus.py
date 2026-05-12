"""filings RAG corpus table

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-12

pgvector extension was reserved by 0001_initial; this migration creates
the ``filings_corpus`` table that the Phase 5.2 RAG agent searches.

Embedding dimension is 384 (sentence-transformers/all-MiniLM-L6-v2).
We use plain ``vector`` rather than ``halfvec`` since the user's
project conventions say halfvec only above 2000 dims.

HNSW index on the embedding column for k-NN. M=16 / ef_construction=64
are the pgvector defaults — good enough for tens of thousands of rows.
Cosine distance opclass (``vector_cosine_ops``) because we'll be
querying with cosine-normalized sentence embeddings.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


EMBEDDING_DIM = 384


def upgrade() -> None:
    # Extension is already installed by 0001_initial. Re-running CREATE
    # IF NOT EXISTS is cheap and makes this migration self-contained
    # for anyone who skipped 0001 for some reason.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.execute(
        f"""
        CREATE TABLE filings_corpus (
            id              BIGSERIAL PRIMARY KEY,
            ticker          VARCHAR(16)  NOT NULL,
            cik             INTEGER      NOT NULL,
            form            VARCHAR(16)  NOT NULL,
            accession_no    VARCHAR(32)  NOT NULL,
            filing_date     DATE         NOT NULL,
            primary_doc     TEXT         NOT NULL,
            chunk_index     INTEGER      NOT NULL,
            chunk_text      TEXT         NOT NULL,
            chunk_tokens    INTEGER      NOT NULL,
            embedding       vector({EMBEDDING_DIM}) NOT NULL,
            embedding_model VARCHAR(64)  NOT NULL,
            ingested_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
        """
    )

    op.create_index(
        "ix_filings_corpus_ticker_filing_date",
        "filings_corpus",
        ["ticker", "filing_date"],
    )
    op.create_index(
        "ix_filings_corpus_form",
        "filings_corpus",
        ["form"],
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_filings_corpus_chunk
        ON filings_corpus (accession_no, chunk_index);
        """
    )
    op.execute(
        """
        CREATE INDEX ix_filings_corpus_embedding_hnsw
        ON filings_corpus
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS filings_corpus;")
