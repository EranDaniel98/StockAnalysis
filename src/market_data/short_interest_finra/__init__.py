"""FINRA Reg SHO daily short-sale-volume ingestion.

Pulls daily per-symbol short volume from FINRA's CDN, parses the
pipe-delimited CNMS files, and writes one row per (ticker,
settlement_date) into the ``short_interest`` Postgres table.

Why "short_interest_finra" not just "short_interest": the source is
*short-sale volume*, not the biweekly short-interest *reportable
position* file. The downstream analyzer reads
``short_interest_shares`` + ``avg_daily_volume`` — the loader
synthesizes those from rolling 30-day windows of these daily rows so
the analyzer's rate-of-change semantics carry over.

Modules:
  client  — async httpx client for the FINRA daily CSV endpoint
  ingest  — orchestrator: fetch + parse + upsert per trading day
  loader  — read path: per-ticker rows → analyzer's ShortInterestRow
"""

from src.market_data.short_interest_finra.client import (
    FINRADailyShortClient,
    parse_daily_csv,
)
from src.market_data.short_interest_finra.ingest import (
    FINRAShortIngestor,
    run_backfill,
)
from src.market_data.short_interest_finra.loader import (
    load_short_interest_rows,
)

__all__ = [
    "FINRADailyShortClient",
    "FINRAShortIngestor",
    "load_short_interest_rows",
    "parse_daily_csv",
    "run_backfill",
]
