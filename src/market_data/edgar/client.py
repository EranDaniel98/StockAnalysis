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

# Tier-2 audit #25: SEC explicitly bans anonymous traffic and IP-bans
# repeat offenders. The placeholder ``contact@stocknew.local`` is NOT a
# valid identifier — leaving it in env would silently take EDGAR offline
# for this host after a few hundred requests. ``get_user_agent`` now
# raises if the env var is unset OR contains the placeholder so the
# first EDGAR call fails loud rather than tripping an IP ban.
DEFAULT_USER_AGENT = "StockNew local-dev contact@stocknew.local"
"""Placeholder; will be REFUSED by get_user_agent. Override via
STOCKNEW_EDGAR_USER_AGENT with your real contact info — SEC requires
``AppName email@domain`` format. Anonymous / placeholder traffic gets
this host IP-banned."""

DEFAULT_TIMEOUT_S = 10.0
DEFAULT_REQ_PER_SEC = 8
# Retry budget for transient 5xx responses. Network blips happen; the
# SEC servers are usually fine but the WAF in front sometimes returns
# 502/503 under load. Bounded retries with backoff are required.
DEFAULT_MAX_RETRIES = 3


def get_user_agent() -> str:
    """Return the EDGAR User-Agent or raise. Fails loud on placeholder
    so the first SEC call surfaces the misconfiguration instead of
    quietly burning through requests until the IP gets banned."""
    ua = os.environ.get("STOCKNEW_EDGAR_USER_AGENT", "").strip()
    if not ua or ua == DEFAULT_USER_AGENT:
        raise RuntimeError(
            "STOCKNEW_EDGAR_USER_AGENT is not set or is still the placeholder. "
            "SEC bans anonymous / fake-identifier traffic and IP-bans repeat "
            "offenders. Set the env var to your real contact info in "
            "'AppName your.email@domain' format before calling EDGAR."
        )
    return ua


class _RateLimiter:
    """Token-bucket-ish limiter — simple sleep between requests. Lets the
    client work without a third-party rate-limit lib."""

    def __init__(self, req_per_sec: int) -> None:
        self._interval = 1.0 / max(req_per_sec, 1)
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            # Use the running loop's monotonic clock. Tier-2 #25 noted
            # ``asyncio.get_event_loop()`` would warn / fail under newer
            # async contexts; ``get_running_loop()`` is the modern API.
            now = asyncio.get_running_loop().time()
            wait = self._interval - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = asyncio.get_running_loop().time()


async def _get_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    rate_limiter: _RateLimiter | None = None,
) -> httpx.Response:
    """GET with bounded retries on 429 / 5xx.

    Tier-2 #25: pre-fix every EDGAR endpoint did a single GET with no
    retry path and ignored ``Retry-After``. A transient 502 from the
    SEC WAF would crash the ingestion run. After:

      * 429 (rate limited) -> honor ``Retry-After`` header before retrying
      * 502/503/504 (transient server) -> exponential backoff retry
      * 4xx (other) -> raise immediately, no retry
      * 200 -> return

    ``rate_limiter`` is acquired ONCE per call (before the first GET);
    the retry sleeps are on top of the limiter's interval.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        if rate_limiter is not None and attempt == 0:
            await rate_limiter.acquire()
        try:
            resp = await client.get(url)
        except httpx.HTTPError as e:
            last_exc = e
            if attempt < max_retries:
                backoff = min(2 ** attempt, 8)
                logger.warning(
                    "EDGAR transport error on %s (attempt %d/%d): %s — "
                    "retrying in %ds",
                    url, attempt + 1, max_retries + 1, e, backoff,
                )
                await asyncio.sleep(backoff)
                continue
            raise
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            try:
                wait_s = float(retry_after) if retry_after else min(2 ** attempt, 8)
            except ValueError:
                wait_s = min(2 ** attempt, 8)
            if attempt < max_retries:
                logger.warning(
                    "EDGAR 429 on %s (attempt %d/%d) — sleeping %.1fs "
                    "before retry",
                    url, attempt + 1, max_retries + 1, wait_s,
                )
                await asyncio.sleep(wait_s)
                continue
        if resp.status_code in (502, 503, 504):
            if attempt < max_retries:
                backoff = min(2 ** attempt, 8)
                logger.warning(
                    "EDGAR %d on %s (attempt %d/%d) — retrying in %ds",
                    resp.status_code, url, attempt + 1, max_retries + 1, backoff,
                )
                await asyncio.sleep(backoff)
                continue
        # Final response — caller decides how to interpret status.
        return resp
    if last_exc is not None:
        raise last_exc
    # Shouldn't be reachable, but satisfy the type checker.
    raise ExternalAPIError(f"EDGAR retries exhausted for {url}")


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
        resp = await _get_with_retries(self._client, url, rate_limiter=self._rate)
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
        resp = await _get_with_retries(self._client, url, rate_limiter=self._rate)
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
        resp = await _get_with_retries(self._client, url, rate_limiter=self._rate)
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
        resp = await _get_with_retries(self._client, url, rate_limiter=self._rate)
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
