"""Bulk PIT lookup for backtests.

The backtest engine scores hundreds of (ticker, as_of-Monday) pairs in tight
loops. Hitting Postgres on every call would dominate wall-clock — instead we
pre-load every row for the ticker universe once, sort by ``valid_from``, and
serve in-memory.

Usage:

    loader = await FundamentalsPITLoader.from_repository(repo, tickers)
    fund_dict = loader.lookup_dict("AAPL", as_of, price=187.0, overlay=current_snap)
    # fund_dict is now an analyzer-shaped dict for AAPL at that historical Monday

Snapshot caching: ``from_json`` + ``to_json`` serialize the entire EDGAR PIT
panel to a single JSON file. Backtests use this to FREEZE the fundamentals
input alongside the snapshot's prices.parquet so a backtest run today and
tomorrow produce bit-identical results even if Postgres EDGAR rows have
been re-ingested or updated. See ``project_backtest_reproducibility`` memory.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.contracts.entities.fundamentals import FundamentalSnapshot

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

    def history(
        self, ticker: str, as_of: datetime, *, edgar_only: bool = True
    ) -> list[FundamentalSnapshot]:
        """All snapshots valid on-or-before ``as_of`` (oldest first).

        ``edgar_only`` keeps just 10-Q/10-K rows so callers computing
        quarter-over-quarter trends (Δmargin, FCF-TTM) step on clean
        filing boundaries rather than yfinance snapshot rows.
        """
        rows = self._by_ticker.get(ticker.upper())
        if not rows:
            return []
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        out = []
        for r in rows:
            vf = r.valid_from if r.valid_from.tzinfo else r.valid_from.replace(tzinfo=timezone.utc)
            if vf > as_of:
                continue
            if edgar_only and r.source not in ("edgar_10q", "edgar_10k"):
                continue
            out.append(r)
        return out

    def compute_eps_ttm(
        self, ticker: str, as_of: datetime
    ) -> float | None:
        """Trailing-12-month diluted EPS, point-in-time at ``as_of``.

        Uses the standard TTM roll:

            TTM = latest_annual_EPS (10-K, FY)
                  + Σ this-FY quarters reported since that 10-K
                  − Σ prior-FY matching quarters (the 10-Q ~365d earlier)

        This is correct where the old "sum the 4 most recent 10-Q rows" was not:
        there are only THREE 10-Qs per fiscal year (Q4 is reported in the 10-K),
        so summing four 10-Qs silently OMITS the Q4 quarter and spans ~5 quarters.
        The 10-K's annual figure supplies Q4; each post-10-K quarter is rolled in
        and its prior-year counterpart rolled out. 10-Q ``eps_diluted`` is the
        discrete quarter (parser ``_period_ok`` rejects the YTD double-report);
        10-K ``eps_diluted`` is the fiscal-year total.

        Returns None when there is no 10-K on/before as_of (can't anchor the year)
        or a needed prior-year quarter is missing — we don't fabricate a TTM.
        """
        rows = self._by_ticker.get(ticker.upper())
        if not rows:
            return None
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)

        def _vf(r):
            return r.valid_from if r.valid_from.tzinfo else r.valid_from.replace(tzinfo=timezone.utc)

        avail = [r for r in rows if _vf(r) <= as_of and r.eps_diluted is not None]
        tenk = [r for r in avail if r.source == "edgar_10k"]
        tenq = sorted((r for r in avail if r.source == "edgar_10q"), key=_vf)
        if not tenk:
            # No annual anchor — fall back to 4 most-recent 10-Q (legacy; omits Q4
            # but better than nothing for tickers with only quarterly coverage).
            return sum(r.eps_diluted for r in tenq[-4:]) if len(tenq) >= 4 else None

        anchor = max(tenk, key=_vf)            # latest fiscal-year 10-K
        fy_eps = float(anchor.eps_diluted)     # type: ignore[arg-type]
        anchor_vf = _vf(anchor)
        ttm = fy_eps
        for q in (r for r in tenq if _vf(r) > anchor_vf):   # quarters since the 10-K
            qd = _vf(q)
            prior = min(                                     # same fiscal quarter, ~1y earlier
                (p for p in tenq if 300 <= (qd - _vf(p)).days <= 430),
                key=lambda p: abs((qd - _vf(p)).days - 365), default=None,
            )
            if prior is None:
                return None                                  # can't match — don't guess
            ttm += float(q.eps_diluted) - float(prior.eps_diluted)  # type: ignore[arg-type]
        return ttm

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

    # ---------------------------------------------------------------
    # JSON serialization (snapshot caching for reproducible backtests)
    # ---------------------------------------------------------------
    # The EDGAR PIT panel is the only backtest input that isn't already
    # frozen with the snapshot. Without these methods, two backtests of
    # the same snapshot drift because Postgres EDGAR rows can be re-
    # ingested between runs. See project_backtest_reproducibility.
    #
    # Schema: list[dict] -- one row per FundamentalSnapshot. Dates
    # serialize as ISO-8601 strings; everything else passes through.

    _FIELDS: tuple[str, ...] = (
        "ticker", "source", "pe_ratio", "pb_ratio", "ps_ratio",
        "ev_to_ebitda", "revenue", "revenue_growth_yoy",
        "earnings_growth_yoy", "eps_diluted", "gross_margin",
        "operating_margin", "profit_margin", "roe", "roa",
        "debt_to_equity", "current_ratio", "free_cash_flow",
        "total_cash", "total_debt", "dividend_yield", "payout_ratio",
        "sector", "industry", "market_cap", "name",
    )

    def to_json(self, path: str | Path) -> None:
        """Serialize the full PIT panel to JSON. Used as a snapshot cache
        so future runs of the same snapshot can re-load instead of
        re-querying Postgres."""
        rows: list[dict[str, Any]] = []
        for snaps in self._by_ticker.values():
            for s in snaps:
                row: dict[str, Any] = {
                    "valid_from": s.valid_from.isoformat() if s.valid_from else None,
                    "valid_to": s.valid_to.isoformat() if s.valid_to else None,
                }
                for f in self._FIELDS:
                    row[f] = getattr(s, f, None)
                rows.append(row)
        Path(path).write_text(
            json.dumps(rows, default=str), encoding="utf-8",
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "FundamentalsPITLoader":
        """Inverse of ``to_json``. Reads the cached panel back into a
        loader. Raises FileNotFoundError if the cache doesn't exist."""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        snapshots: list[FundamentalSnapshot] = []
        for r in raw:
            vf_str = r.get("valid_from")
            vt_str = r.get("valid_to")
            kwargs: dict[str, Any] = {
                f: r.get(f) for f in cls._FIELDS
            }
            kwargs["valid_from"] = (
                datetime.fromisoformat(vf_str) if vf_str else None
            )
            kwargs["valid_to"] = (
                datetime.fromisoformat(vt_str) if vt_str else None
            )
            snapshots.append(FundamentalSnapshot(**kwargs))
        return cls(snapshots)


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
