"""/api/stocks — per-ticker deep-dive (trade plan + sub-scores + chart history).

This endpoint stitches together two existing stores:

  - ``scan_runs`` for the last engine recommendation row matching the ticker
    (so we can render the same trade plan the user already saw in /scan),
  - ParquetPriceRepository for an OHLC slice the frontend overlays
    entry/stop/target lines on.

No on-demand re-scan — that's an expensive 30s pipeline and the cost
isn't justified for the deep-dive use case. If the scoring is stale,
the user can re-run /scan; this endpoint only narrates what the engine
already produced.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db_session, get_price_repo
from src.api.schemas.scan import ScanResultItem
from src.api.schemas.stock import OHLCBar, StockDetail
from src.db.models import ScanRun
from src.storage.parquet_ohlcv import ParquetPriceRepository

logger = logging.getLogger(__name__)
router = APIRouter()


def _extract_recommendation(
    recs: list[dict], ticker_upper: str
) -> dict | None:
    """Find the first row matching the ticker. Recs are stored newest-first
    inside each scan_run, but the ticker order is by composite_score, so
    we still need to walk all rows."""
    for r in recs:
        t = r.get("ticker")
        if isinstance(t, str) and t.upper() == ticker_upper:
            return r
    return None


@router.get("/{ticker}", response_model=StockDetail)
async def get_stock_detail(
    ticker: str,
    history_days: int = Query(default=120, ge=5, le=730),
    db: AsyncSession = Depends(get_db_session),
    price_repo: ParquetPriceRepository = Depends(get_price_repo),
) -> StockDetail:
    """Per-ticker deep-dive: latest stored recommendation + OHLC history.

    ``history_days`` controls how many calendar days of price data come
    back. The frontend overlays entry/stop/target lines on this slice.
    """
    tu = ticker.strip().upper()
    if not tu:
        raise HTTPException(status_code=400, detail="empty ticker")

    # Walk scan_runs newest-first until we find one containing this ticker.
    # In practice the latest scan_run almost always has it (the user is
    # asking about a stock they just saw on /scan); the loop guards against
    # tickers that fell out of the universe in the latest run.
    stmt = (
        select(ScanRun)
        .order_by(desc(ScanRun.scan_timestamp))
        .limit(50)
    )
    rows = (await db.execute(stmt)).scalars().all()

    rec: dict | None = None
    matched_row: ScanRun | None = None
    for row in rows:
        rec = _extract_recommendation(row.recommendations or [], tu)
        if rec is not None:
            matched_row = row
            break

    # Build OHLC slice (best-effort — Parquet may not have this ticker yet).
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=history_days)
    history: list[OHLCBar] = []
    try:
        df = await price_repo.get_history(tu, start=start, end=end)
        if df is not None and not df.empty:
            df = df.reset_index()
            # Column name can be 'Date' or 'date' depending on writer
            date_col = "Date" if "Date" in df.columns else "date"
            for _, r in df.iterrows():
                history.append(
                    OHLCBar(
                        date=r[date_col].date()
                        if hasattr(r[date_col], "date")
                        else r[date_col],
                        open=float(r["Open"]),
                        high=float(r["High"]),
                        low=float(r["Low"]),
                        close=float(r["Close"]),
                        volume=int(r["Volume"]) if "Volume" in df.columns and r["Volume"] is not None else None,
                    )
                )
    except Exception as e:
        # Don't block the response on a price-data miss; the trade plan
        # is the load-bearing part of this view.
        logger.debug("price history fetch failed for %s: %s", tu, e)

    if rec is None and not history:
        raise HTTPException(
            status_code=404,
            detail=f"no scan history or price data for ticker {tu!r}",
        )

    return StockDetail(
        ticker=tu,
        latest_recommendation=ScanResultItem.model_validate(rec) if rec else None,
        scan_run_id=matched_row.universe_label if matched_row else None,
        scan_strategy=matched_row.strategy if matched_row else None,
        scan_timestamp=matched_row.scan_timestamp if matched_row else None,
        history=history,
    )
