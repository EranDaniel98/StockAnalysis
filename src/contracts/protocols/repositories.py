"""Repository protocols. Each one abstracts a persistence concern that has
multiple plausible implementations (SQLite/Postgres, JSON file/Postgres JSONB,
yfinance/Parquet snapshot)."""

from datetime import datetime
from typing import Protocol, runtime_checkable

import pandas as pd

from src.contracts.entities.backtest import BacktestResult
from src.contracts.entities.factor import ICReport
from src.contracts.entities.fundamentals import FundamentalPanel, FundamentalSnapshot
from src.contracts.entities.recommendation import Recommendation
from src.contracts.entities.score import CompositeScore


@runtime_checkable
class PriceRepository(Protocol):
    """Read OHLCV history. Concrete impl: src/storage/parquet_ohlcv.py
    (Stream D), with SQLite fallback during Phase 0."""

    async def get_history(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Return DataFrame with columns [Open, High, Low, Close, Volume]
        and DatetimeIndex (tz-naive UTC). Empty DataFrame on no-data;
        raises DataError if the ticker is unknown."""
        ...

    async def get_batch(
        self,
        tickers: list[str],
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        """Parallel fetch. Returns only tickers that had data; the caller
        diffs the input list to find what's missing."""
        ...

    async def get_latest_price(self, ticker: str) -> float | None:
        """Latest known price. Used for realtime quotes; not cached."""
        ...


@runtime_checkable
class FundamentalsRepository(Protocol):
    """Read fundamental snapshots. Concrete impl: src/db/repositories/
    fundamentals.py (Postgres). Yfinance stays as the writer/source.

    EDGAR adds PIT history via Stream E (separate writer path)."""

    async def get_snapshot(
        self,
        ticker: str,
        as_of: datetime | None = None,
    ) -> FundamentalSnapshot | None:
        """Return the snapshot valid at `as_of` (None = now). Picks the most
        specific source available: edgar_10q > edgar_10k > yfinance_snapshot."""
        ...

    async def get_panel(
        self,
        tickers: list[str],
        as_of: datetime | None = None,
    ) -> FundamentalPanel:
        """Batch version."""
        ...

    async def upsert(self, snapshot: FundamentalSnapshot) -> None:
        ...


@runtime_checkable
class ScoreRepository(Protocol):
    """Persist composite scores from scan runs. Reads back for the future
    web layer's score history view + Phase 4 calibration tracker."""

    async def save_scan(
        self,
        run_id: str,
        strategy: str,
        as_of: datetime,
        scores: list[CompositeScore],
    ) -> None:
        ...

    async def get_scan(self, run_id: str) -> list[CompositeScore]:
        ...

    async def get_score_history(
        self,
        ticker: str,
        strategy: str,
        start: datetime,
        end: datetime,
    ) -> list[tuple[datetime, CompositeScore]]:
        ...


@runtime_checkable
class RecommendationRepository(Protocol):
    """Persist recommendations from scan + paper trade runs. Backs the
    paper_trading.db port (paper_recommendations table)."""

    async def save(self, recommendation: Recommendation, run_id: str) -> int:
        """Returns the persisted row id."""
        ...

    async def get_by_run(self, run_id: str) -> list[Recommendation]:
        ...


@runtime_checkable
class BacktestRepository(Protocol):
    """Persist full backtest result trees. Postgres backtest_runs table."""

    async def save(self, result: BacktestResult) -> int:
        """Returns the persisted row id."""
        ...

    async def get_by_id(self, run_id: int) -> BacktestResult | None:
        ...

    async def list_recent(
        self,
        strategy: str | None = None,
        limit: int = 20,
    ) -> list[BacktestResult]:
        ...


@runtime_checkable
class ICRepository(Protocol):
    """Persist alphalens diagnostic outputs. Postgres ic_diagnostics table."""

    async def save(self, report: ICReport) -> int:
        ...

    async def list_recent(
        self,
        factor_column: str | None = None,
        limit: int = 20,
    ) -> list[ICReport]:
        ...
