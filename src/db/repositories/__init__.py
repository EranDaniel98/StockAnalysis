"""Concrete Postgres-backed implementations of the repository Protocols
declared in src/contracts/protocols/repositories.py.

PriceRepository lives in src/storage/ (Parquet-backed via Stream D) — not
here, because OHLCV time-series scales better outside Postgres.
"""

from src.db.repositories.backtest import PostgresBacktestRepository
from src.db.repositories.fundamentals import PostgresFundamentalsRepository
from src.db.repositories.ic import PostgresICRepository
from src.db.repositories.recommendation import PostgresRecommendationRepository
from src.db.repositories.score import PostgresScoreRepository

__all__ = [
    "PostgresBacktestRepository",
    "PostgresFundamentalsRepository",
    "PostgresICRepository",
    "PostgresRecommendationRepository",
    "PostgresScoreRepository",
]
