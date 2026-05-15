"""SQLAlchemy 2.0 declarative models.

Schema corresponds 1:1 with Alembic migration 0001_initial.py. When changing
a model, generate a new revision via `alembic revision --autogenerate -m '...'`
and READ the autogen output — it misses pgvector columns, enum types, and
server defaults.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from pgvector.sqlalchemy import Vector
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
    # Idempotency key; UNIQUE NOT NULL so a retry that bypasses Alpaca's
    # duplicate-id check still can't double-write the orders table.
    # Pre-0010 rows were backfilled with `legacy-<id>` to satisfy NOT NULL.
    client_order_id: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )
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


class ResearchRun(Base):
    """One autonomous research run.

    Persists the full Anthropic message transcript (user prompt, assistant
    turns with tool_use blocks, tool_result blocks, final answer) plus
    token/cost accounting denormalized for cheap querying. See alembic
    0004 for the column-level commentary.

    ``status`` lifecycle: pending → running → (complete | failed |
    budget_exceeded). Updated in-place as the orchestrator progresses.
    """

    __tablename__ = "research_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending", index=True
    )
    final_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    tool_calls: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    n_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(
        Numeric(10, 6), nullable=False, default=0
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class FilingCorpusChunk(Base):
    """One chunk of an EDGAR filing — the unit the RAG agent searches.

    Embeddings are stored as ``vector(384)`` (alembic 0005). The Python
    ORM column declares them via ``pgvector.sqlalchemy.Vector`` so
    SQLAlchemy returns numpy arrays on read.

    Uniqueness: ``(accession_no, chunk_index)``. Re-ingesting the same
    filing replaces the chunks rather than duplicating them.
    """

    __tablename__ = "filings_corpus"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    cik: Mapped[int] = mapped_column(Integer, nullable=False)
    form: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    accession_no: Mapped[str] = mapped_column(String(32), nullable=False)
    filing_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    primary_doc: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "accession_no", "chunk_index", name="uq_filings_corpus_chunk"
        ),
    )


class MonitoredTicker(Base):
    """Per-ticker watermark for the background filing-event monitor.

    ``last_seen_accession_no`` is the EDGAR accession the monitor most
    recently observed. On first poll for a ticker, we set this without
    firing notifications so the user doesn't get buried in historical
    filings.
    """

    __tablename__ = "monitored_tickers"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    last_seen_accession_no: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
    last_polled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class FilingNotification(Base):
    """One row per new filing the monitor surfaced. Stays in the DB so
    the /research/feed page is a straight read on load and only uses SSE
    for incremental updates.

    ``research_run_id`` links to a follow-up agent summarization, if the
    user triggered one. ``summary`` caches the final answer so we don't
    re-fetch the run row to display the headline."""

    __tablename__ = "filing_notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    form: Mapped[str] = mapped_column(String(16), nullable=False)
    accession_no: Mapped[str] = mapped_column(String(32), nullable=False)
    filing_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    primary_document: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True
    )
    research_run_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("research_runs.id", ondelete="SET NULL"), nullable=True
    )
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "ticker", "accession_no", name="uq_filing_notifications_ticker_accn"
        ),
    )


class InsiderTransaction(Base):
    """One non-derivative transaction reported on a Form 4 filing.

    Backs the ``insider_flow`` analyzer's cluster-detection query path:
    "all open-market buys (transaction_code='P') for ticker X over the
    last N days." Indexed on (ticker, transaction_code, transaction_date)
    to make that query a single index seek.

    Why one row per (transaction × owner): joint filings (rare but
    legal) list multiple reporting owners against the same transaction
    block. Replicating per-owner keeps the cluster-count math (a key
    component of the CMP-2012 opportunistic-cluster filter) trivial —
    a count of distinct owner_cik values in the window is the answer.

    The composite uniqueness on (accession, owner_cik, transaction_date,
    transaction_code, shares) prevents an amended Form 4/A from double-
    counting on re-ingestion of the same filing.
    """

    __tablename__ = "insider_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Issuer identification
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    issuer_cik: Mapped[str] = mapped_column(String(16), nullable=False)
    issuer_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Filing metadata
    accession_no: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    filing_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    # Insider identification
    owner_cik: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_name: Mapped[str] = mapped_column(Text, nullable=False)
    owner_role: Mapped[str] = mapped_column(String(64), nullable=False)
    """Comma-joined role flags: officer,director,ten_percent_owner."""
    officer_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Transaction details
    transaction_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    transaction_code: Mapped[str] = mapped_column(String(8), nullable=False)
    """SEC Form 4 transaction codes — see migration 0007 for the legend."""
    acquired_disposed: Mapped[str] = mapped_column(String(1), nullable=False)
    """A=acquired (long), D=disposed (sold)."""
    shares: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    price_per_share: Mapped[Optional[float]] = mapped_column(
        Numeric(18, 4), nullable=True
    )
    value_usd: Mapped[Optional[float]] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "accession_no",
            "owner_cik",
            "transaction_date",
            "transaction_code",
            "shares",
            name="uq_insider_tx_natural_key",
        ),
    )


class InsiderNarrativeSnapshot(Base):
    """One row per (ticker, cluster_end_date) snapshot — proactive
    catalyst-narrative features. Populated by the offline backfill
    job (``scripts/backfill_insider_narrative.py``), consumed by the
    Phase 4 ML feature store.

    Each ``sim_*`` column is the max cosine similarity between any
    chunk of the nearest filing (8-K preferred, 10-Q/K fallback) and
    one anchor phrase from ``src/scoring/catalyst_anchors.py``. The
    ``narrative_skew`` field is ``top_bullish_sim - top_bearish_sim``,
    pre-computed at snapshot time so feature joins are cheap.

    Lookahead safety: the producer enforces
    ``nearest_filing_date <= cluster_end_date``; the schema can't
    express that across columns cheaply.
    """

    __tablename__ = "insider_narrative_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    cluster_end_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    # Cluster metadata (denormalized so feature joins are single-table)
    insider_count: Mapped[int] = mapped_column(Integer, nullable=False)
    senior_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cluster_value_usd: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    # Nearest filing — NULL when no filing was found in either window
    has_recent_8k: Mapped[bool] = mapped_column(Boolean, nullable=False)
    nearest_filing_form: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    nearest_filing_date: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    nearest_filing_accession: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    days_to_filing: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Aggregates (NULL when no filing → no anchor sims computed)
    top_bullish_anchor: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    top_bearish_anchor: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    top_bullish_sim: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    top_bearish_sim: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    narrative_skew: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Per-anchor cosines (10 columns). Order matches catalyst_anchors.ANCHORS.
    sim_buyback_authorization: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sim_guidance_raised: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sim_product_approval: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sim_acquisition_announced: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sim_major_contract_win: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sim_going_concern: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sim_executive_departure: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sim_litigation_settlement: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sim_guidance_lowered: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sim_restructuring_layoffs: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Provenance
    embedding_model: Mapped[str] = mapped_column(String(64), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "ticker", "cluster_end_date", name="uq_narrative_snap_natural"
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


class ShortInterest(Base):
    """Daily short-sale volume from FINRA's Reg SHO CNMS files.

    One row per (ticker, settlement_date). FINRA publishes a single
    pipe-delimited file per trading day at
    ``https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt``
    listing per-symbol short volume + total volume across the
    consolidated market.

    Note: this is *daily short-sale volume*, NOT biweekly
    short-interest reportable positions. The loader rolls 30 daily
    rows into a synthetic short-interest series the analyzer reads —
    the rate-of-change semantics the analyzer uses translate
    cleanly. Per ``loader.load_short_interest_rows`` we set:

      ``short_interest_shares = sum_over_30d(short_volume)``
      ``avg_daily_volume = mean_over_30d(total_volume)``

    The 30-day cumulative captures sustained short pressure rather
    than one-day spikes, and the avg_daily_volume normalizer lets the
    analyzer's days-to-cover derivation work on the same scale as
    biweekly FINRA short-interest reports.
    """

    __tablename__ = "short_interest"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    settlement_date: Mapped[date] = mapped_column(Date, nullable=False)
    short_volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    short_exempt_volume: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "ticker", "settlement_date", name="uq_short_interest_ticker_date"
        ),
    )
