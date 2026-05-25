"""/api/stocks — per-ticker OHLC history for the chart panel.

The endpoint used to also surface the latest 5-engine recommendation row
for the requested ticker (read from ``scan_runs``). After the factor-pipeline
migration the FE stopped rendering that field; this route now only returns
OHLC bars. The legacy ``ScanResultItem`` / ``scan_run_id`` /
``scan_strategy`` / ``scan_timestamp`` fields are emitted as ``None`` for
schema compatibility until ``StockDetail`` is narrowed.

POST ``/api/stocks/{ticker}/analyze`` was deleted in the same change — its
synchronous full-analyzer chain was driven by ``src.scoring.service`` and
had no live FE consumer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import get_price_repo
from src.api.schemas.stock import OHLCBar, StockDetail
from src.storage.parquet_ohlcv import ParquetPriceRepository

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{ticker}", response_model=StockDetail)
async def get_stock_detail(
    ticker: str,
    history_days: int = Query(default=120, ge=5, le=730),
    price_repo: ParquetPriceRepository = Depends(get_price_repo),
) -> StockDetail:
    """Per-ticker OHLC history. ``history_days`` controls the lookback."""
    tu = ticker.strip().upper()
    if not tu:
        raise HTTPException(status_code=400, detail="empty ticker")

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=history_days)
    history: list[OHLCBar] = []
    try:
        df = await price_repo.get_history(tu, start=start, end=end)
        if df is not None and not df.empty:
            df = df.reset_index()
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
                        volume=(
                            int(r["Volume"])
                            if "Volume" in df.columns and r["Volume"] is not None
                            else None
                        ),
                    )
                )
    except Exception as e:
        logger.warning("price history fetch failed for %s: %s", tu, e)

    if not history:
        raise HTTPException(
            status_code=404,
            detail=f"no price data for ticker {tu!r}",
        )

    return StockDetail(ticker=tu, history=history)
