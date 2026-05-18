"""Bulk PIT lookup for backtests.

The backtest engine scores hundreds of (ticker, as_of-Monday) pairs in tight
loops. Hitting Postgres on every call would dominate wall-clock — instead we
pre-load every row for the ticker universe once, sort by ``valid_from``, and
serve in-memory.

Usage:

    loader = await FundamentalsPITLoader.from_repository(repo, tickers)
    fund_dict = loader.lookup_dict("AAPL", as_of, price=187.0, overlay=current_snap)
    # fund_dict is now an analyzer-shaped dict for AAPL at that historical Monday
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.contracts.entities.fundamentals import FundamentalSnapshot
from src.scoring.fundamentals_adapter import snapshot_to_analyzer_dict

# Source-precedence: higher rank wins when several snapshots are valid at as_of.
# When lookup() sees both an EDGAR 10-Q and a yfinance snapshot covering as_of
# it picks 10-Q (rank 3) over 10-K (rank 2) over yfinance (rank 1). Adding a
# new source: pick a number BIGGER than the most-authoritative existing source
# you want to override (e.g. an audited XBRL feed → 4), or smaller if it's a
# permissible fallback. The lookup() sort uses (rank, valid_from) so source
# wins first; ties (same source from multiple filings) break on recency.
_SOURCE_RANK: dict[str, int] = {
    "yfinance_snapshot": 1,
    "edgar_10k": 2,
    "edgar_10q": 3,
}


class FundamentalsPITLoader:
    """In-memory PIT index over a list of ``FundamentalSnapshot`` rows.

    Construct via ``from_repository`` (async, queries Postgres) or directly
    from a pre-loaded list (useful in tests).
    """

    def __init__(self, snapshots: list[FundamentalSnapshot]) -> None:
        # Bucket by ticker, sort each bucket by valid_from (ascending).
        # We don't pre-filter by source — lookup picks the best source live so
        # we keep yfinance fallback rows usable when EDGAR is missing.
        by_ticker: dict[str, list[FundamentalSnapshot]] = {}
        for s in snapshots:
            by_ticker.setdefault(s.ticker.upper(), []).append(s)
        for tkr, rows in by_ticker.items():
            rows.sort(key=lambda r: r.valid_from)
        self._by_ticker = by_ticker

    @classmethod
    async def from_repository(
        cls,
        repo: Any,  # PostgresFundamentalsRepository — typed via duck since we only need the session
        tickers: list[str],
    ) -> "FundamentalsPITLoader":
        """Pull all rows for the ticker universe in one query, regardless of
        as_of. The query lives directly on the repo's session rather than
        through ``get_snapshot``/``get_panel`` which are as-of-specific."""
        from sqlalchemy import select

        from src.db.models import Fundamental

        if not tickers:
            return cls([])
        tickers_upper = [t.upper() for t in tickers]
        stmt = select(Fundamental).where(Fundamental.ticker.in_(tickers_upper))
        rows = (await repo._session.execute(stmt)).scalars().all()
        snapshots = [_row_to_snapshot(r) for r in rows]
        return cls(snapshots)

    def lookup(
        self, ticker: str, as_of: datetime
    ) -> FundamentalSnapshot | None:
        """Return the highest-rank snapshot valid at ``as_of`` for ticker.
        Returns None when ticker is uncovered or as_of predates the earliest
        filing."""
        rows = self._by_ticker.get(ticker.upper())
        if not rows:
            return None
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        valid: list[FundamentalSnapshot] = []
        for r in rows:
            vf = r.valid_from if r.valid_from.tzinfo else r.valid_from.replace(tzinfo=timezone.utc)
            if vf > as_of:
                continue
            vt = r.valid_to
            if vt is not None:
                vt_aware = vt if vt.tzinfo else vt.replace(tzinfo=timezone.utc)
                if vt_aware <= as_of:
                    continue
            valid.append(r)
        if not valid:
            return None
        # Highest source rank, then latest valid_from as tiebreak.
        return max(valid, key=lambda r: (_SOURCE_RANK.get(r.source, 0), r.valid_from))

    def compute_eps_ttm(
        self, ticker: str, as_of: datetime
    ) -> float | None:
        """Trailing-12-month EPS — sum of diluted EPS across the 4 most recent
        edgar_10q rows valid on-or-before as_of.

        Returns None when fewer than 4 quarters are available or any of them
        is missing diluted EPS. The adapter falls back to "no pe_trailing"
        rather than fabricate a TTM from a partial year.

        10-K rows are excluded — they report annual EPS, which would
        double-count with the quarterly sum. Pure 10-K coverage (rare for
        recent filings) means callers see no TTM.
        """
        rows = self._by_ticker.get(ticker.upper())
        if not rows:
            return None
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        quarterly: list[FundamentalSnapshot] = []
        for r in rows:
            if r.source != "edgar_10q":
                continue
            vf = r.valid_from if r.valid_from.tzinfo else r.valid_from.replace(tzinfo=timezone.utc)
            if vf > as_of:
                continue
            if r.eps_diluted is None:
                continue
            quarterly.append(r)
        if len(quarterly) < 4:
            return None
        last_four = sorted(quarterly, key=lambda r: r.valid_from)[-4:]
        return sum(r.eps_diluted for r in last_four)  # type: ignore[misc]

    def lookup_dict(
        self,
        ticker: str,
        as_of: datetime,
        *,
        price: float | None = None,
        overlay: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Same as ``lookup`` but returns the analyzer-shaped dict. Returns
        the overlay alone (or empty) when no PIT row covers as_of.

        Auto-injects ``eps_ttm`` into the overlay when 4 quarters of EDGAR
        EPS are available — so the adapter computes PE from real TTM rather
        than the latest-quarter × 4 heuristic. Caller-supplied eps_ttm in
        the overlay wins (lets tests pin a specific value).
        """
        snap = self.lookup(ticker, as_of)
        merged_overlay: dict[str, Any] = dict(overlay) if overlay else {}
        if "eps_ttm" not in merged_overlay:
            ttm = self.compute_eps_ttm(ticker, as_of)
            if ttm is not None:
                merged_overlay["eps_ttm"] = ttm
        return snapshot_to_analyzer_dict(snap, price=price, overlay=merged_overlay)

    def coverage(self) -> dict[str, int]:
        """Per-ticker row count. Useful for sanity-checking the universe at
        backtest setup time — ``{t: 0 for t in universe if t not in cov}``
        flags missing tickers."""
        return {t: len(rows) for t, rows in self._by_ticker.items()}

    def lookup_sector(self, ticker: str, as_of: datetime) -> str | None:
        """Return the sector string for ticker at as_of, or None when uncovered.

        Sector is carried on every FundamentalSnapshot row but rarely changes
        within a ticker's history; this is a thin wrapper that surfaces it
        without forcing callers to reach through the full snapshot. Used by
        the factor-pipeline sector-cap selector.
        """
        snap = self.lookup(ticker, as_of)
        return snap.sector if snap is not None else None

    @property
    def tickers(self) -> set[str]:
        return set(self._by_ticker.keys())


def _row_to_snapshot(row: Any) -> FundamentalSnapshot:
    """Inline copy of repositories/fundamentals._row_to_snapshot to avoid the
    circular import (repository → loader → repository). Keep these aligned —
    if FundamentalSnapshot gains a field, both translation sites need it."""
    return FundamentalSnapshot(
        ticker=row.ticker,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        source=row.source,
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
