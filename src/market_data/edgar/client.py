"""Async EDGAR HTTP client.

SEC mandates a descriptive User-Agent on every request — they block
anonymous traffic. Set STOCKNEW_EDGAR_USER_AGENT to your own
"AppName email@domain" string before hitting the API in volume.

Two endpoints we use:
  - https://www.sec.gov/files/company_tickers.json
      Ticker → CIK mapping (refreshed weekly by SEC).
  - https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json
      All XBRL-reported concepts across all filings for one company.

Rate limit: SEC's published limit is 10 req/sec across all of data.sec.gov
+ www.sec.gov. We enforce 8/sec to leave headroom.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from src.contracts.errors import ExternalAPIError

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "StockNew local-dev contact@stocknew.local"
"""SEC blocks anonymous traffic. Override via STOCKNEW_EDGAR_USER_AGENT
with your real contact info (any AppName + email format works)."""

DEFAULT_TIMEOUT_S = 10.0
DEFAULT_REQ_PER_SEC = 8


def get_user_agent() -> str:
    return os.environ.get("STOCKNEW_EDGAR_USER_AGENT", DEFAULT_USER_AGENT)


class _RateLimiter:
    """Token-bucket-ish limiter — simple sleep between requests. Lets the
    client work without a third-party rate-limit lib."""

    def __init__(self, req_per_sec: int) -> None:
        self._interval = 1.0 / max(req_per_sec, 1)
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = asyncio.get_event_loop().time()
            wait = self._interval - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = asyncio.get_event_loop().time()


class EDGARClient:
    """Async EDGAR client. Single-process — reuses one httpx.AsyncClient
    so the connection pool stays warm across calls."""

    BASE_DATA = "https://data.sec.gov"
    BASE_WWW = "https://www.sec.gov"

    def __init__(
        self,
        user_agent: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        req_per_sec: int = DEFAULT_REQ_PER_SEC,
    ) -> None:
        self._headers = {
            "User-Agent": user_agent or get_user_agent(),
            "Accept-Encoding": "gzip, deflate",
            "Host": "data.sec.gov",  # overwritten per request when needed
        }
        self._client = httpx.AsyncClient(
            timeout=timeout_s,
            headers={
                "User-Agent": self._headers["User-Agent"],
                "Accept-Encoding": "gzip, deflate",
            },
        )
        self._rate = _RateLimiter(req_per_sec)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch_company_tickers(self) -> dict[str, Any]:
        """Returns the SEC's ticker → CIK index. Cache this — it's a 1MB
        JSON file refreshed weekly."""
        url = f"{self.BASE_WWW}/files/company_tickers.json"
        await self._rate.acquire()
        resp = await self._client.get(url)
        if resp.status_code != 200:
            raise ExternalAPIError(
                f"EDGAR ticker index returned {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json()

    async def fetch_company_facts(self, cik: int) -> dict[str, Any]:
        """All XBRL-reported facts for one company. Returns the raw EDGAR
        JSON shape; parser turns it into FundamentalSnapshot rows."""
        cik_padded = f"{int(cik):010d}"
        url = f"{self.BASE_DATA}/api/xbrl/companyfacts/CIK{cik_padded}.json"
        await self._rate.acquire()
        resp = await self._client.get(url)
        if resp.status_code == 404:
            raise ExternalAPIError(f"No EDGAR facts for CIK {cik_padded}")
        if resp.status_code != 200:
            raise ExternalAPIError(
                f"EDGAR companyfacts returned {resp.status_code} for CIK {cik_padded}"
            )
        return resp.json()

    async def fetch_submissions(self, cik: int) -> dict[str, Any]:
        """Company submissions metadata: recent filings + the form types
        we'd want to ingest. Used by Phase 5.2 RAG ingestion."""
        cik_padded = f"{int(cik):010d}"
        url = f"{self.BASE_DATA}/submissions/CIK{cik_padded}.json"
        await self._rate.acquire()
        resp = await self._client.get(url)
        if resp.status_code != 200:
            raise ExternalAPIError(
                f"EDGAR submissions returned {resp.status_code} for CIK {cik_padded}"
            )
        return resp.json()

    async def fetch_filing_text(
        self, cik: int, accession_no: str, primary_doc: str
    ) -> str:
        """Raw HTML/text of one filing's primary document.

        ``accession_no`` comes back from ``fetch_submissions`` with dashes
        (e.g. "0000320193-25-000123"). The archive URL strips dashes.
        """
        cik_str = str(int(cik))
        accession_clean = accession_no.replace("-", "")
        url = (
            f"{self.BASE_WWW}/Archives/edgar/data/"
            f"{cik_str}/{accession_clean}/{primary_doc}"
        )
        await self._rate.acquire()
        resp = await self._client.get(url)
        if resp.status_code != 200:
            raise ExternalAPIError(
                f"EDGAR filing text returned {resp.status_code} for {accession_no}"
            )
        return resp.text


async def get_ticker_to_cik(
    client: EDGARClient | None = None,
) -> dict[str, int]:
    """Convenience wrapper: returns {TICKER: cik} for ~10k US-listed companies.

    The SEC index ships as a positional JSON object where each value is
    {cik_str, ticker, title}. We flatten to {ticker → int cik}.
    """
    owned_client = client is None
    if client is None:
        client = EDGARClient()
    try:
        raw = await client.fetch_company_tickers()
        mapping: dict[str, int] = {}
        for entry in raw.values():
            tkr = entry.get("ticker", "").upper()
            cik = entry.get("cik_str")
            if tkr and cik is not None:
                mapping[tkr] = int(cik)
        return mapping
    finally:
        if owned_client:
            await client.aclose()
