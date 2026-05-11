"""SEC EDGAR XBRL ingestion.

Pulls point-in-time fundamentals from EDGAR's company-facts API and writes
them to the Postgres `fundamentals` table with source=`edgar_10q` or
`edgar_10k` and a proper valid_from/valid_to interval.

Why PIT matters: the current yfinance-only fundamentals source is a
current-snapshot. Backtests against yfinance fundamentals have a
look-ahead leak (we score historical periods with TODAY'S financials).
EDGAR fixes that — `valid_from` is the actual filing date, so we can
ask "what was AAPL's debt-to-equity as of 2023-03-15?" and get the truth.

Modules:
  client       — async httpx client with the SEC-mandated User-Agent
  concept_map  — XBRL concept → FundamentalSnapshot field map
  parser       — XBRL company_facts JSON → list[FundamentalSnapshot]
  ingest       — orchestrator: fetch + parse + upsert into Postgres
"""

from src.market_data.edgar.client import EDGARClient, get_ticker_to_cik
from src.market_data.edgar.concept_map import CONCEPT_MAP
from src.market_data.edgar.ingest import EDGARIngestor

__all__ = [
    "CONCEPT_MAP",
    "EDGARClient",
    "EDGARIngestor",
    "get_ticker_to_cik",
]
