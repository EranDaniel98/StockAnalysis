"""initial schema: fundamentals, paper_*, backtest_runs, scan_runs, ic_diagnostics, factor_snapshots

Revision ID: 0001
Revises:
Create Date: 2026-05-11

Creates the full Phase 0 schema in one shot. Hand-written (not autogen) so
the JSONB columns, the `vector` extension reservation, and the GIN index
on backtest_runs.result are all explicit.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- extensions ----
    # Reserve pgvector for Phase 5 embeddings. Empty until then; loading the
    # extension up-front keeps the schema migration linear.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # ---- fundamentals (PIT) ----
    op.create_table(
        "fundamentals",
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pe_ratio", sa.Float, nullable=True),
        sa.Column("pb_ratio", sa.Float, nullable=True),
        sa.Column("ps_ratio", sa.Float, nullable=True),
        sa.Column("ev_to_ebitda", sa.Float, nullable=True),
        sa.Column("revenue", sa.Float, nullable=True),
        sa.Column("revenue_growth_yoy", sa.Float, nullable=True),
        sa.Column("earnings_growth_yoy", sa.Float, nullable=True),
        sa.Column("eps_diluted", sa.Float, nullable=True),
        sa.Column("gross_margin", sa.Float, nullable=True),
        sa.Column("operating_margin", sa.Float, nullable=True),
        sa.Column("profit_margin", sa.Float, nullable=True),
        sa.Column("roe", sa.Float, nullable=True),
        sa.Column("roa", sa.Float, nullable=True),
        sa.Column("debt_to_equity", sa.Float, nullable=True),
        sa.Column("current_ratio", sa.Float, nullable=True),
        sa.Column("free_cash_flow", sa.Float, nullable=True),
        sa.Column("total_cash", sa.Float, nullable=True),
        sa.Column("total_debt", sa.Float, nullable=True),
        sa.Column("dividend_yield", sa.Float, nullable=True),
        sa.Column("payout_ratio", sa.Float, nullable=True),
        sa.Column("sector", sa.String(64), nullable=True),
        sa.Column("industry", sa.String(128), nullable=True),
        sa.Column("market_cap", sa.Float, nullable=True),
        sa.Column("name", sa.String(256), nullable=True),
        sa.PrimaryKeyConstraint("ticker", "valid_from", "source"),
    )
    op.create_index(
        "ix_fundamentals_ticker_valid_from",
        "fundamentals",
        ["ticker", "valid_from"],
    )

    # ---- paper trading (carryover from data/paper_trading.db) ----
    op.create_table(
        "paper_recommendations",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("scan_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("strategy", sa.String(64), nullable=False),
        sa.Column("composite_score", sa.Float, nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("sub_scores_json", sa.Text, nullable=True),
        sa.Column("entry_price", sa.Float, nullable=True),
        sa.Column("stop_loss", sa.Float, nullable=True),
        sa.Column("take_profit", sa.Float, nullable=True),
        sa.Column("sector", sa.String(64), nullable=True),
        sa.Column("earnings_in_days", sa.Integer, nullable=True),
        sa.Column("submitted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skip_reason", sa.Text, nullable=True),
    )
    op.create_index("ix_paper_rec_ticker", "paper_recommendations", ["ticker"])
    op.create_index(
        "ix_paper_rec_scan_timestamp", "paper_recommendations", ["scan_timestamp"]
    )

    op.create_table(
        "paper_orders",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "recommendation_id",
            sa.BigInteger,
            sa.ForeignKey("paper_recommendations.id"),
            nullable=False,
        ),
        sa.Column("alpaca_order_id", sa.String(64), nullable=False, unique=True),
        sa.Column("client_order_id", sa.String(64), nullable=True),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("qty", sa.Float, nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("filled_qty", sa.Float, nullable=False, server_default="0"),
        sa.Column("filled_price", sa.Float, nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("take_profit", sa.Float, nullable=True),
        sa.Column("stop_loss", sa.Float, nullable=True),
    )
    op.create_index("ix_paper_orders_rec", "paper_orders", ["recommendation_id"])

    op.create_table(
        "paper_trades",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "recommendation_id",
            sa.BigInteger,
            sa.ForeignKey("paper_recommendations.id"),
            nullable=True,
        ),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("qty", sa.Float, nullable=False),
        sa.Column("entry_price", sa.Float, nullable=False),
        sa.Column("exit_price", sa.Float, nullable=False),
        sa.Column("entry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hold_days", sa.Integer, nullable=True),
        sa.Column("pnl", sa.Float, nullable=False),
        sa.Column("pnl_pct", sa.Float, nullable=False),
        sa.Column("exit_reason", sa.String(32), nullable=True),
        sa.Column("composite_score", sa.Float, nullable=True),
    )
    op.create_index("ix_paper_trades_ticker", "paper_trades", ["ticker"])
    op.create_index("ix_paper_trades_score", "paper_trades", ["composite_score"])

    # ---- backtest_runs ----
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("strategy", sa.String(64), nullable=False),
        sa.Column("universe_label", sa.String(64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("n_trades", sa.Integer, nullable=True),
        sa.Column("oos_sharpe", sa.Float, nullable=True),
        sa.Column("oos_total_return_pct", sa.Float, nullable=True),
        sa.Column("oos_max_drawdown_pct", sa.Float, nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.UniqueConstraint(
            "strategy",
            "universe_label",
            "window_start",
            "window_end",
            "created_at",
            name="uq_backtest_runs_window",
        ),
    )
    op.create_index("ix_backtest_runs_strategy", "backtest_runs", ["strategy"])
    # GIN index on the JSONB result for ad-hoc filtering / web list views
    op.execute(
        "CREATE INDEX ix_backtest_runs_result_gin "
        "ON backtest_runs USING GIN (result jsonb_path_ops);"
    )

    # ---- scan_runs ----
    op.create_table(
        "scan_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("strategy", sa.String(64), nullable=False),
        sa.Column("scan_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("universe_label", sa.String(64), nullable=False),
        sa.Column("budget", sa.Float, nullable=True),
        sa.Column("n_candidates", sa.Integer, nullable=False),
        sa.Column("recommendations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.create_index("ix_scan_runs_strategy", "scan_runs", ["strategy"])
    op.create_index(
        "ix_scan_runs_scan_timestamp", "scan_runs", ["scan_timestamp"]
    )

    # ---- ic_diagnostics ----
    op.create_table(
        "ic_diagnostics",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("factor_column", sa.String(32), nullable=False),
        sa.Column("universe_label", sa.String(64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quantiles", sa.Integer, nullable=False),
        sa.Column("n_observations", sa.Integer, nullable=False),
        sa.Column("ic_mean", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ic_std", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ic_ir", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "quantile_spreads", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("verdict", sa.Text, nullable=False, server_default=""),
    )
    op.create_index("ix_ic_factor", "ic_diagnostics", ["factor_column"])

    # ---- factor_snapshots (Phase 4 reserved) ----
    op.create_table(
        "factor_snapshots",
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("factor_set", sa.String(32), nullable=False),
        sa.Column("values", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("z_scores", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("ticker", "as_of", "factor_set"),
    )
    op.create_index(
        "ix_factor_snapshots_as_of_factor_set",
        "factor_snapshots",
        ["as_of", "factor_set"],
    )


def downgrade() -> None:
    op.drop_table("factor_snapshots")
    op.drop_table("ic_diagnostics")
    op.drop_table("scan_runs")
    op.execute("DROP INDEX IF EXISTS ix_backtest_runs_result_gin;")
    op.drop_table("backtest_runs")
    op.drop_table("paper_trades")
    op.drop_table("paper_orders")
    op.drop_table("paper_recommendations")
    op.drop_table("fundamentals")
    # Keep `vector` extension installed — dropping it would cascade in Phase 5
