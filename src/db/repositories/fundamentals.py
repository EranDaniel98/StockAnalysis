"""Postgres-backed FundamentalsRepository.

PIT-aware: queries pick the row whose [valid_from, valid_to) interval contains
`as_of`. Source precedence (most → least specific) is edgar_10q > edgar_10k >
yfinance_snapshot when multiple rows qualify.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.contracts.entities.fundamentals import (
    FundamentalPanel,
    FundamentalSnapshot,
    FundamentalsSource,
)
from src.db.models import Fundamental

# Higher rank = preferred when multiple sources are valid at the same as_of
_SOURCE_RANK: dict[str, int] = {
    "yfinance_snapshot": 1,
    "edgar_10k": 2,
    "edgar_10q": 3,
}


def _row_to_snapshot(row: Fundamental) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        ticker=row.ticker,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        source=row.source,  # type: ignore[arg-type]
        pe_ratio=row.pe_ratio,
        pb_ratio=row.pb_ratio,
        ps_ratio=row.ps_ratio,
        ev_to_ebitda=row.ev_to_ebitda,
        revenue=row.revenue,
        revenue_growth_yoy=row.revenue_growth_yoy,
        earnings_growth_yoy=row.earnings_growth_yoy,
        eps_diluted=row.eps_diluted,
        gross_margin=row.gross_margin,
        operating_margin=row.operating_margin,
        profit_margin=row.profit_margin,
        roe=row.roe,
        roa=row.roa,
        debt_to_equity=row.debt_to_equity,
        current_ratio=row.current_ratio,
        free_cash_flow=row.free_cash_flow,
        total_cash=row.total_cash,
        total_debt=row.total_debt,
        dividend_yield=row.dividend_yield,
        payout_ratio=row.payout_ratio,
        sector=row.sector,
        industry=row.industry,
        market_cap=row.market_cap,
        name=row.name,
    )


class PostgresFundamentalsRepository:
    """Implements src.contracts.protocols.repositories.FundamentalsRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_snapshot(
        self, ticker: str, as_of: datetime | None = None
    ) -> FundamentalSnapshot | None:
        as_of = as_of or datetime.now(timezone.utc)
        stmt = (
            select(Fundamental)
            .where(Fundamental.ticker == ticker)
            .where(Fundamental.valid_from <= as_of)
            .where(or_(Fundamental.valid_to.is_(None), Fundamental.valid_to > as_of))
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        if not rows:
            return None
        # Pick the highest-rank source. Ties broken by latest valid_from.
        best = max(rows, key=lambda r: (_SOURCE_RANK.get(r.source, 0), r.valid_from))
        return _row_to_snapshot(best)

    async def get_panel(
        self, tickers: list[str], as_of: datetime | None = None
    ) -> FundamentalPanel:
        as_of = as_of or datetime.now(timezone.utc)
        if not tickers:
            return FundamentalPanel(as_of=as_of, snapshots={})

        stmt = (
            select(Fundamental)
            .where(Fundamental.ticker.in_(tickers))
            .where(Fundamental.valid_from <= as_of)
            .where(or_(Fundamental.valid_to.is_(None), Fundamental.valid_to > as_of))
        )
        rows = (await self._session.execute(stmt)).scalars().all()

        # Bucket by ticker, pick best source per ticker
        by_ticker: dict[str, list[Fundamental]] = {}
        for r in rows:
            by_ticker.setdefault(r.ticker, []).append(r)

        snapshots: dict[str, FundamentalSnapshot] = {}
        for tkr, ticker_rows in by_ticker.items():
            best = max(
                ticker_rows,
                key=lambda r: (_SOURCE_RANK.get(r.source, 0), r.valid_from),
            )
            snapshots[tkr] = _row_to_snapshot(best)

        return FundamentalPanel(as_of=as_of, snapshots=snapshots)

    async def upsert(self, snapshot: FundamentalSnapshot) -> None:
        """Idempotent insert on (ticker, valid_from, source). Updates valid_to
        and all metric columns if the row already exists — this is how a daily
        yfinance snapshot job replaces the previous day's row."""
        values = {
            "ticker": snapshot.ticker,
            "valid_from": snapshot.valid_from,
            "source": snapshot.source,
            "valid_to": snapshot.valid_to,
            "pe_ratio": snapshot.pe_ratio,
            "pb_ratio": snapshot.pb_ratio,
            "ps_ratio": snapshot.ps_ratio,
            "ev_to_ebitda": snapshot.ev_to_ebitda,
            "revenue": snapshot.revenue,
            "revenue_growth_yoy": snapshot.revenue_growth_yoy,
            "earnings_growth_yoy": snapshot.earnings_growth_yoy,
            "eps_diluted": snapshot.eps_diluted,
            "gross_margin": snapshot.gross_margin,
            "operating_margin": snapshot.operating_margin,
            "profit_margin": snapshot.profit_margin,
            "roe": snapshot.roe,
            "roa": snapshot.roa,
            "debt_to_equity": snapshot.debt_to_equity,
            "current_ratio": snapshot.current_ratio,
            "free_cash_flow": snapshot.free_cash_flow,
            "total_cash": snapshot.total_cash,
            "total_debt": snapshot.total_debt,
            "dividend_yield": snapshot.dividend_yield,
            "payout_ratio": snapshot.payout_ratio,
            "sector": snapshot.sector,
            "industry": snapshot.industry,
            "market_cap": snapshot.market_cap,
            "name": snapshot.name,
        }
        stmt = pg_insert(Fundamental.__table__).values(**values)
        update_cols = {k: stmt.excluded[k] for k in values if k not in ("ticker", "valid_from", "source")}
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker", "valid_from", "source"],
            set_=update_cols,
        )
        await self._session.execute(stmt)
        await self._session.commit()
