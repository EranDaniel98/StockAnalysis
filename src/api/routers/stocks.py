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

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.dependencies import get_price_repo
from src.api.schemas.stock import OHLCBar, StockDetail
from src.storage.parquet_ohlcv import ParquetPriceRepository

logger = logging.getLogger(__name__)
router = APIRouter()


class TickerFactors(BaseModel):
    """On-demand factor breakdown for ANY universe ticker — including names the
    daily picks filtered out (e.g. recent spin-offs). Lets the per-stock page
    show why a ticker ranks where it does even when it never made the basket."""
    ticker: str
    as_of: date
    in_universe: bool
    picked_today: bool = False
    universe_size: int = 0
    composite_rank: Optional[int] = None
    composite_z: Optional[float] = None
    momentum_rank: Optional[int] = None
    quality_rank: Optional[int] = None
    value_rank: Optional[int] = None
    pead_rank: Optional[int] = None
    edgar_rows: int = 0
    thin_fundamentals: bool = False  # few EDGAR quarters -> quality/value unreliable
    note: Optional[str] = None


# Cache the (expensive) full unfiltered ranking per as_of date so the first
# /factors call of the day pays ~1-2 min and the rest are instant lookups.
# Lock serializes concurrent first-callers so we compute once, not N times.
_FACTORS_THIN_ROWS = 8  # < 2 years of quarters -> quality/value unreliable
_factors_cache: dict[date, object] = {}
_factors_lock = asyncio.Lock()


async def _full_ranking(as_of: date):
    res = _factors_cache.get(as_of)
    if res is not None:
        return res
    async with _factors_lock:
        res = _factors_cache.get(as_of)
        if res is not None:
            return res
        import pandas as pd

        from src.factors.pipeline import run_factor_picks
        logger.info("Computing on-demand full factor ranking for %s...", as_of)
        res = await asyncio.to_thread(
            run_factor_picks,
            as_of=pd.Timestamp(as_of),
            top_n=24,
            include_pead=True,
            sector_neutral_quality=True,
            min_history_days=None,  # include gate-excluded names (spin-offs)
            hysteresis_bonus=0.0,
        )
        _factors_cache.clear()  # only today's ranking is useful; bound memory
        _factors_cache[as_of] = res
        return res


def _in_todays_basket(ticker: str, as_of: date) -> bool:
    """True if ``ticker`` is in the actual daily picks file for ``as_of``."""
    import json
    from pathlib import Path
    p = Path("data/daily_picks") / f"{as_of.isoformat()}.json"
    if not p.exists():
        return False
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return ticker.upper() in {
        (x.get("ticker") or "").upper() for x in (payload.get("picks") or [])
    }


@router.get("/{ticker}/factors", response_model=TickerFactors)
async def get_ticker_factors(ticker: str) -> TickerFactors:
    """Compute (cached per day) the ticker's factor ranks across the universe,
    even if it wasn't picked. First call of the day takes ~1-2 min."""
    import pandas as pd

    tu = ticker.strip().upper()
    if not tu:
        raise HTTPException(status_code=400, detail="empty ticker")
    res = await _full_ranking(datetime.now(timezone.utc).date())
    comp = res.composite
    as_of_d = res.as_of.date() if hasattr(res.as_of, "date") else res.as_of
    edgar_rows = int(res.per_ticker_coverage.get(tu, 0))
    row = comp[comp["ticker"] == tu] if not comp.empty else comp
    if row.empty:
        return TickerFactors(
            ticker=tu, as_of=as_of_d, in_universe=False,
            universe_size=len(comp), edgar_rows=edgar_rows,
            note="Not in the scored S&P 500 PIT universe for this date "
                 "(or no price history / too few overlapping factors).",
        )
    r = row.iloc[0]

    def _i(col):
        return int(r[col]) if col in r.index and pd.notna(r[col]) else None

    # picked_today reflects the ACTUAL production basket (which applies the
    # 504-day min-history gate), NOT this endpoint's unfiltered ranking — a
    # name can rank top-N here yet be excluded from the real basket.
    picked = _in_todays_basket(tu, as_of_d)
    crank = _i("rank")
    thin = 0 < edgar_rows < _FACTORS_THIN_ROWS
    notes = []
    if thin:
        notes.append(f"Quality/value computed on only {edgar_rows} EDGAR quarters "
                     "(likely a recent spin-off) — treat those ranks as unreliable.")
    if not picked and crank is not None and crank <= 24:
        notes.append("Ranks inside the top-24 here but is NOT in today's basket — "
                     "excluded by the min-history gate (insufficient history for "
                     "reliable fundamentals).")
    return TickerFactors(
        ticker=tu, as_of=as_of_d, in_universe=True, picked_today=picked,
        universe_size=len(comp),
        composite_rank=crank,
        composite_z=round(float(r["z_score"]), 2) if pd.notna(r["z_score"]) else None,
        momentum_rank=_i("mom_rank"),
        quality_rank=_i("qual_rank"),
        value_rank=_i("val_rank"),
        pead_rank=_i("pead_rank"),
        edgar_rows=edgar_rows,
        thin_fundamentals=thin,
        note=(" ".join(notes) or None),
    )


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
