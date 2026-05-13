"""Read path: daily-short rows → analyzer-shaped ShortInterestRow series.

The analyzer at ``src/scoring/analyzers/short_interest.py`` expects
biweekly-style rows with:
  * ``settlement_date``: date
  * ``short_interest_shares``: int — total shares sold short on the
    "as-of" date for the report
  * ``avg_daily_volume``: int | None — used to derive days-to-cover
  * ``days_to_cover``: float | None — pre-computed alternative

FINRA's daily file gives us *daily short-sale volume* instead. We
synthesize the analyzer's row shape by rolling a 30-day window over
the daily rows:

  ``short_interest_shares`` <- sum of daily short_volume over 30d
  ``avg_daily_volume``      <- mean of daily total_volume over 30d
  ``days_to_cover``         <- derived inside the analyzer

The analyzer's signal logic — rate-of-change of short pressure and
days-to-cover thresholds — translates because the 30-day cumulative
captures sustained short pressure rather than one-day spikes, on the
same scale as biweekly FINRA short-interest reports.

The output series carries one row per trading day in the requested
window (after the rolling-window warm-up). The analyzer picks the
latest + a 30-day-prior baseline internally, so denser data is fine.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ShortInterest as ShortInterestDB
from src.scoring.analyzers.short_interest import ShortInterestRow

logger = logging.getLogger(__name__)

# Rolling window: 30 days mirrors the analyzer's default change-window
# and the typical FINRA biweekly cadence. Don't expose as a parameter
# unless the analyzer's ``window_days`` also becomes loader-tunable;
# the two have to stay aligned for the rate-of-change semantics to
# hold.
WINDOW_DAYS = 30


def _aggregate_daily(
    rows: Sequence[ShortInterestDB],
) -> tuple[list[date], list[int], list[int]]:
    """Collapse ORM rows into parallel arrays sorted by settlement_date
    ascending. Returns (dates, short_volume, total_volume).

    Duplicates on the same date (shouldn't happen given the unique
    constraint, but we're defensive against re-runs that bypass the
    constraint via raw SQL) are summed.
    """
    by_date: dict[date, tuple[int, int]] = {}
    for r in rows:
        prev = by_date.get(r.settlement_date, (0, 0))
        by_date[r.settlement_date] = (
            prev[0] + int(r.short_volume),
            prev[1] + int(r.total_volume),
        )
    dates = sorted(by_date.keys())
    sv = [by_date[d][0] for d in dates]
    tv = [by_date[d][1] for d in dates]
    return dates, sv, tv


def _rolling_series(
    dates: list[date],
    short_volume: list[int],
    total_volume: list[int],
    *,
    window: int = WINDOW_DAYS,
) -> list[ShortInterestRow]:
    """Compute rolling-window aggregates indexed by trading-day position.

    We roll over *trading days* (the entries in ``dates``), NOT over a
    calendar window — FINRA only publishes for trading days, so window
    size N here = "last N trading days" ~ 6 calendar weeks (close
    enough to the 30 calendar days the analyzer's docstring uses).

    Skip the warm-up: rows with fewer than ``window`` prior days are
    omitted so we don't pass partial sums to the analyzer.
    """
    out: list[ShortInterestRow] = []
    n = len(dates)
    if n < window:
        return out
    # Prefix sums so each rolling window is O(1).
    sv_pre = [0] * (n + 1)
    tv_pre = [0] * (n + 1)
    for i in range(n):
        sv_pre[i + 1] = sv_pre[i] + short_volume[i]
        tv_pre[i + 1] = tv_pre[i] + total_volume[i]
    for i in range(window - 1, n):
        lo = i - window + 1
        sv_sum = sv_pre[i + 1] - sv_pre[lo]
        tv_sum = tv_pre[i + 1] - tv_pre[lo]
        avg_daily = int(round(tv_sum / window)) if tv_sum > 0 else None
        out.append(ShortInterestRow(
            settlement_date=dates[i],
            short_interest_shares=int(sv_sum),
            avg_daily_volume=avg_daily,
            days_to_cover=None,  # analyzer derives from avg_daily_volume
        ))
    return out


async def load_short_interest_rows(
    session: AsyncSession,
    tickers: Sequence[str],
    *,
    lookback_days: int = 180,
    as_of: date | None = None,
) -> dict[str, list[ShortInterestRow]]:
    """Load rolling 30-day short-interest series for each ticker.

    Reads ``short_interest`` rows in ``[as_of - lookback_days, as_of]``
    for the requested tickers, aggregates per (ticker, day), and
    computes the rolling-window series the analyzer expects.

    ``lookback_days`` should be at least ``WINDOW_DAYS + N`` where N
    is the comfortable change-detection runway the analyzer wants
    (the analyzer's default 30-day baseline pick → minimum 60 calendar
    days, but more is better for noisy days). The default 180 gives
    the analyzer 4-5 monthly snapshots' worth of history.

    Returns ``{TICKER: [rows sorted ascending by settlement_date]}``.
    Tickers with no qualifying rows map to an empty list — callers
    iterate the dict directly without missing-key handling.
    """
    if not tickers:
        return {}
    end = as_of or date.today()
    start = end - timedelta(days=int(lookback_days))
    upper = [t.upper().replace(".", "") for t in tickers if t]
    # Initialize result dict so every requested ticker shows up,
    # even with [] when there's no data. Caller convention from the
    # task spec.
    result: dict[str, list[ShortInterestRow]] = {t: [] for t in upper}

    stmt = (
        select(ShortInterestDB)
        .where(ShortInterestDB.ticker.in_(upper))
        .where(ShortInterestDB.settlement_date >= start)
        .where(ShortInterestDB.settlement_date <= end)
        .order_by(ShortInterestDB.ticker.asc(),
                  ShortInterestDB.settlement_date.asc())
    )
    res = await session.execute(stmt)
    by_ticker: dict[str, list[ShortInterestDB]] = {}
    for row in res.scalars().all():
        by_ticker.setdefault(row.ticker, []).append(row)

    for t, ticker_rows in by_ticker.items():
        dates, sv, tv = _aggregate_daily(ticker_rows)
        series = _rolling_series(dates, sv, tv)
        # Even if the loader has rows but they don't span 30 days, the
        # rolling helper returns [] and we leave the ticker as []. The
        # analyzer requires >=2 rows so a single short series wouldn't
        # produce a score anyway.
        result[t] = series
    return result


def load_short_interest_rows_sync(
    tickers: Sequence[str],
    *,
    lookback_days: int = 180,
    as_of: date | None = None,
) -> dict[str, list[ShortInterestRow]]:
    """Sync wrapper for CLI / backtest contexts that aren't async.

    Builds a fresh AsyncSession via the default sessionmaker and
    closes it before returning. Don't call this from inside an
    already-running event loop — that's an ``asyncio.run`` violation.
    Use ``load_short_interest_rows`` directly under async code.
    """
    import asyncio

    from src.db.session import get_sessionmaker

    async def _run() -> dict[str, list[ShortInterestRow]]:
        SessionLocal = get_sessionmaker()
        async with SessionLocal() as session:
            return await load_short_interest_rows(
                session, tickers, lookback_days=lookback_days, as_of=as_of,
            )

    return asyncio.run(_run())


# Re-exported helpers — unit tests import these for the synthetic-row
# path that doesn't touch Postgres.
__all__ = [
    "WINDOW_DAYS",
    "ShortInterestRow",
    "load_short_interest_rows",
    "load_short_interest_rows_sync",
    "_aggregate_daily",
    "_rolling_series",
]


def build_series_from_daily(
    daily: Sequence[tuple[date, int, int]],
) -> list[ShortInterestRow]:
    """Pure helper for tests: take ``[(date, short_vol, total_vol), ...]``
    sorted ascending and return the rolling-window analyzer rows.

    Lives in the loader (not the test file) so callers writing custom
    ingest paths (e.g. a CSV one-off) can reuse the same windowing
    logic without spinning up the ORM.
    """
    if not daily:
        return []
    sorted_daily = sorted(daily, key=lambda t: t[0])
    dates = [t[0] for t in sorted_daily]
    sv = [int(t[1]) for t in sorted_daily]
    tv = [int(t[2]) for t in sorted_daily]
    return _rolling_series(dates, sv, tv)


# Append to __all__ after definition (avoids duplication above).
__all__.append("build_series_from_daily")
