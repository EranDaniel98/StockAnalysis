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

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_config, get_db_session, get_price_repo
from src.api.schemas.scan import ScanResultItem
from src.api.schemas.stock import OHLCBar, StockDetail
from src.config_loader import Config
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


def _analyze_single_ticker(
    ticker: str, config: Config, strategy_name: str
) -> dict | None:
    """Synchronous worker: full analyzer chain on one ticker. Returns the
    composite/recommendation dict or None if data fetch failed."""
    from src.data.cache import DataCache
    from src.data.fetcher import DataFetcher
    from src.data.fundamentals import FundamentalsFetcher
    from src.scoring.service import analyze_and_score

    strategy = config.get_strategy(strategy_name)
    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5
        ),
        force_fresh=False,
    )
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    price_map = fetcher.fetch_batch([ticker])
    fund_map = fund_fetcher.fetch_batch([ticker])
    if not price_map.get(ticker) is not None and not price_map:
        return None

    recs = analyze_and_score(price_map, fund_map, config, strategy)
    if not recs:
        return None
    # analyze_and_score returns a list ranked by score; for a single ticker
    # we just want the one row, regardless of action.
    for r in recs:
        if r.get("ticker", "").upper() == ticker.upper():
            return r
    return recs[0]


@router.post("/{ticker}/analyze", response_model=ScanResultItem)
async def analyze_ticker(
    ticker: str,
    strategy: str = Query(default="swing_trading"),
    config: Config = Depends(get_config),
) -> ScanResultItem:
    """Run the full analyzer chain on a single ticker on-demand.

    Used by the web ticker-search bar so users can pull up a deep-dive on
    any ticker, not just ones present in the latest scan_run. Returns a
    ``ScanResultItem`` shaped identically to the rows produced by
    ``/api/scans`` — same composite score, sub-scores, signals, risk
    plan, and reasoning. ~3–8 s per call (price + fundamentals fetch
    dominate; both are cached).
    """
    tu = ticker.strip().upper()
    if not tu:
        raise HTTPException(status_code=400, detail="empty ticker")
    try:
        rec = await asyncio.to_thread(
            _analyze_single_ticker, tu, config, strategy
        )
    except KeyError:
        raise HTTPException(status_code=400, detail=f"unknown strategy {strategy!r}")
    if rec is None:
        raise HTTPException(
            status_code=404,
            detail=f"no price/fundamental data available for ticker {tu!r}",
        )
    return ScanResultItem.model_validate(rec)
