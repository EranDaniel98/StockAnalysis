"""Sanity check: for given tickers, compare the most recent EDGAR-sourced
revenue against the current yfinance snapshot.

A green run is no proof of correctness — only that the *magnitudes* line
up. Truly catching mis-tagged concepts requires manual XBRL inspection
on a few tickers (next-quarter work, not Phase 0).

Usage:
    uv run python -m scripts.validate_edgar_backfill --tickers AAPL,MSFT,TSLA
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from src.db.models import Fundamental
from src.db.session import dispose_engine, get_sessionmaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("validate_edgar_backfill")


def _yfinance_revenue(ticker: str) -> float | None:
    """Latest annual revenue from yfinance. Returns None on failure."""
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).info or {}
        return info.get("totalRevenue")
    except Exception as e:
        logger.warning("yfinance lookup failed for %s: %s", ticker, e)
        return None


async def _run(tickers: list[str], tol_pct: float) -> int:
    SessionLocal = get_sessionmaker()
    exit_code = 0

    async with SessionLocal() as session:
        for t in tickers:
            t = t.upper()
            # Compare against most recent 10-K (annual) only — yfinance
            # totalRevenue is TTM, so a 10-Q quarterly figure will always
            # look ~75% off. The 10-K aligns with annualized revenue.
            stmt = (
                select(Fundamental)
                .where(Fundamental.ticker == t)
                .where(Fundamental.revenue.is_not(None))
                .where(Fundamental.source == "edgar_10k")
                .order_by(Fundamental.valid_from.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                logger.warning("%s: no EDGAR rows in Postgres", t)
                exit_code = 2
                continue

            yf_rev = _yfinance_revenue(t)
            if yf_rev is None:
                logger.warning("%s: yfinance no revenue", t)
                exit_code = 2
                continue

            edgar_rev = float(row.revenue or 0)
            if edgar_rev == 0:
                logger.warning("%s: EDGAR revenue is 0", t)
                exit_code = 2
                continue

            delta_pct = abs(edgar_rev - yf_rev) / yf_rev * 100
            within = delta_pct <= tol_pct
            status = "OK" if within else "MISMATCH"
            if not within:
                exit_code = 1
            logger.info(
                "%s: EDGAR rev (%s, filed %s) = $%.2fB, yfinance = $%.2fB, "
                "delta %.1f%% [%s]",
                t,
                row.source,
                row.valid_from.date(),
                edgar_rev / 1e9,
                yf_rev / 1e9,
                delta_pct,
                status,
            )

    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tickers",
        type=str,
        default="AAPL,MSFT,TSLA",
        help="Comma-separated tickers to check (default: AAPL,MSFT,TSLA)",
    )
    parser.add_argument(
        "--tol-pct",
        type=float,
        default=15.0,
        help="Tolerance %% for the EDGAR-10K vs yfinance revenue check. Default 15%% "
        "— EDGAR's latest 10-K is annual revenue while yfinance.totalRevenue is "
        "trailing-twelve-months, so the latest fiscal year and TTM can drift up to "
        "~one full quarter of growth. Flags only wild divergence (mis-tagged concepts).",
    )
    args = parser.parse_args()

    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]

    async def _go() -> int:
        try:
            return await _run(tickers, args.tol_pct)
        finally:
            await dispose_engine()

    sys.exit(asyncio.run(_go()))


if __name__ == "__main__":
    main()
