"""SQLAlchemy 2.0 declarative models.

Schema corresponds 1:1 with Alembic migration 0001_initial.py. When changing
a model, generate a new revision via `alembic revision --autogenerate -m '...'`
and READ the autogen output — it misses pgvector columns, enum types, and
server defaults.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.session import Base


class Fundamental(Base):
    """Point-in-time fundamental snapshot.

    Primary key (ticker, valid_from, source) lets us layer multiple sources:
    EDGAR 10-Q rows are the truth post-filing, EDGAR 10-K supersedes annually,
    yfinance_snapshot fills the live-quote gap. Queries pick the most specific
    valid row at as_of.
    """

    __tablename__ = "fundamentals"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    """One of: yfinance_snapshot, edgar_10q, edgar_10k."""

    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # valuation
    pe_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pb_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ps_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ev_to_ebitda: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # growth
    revenue: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    revenue_growth_yoy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    earnings_growth_yoy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    eps_diluted: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # profitability
    gross_margin: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    operating_margin: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    profit_margin: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    roe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    roa: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # balance sheet / health
    debt_to_equity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    free_cash_flow: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_cash: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_debt: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # dividend
    dividend_yield: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    payout_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # categorical
    sector: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    market_cap: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)


class PaperRecommendation(Base):
    """Carryover from data/paper_trading.db `recommendations` table.

    Schema preserved row-for-row so scripts/migrate_paper_db.py is a direct
    copy. JSON sub-scores stored as text (sqlite-style) for migration
    fidelity; switch to JSONB in a follow-up once nothing reads the text.
    """

    __tablename__ = "paper_recommendations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    scan_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    composite_score: Mapped[float] = mapped_column(Float, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    sub_scores_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sector: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    earnings_in_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    submitted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skip_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    orders: Mapped[list["PaperOrder"]] = relationship(back_populates="recommendation")
    trades: Mapped[list["PaperTrade"]] = relationship(back_populates="recommendation")


class PaperOrder(Base):
    """Carryover from data/paper_trading.db `paper_orders` table."""

    __tablename__ = "paper_orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    recommendation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("paper_recommendations.id"), nullable=False, index=True
    )
    alpaca_order_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    client_order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    filled_qty: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    filled_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    filled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    recommendation: Mapped["PaperRecommendation"] = relationship(back_populates="orders")


class PaperTrade(Base):
    """Carryover from data/paper_trading.db `paper_trades` table."""

    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    recommendation_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("paper_recommendations.id"), nullable=True
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float] = mapped_column(Float, nullable=False)
    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hold_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pnl: Mapped[float] = mapped_column(Float, nullable=False)
    pnl_pct: Mapped[float] = mapped_column(Float, nullable=False)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    composite_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    """Free-text journal notes. Backed by alembic 0002. Edited via PATCH
    /api/trades/{id} from the /journal page."""

    recommendation: Mapped[Optional["PaperRecommendation"]] = relationship(back_populates="trades")


class BacktestRun(Base):
    """Header + denormalized JSONB body for a backtest result tree.

    The current code saves these as `data/backtest_results.json`; we mirror
    the same shape inside `result` so the parity test compares cleanly.
    """

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    universe_label: Mapped[str] = mapped_column(String(64), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Tier-level summary scalars surfaced for fast filtering / list views
    n_trades: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    oos_sharpe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    oos_total_return_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    oos_max_drawdown_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    """Full BacktestResult tree. Indexed via GIN in 0001_initial."""

    __table_args__ = (
        UniqueConstraint(
            "strategy",
            "universe_label",
            "window_start",
            "window_end",
            "created_at",
            name="uq_backtest_runs_window",
        ),
    )


class ScanRun(Base):
    """One scan invocation's top-N recommendations with full sub-score
    breakdown. Backs the future web layer's scan history view."""

    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scan_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    universe_label: Mapped[str] = mapped_column(String(64), nullable=False)
    budget: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    n_candidates: Mapped[int] = mapped_column(Integer, nullable=False)

    recommendations: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    """List of Recommendation.model_dump() entries with sub_scores + signals."""


class ICDiagnostic(Base):
    """One alphalens diagnostic run. Backs Phase 1's IC viewer."""

    __tablename__ = "ic_diagnostics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    factor_column: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    universe_label: Mapped[str] = mapped_column(String(64), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quantiles: Mapped[int] = mapped_column(Integer, nullable=False)
    n_observations: Mapped[int] = mapped_column(Integer, nullable=False)

    ic_mean: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ic_std: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ic_ir: Mapped[dict] = mapped_column(JSONB, nullable=False)
    quantile_spreads: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ModelVersion(Base):
    """One row per trained model. The pipeline picks the next version per
    ``model_name`` and writes a row after the joblib artifact is on disk.

    Schema: see alembic/versions/0003_model_versions.py. Metrics + params
    are intentionally JSONB so we can evolve the model + hyperparam set
    without schema churn — at the cost of typed access (we live with it).
    """

    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    train_window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    train_window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    factor_set: Mapped[str] = mapped_column(String(32), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "model_name", "version", name="uq_model_versions_name_version"
        ),
    )


class FactorSnapshot(Base):
    """RESERVED for Phase 4 ML feature store. Empty table at Phase 0 end.

    Schema: (ticker, as_of, factor_set) primary key. `values` and `z_scores`
    are JSONB maps. Indexed for time-series queries during model training.
    """

    __tablename__ = "factor_snapshots"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    factor_set: Mapped[str] = mapped_column(String(32), primary_key=True)
    values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    z_scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
