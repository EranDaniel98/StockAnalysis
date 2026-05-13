"""Backfill the EDGAR filings_corpus for the research agent's RAG.

Usage:
    # Ingest themes universe, latest 4 of each form per ticker (default)
    uv run python -m scripts.ingest_filings --universe themes

    # Just one ticker for quick testing
    uv run python -m scripts.ingest_filings --tickers AAPL --per-form 1

    # Limit to 10-K only
    uv run python -m scripts.ingest_filings --tickers AAPL --forms 10-K --per-form 2

EDGAR is rate-limited to 8 req/sec; the embedder is CPU-bound on the
local sentence-transformer. Expect ~5-10s per filing wall-clock.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from src.config_loader import Config
from src.db.session import dispose_engine, get_sessionmaker
from src.research_agent.rag.ingest import (
    DEFAULT_FORMS,
    DEFAULT_PER_FORM_LIMIT,
    ingest_universe,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_filings")


def _resolve_universe(cfg: Config, universe: str, tickers_arg: str | None) -> list[str]:
    if tickers_arg:
        return [t.strip().upper() for t in tickers_arg.split(",") if t.strip()]
    if universe == "watchlist":
        return cfg.get_watchlist()
    if universe == "themes":
        return cfg.get_theme_tickers()
    if universe == "value_cohort":
        return cfg.get_value_cohort_tickers()
    if universe == "portfolio":
        from src.portfolio import Portfolio

        return Portfolio(cfg).get_tickers()
    raise ValueError(f"unknown universe: {universe}")


async def _run(args: argparse.Namespace) -> int:
    cfg = Config()
    tickers = _resolve_universe(cfg, args.universe, args.tickers)
    if not tickers:
        logger.error("empty universe; nothing to ingest")
        return 2
    logger.info("ingesting %d tickers, forms=%s, per_form=%d",
                len(tickers), args.forms, args.per_form)

    SessionLocal = get_sessionmaker()
    forms = tuple(f.strip() for f in args.forms.split(",") if f.strip())

    stats = await ingest_universe(
        tickers,
        sessionmaker=SessionLocal,
        forms=forms,
        per_form_limit=args.per_form,
        max_concurrent=args.concurrency,
    )

    total_chunks = sum(s.n_chunks for s in stats)
    total_filings = sum(s.n_filings for s in stats)
    total_errors = sum(len(s.errors) for s in stats)
    logger.info(
        "done — %d tickers, %d filings, %d chunks, %d errors",
        len(stats), total_filings, total_chunks, total_errors,
    )
    if total_errors:
        for s in stats:
            for err in s.errors:
                logger.warning("  %s: %s", s.ticker, err)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", default="themes",
                        choices=["watchlist", "portfolio", "themes", "value_cohort"])
    parser.add_argument("--tickers", default=None,
                        help="Comma-separated tickers (overrides --universe)")
    parser.add_argument("--forms", default=",".join(DEFAULT_FORMS),
                        help=f"Comma-separated form types. Default: {','.join(DEFAULT_FORMS)}")
    parser.add_argument("--per-form", type=int, default=DEFAULT_PER_FORM_LIMIT,
                        help=f"Latest N filings per form per ticker. Default {DEFAULT_PER_FORM_LIMIT}.")
    parser.add_argument("--concurrency", type=int, default=2,
                        help="Concurrent tickers. SEC limits to 8 req/sec total — keep low.")
    args = parser.parse_args()

    async def _go() -> int:
        try:
            return await _run(args)
        finally:
            await dispose_engine()

    sys.exit(asyncio.run(_go()))


if __name__ == "__main__":
    main()
