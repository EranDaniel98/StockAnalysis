"""Thin Polygon.io / Massive REST client (stocks aggregates).

Promoted from the working IPO-spike client (scripts/research/spike_ipo_first_day.py).
Scope is deliberately narrow: the aggregates ("aggs") endpoint, which is all the
OHLCV migration needs. Fundamentals stay on EDGAR; this never touches them.

Auth: ``apiKey`` query param (existing Polygon keys work post the Massive
rebrand). Base host api.polygon.io. Pagination via ``next_url``.
"""

from __future__ import annotations

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

_BASE = "https://api.polygon.io"
_TIMEOUT = 30.0


class PolygonError(RuntimeError):
    """Non-retryable Polygon API failure (bad key, 4xx other than 429, exhausted retries)."""


class PolygonClient:
    """Stateless-ish wrapper over the Polygon aggregates endpoint.

    ``aggregates`` returns the raw bar dicts (keys o/h/l/c/v/t-ms); shaping into
    the canonical OHLCV frame is the mapper's job, kept separate so the client
    stays a pure transport layer.
    """

    def __init__(self, api_key: str | None = None, *, session: requests.Session | None = None,
                 max_retries: int = 4):
        self.api_key = api_key or os.getenv("POLYGON_API_KEY") or os.getenv("MASSIVE_API_KEY")
        if not self.api_key:
            raise PolygonError(
                "no POLYGON_API_KEY / MASSIVE_API_KEY in environment — add it to .env")
        self._session = session or requests.Session()
        self._max_retries = max_retries

    def aggregates(self, ticker: str, start, end, *, timespan: str = "day",
                   multiplier: int = 1, adjusted: bool = True, limit: int = 50_000) -> list[dict]:
        """All bars for ``ticker`` in [start, end]. start/end accept date/str/Timestamp.

        ``adjusted`` MUST be True for the factor path (momentum reads split/div-
        adjusted Close); False for raw prints (IPO day-1, intraday microstructure).
        Empty result (delisted / pre-listing window) returns [] — not an error,
        matching the legacy fetcher's "empty -> drop ticker" contract.
        """
        frm, to = _as_date_str(start), _as_date_str(end)
        url = (f"{_BASE}/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{frm}/{to}"
               f"?adjusted={'true' if adjusted else 'false'}&sort=asc&limit={limit}"
               f"&apiKey={self.api_key}")
        results: list[dict] = []
        while url:
            data = self._get(url)
            results.extend(data.get("results") or [])
            nxt = data.get("next_url")
            url = f"{nxt}&apiKey={self.api_key}" if nxt else None
        return results

    def news(self, ticker: str, *, limit: int = 10, published_gte: str | None = None) -> list[dict]:
        """Ticker-tagged news (desc by published_utc). Each item carries
        ``insights`` = per-ticker sentiment when available. ``published_gte`` is
        an ISO date/datetime to window the feed."""
        url = f"{_BASE}/v2/reference/news?ticker={ticker}&order=desc&limit={limit}"
        if published_gte:
            url += f"&published_utc.gte={published_gte}"
        return self._get(url + f"&apiKey={self.api_key}").get("results") or []

    def related_companies(self, ticker: str) -> list[str]:
        """Polygon's related-tickers (peer proxy) for ``ticker``."""
        url = f"{_BASE}/v1/related-companies/{ticker}?apiKey={self.api_key}"
        return [r.get("ticker") for r in (self._get(url).get("results") or []) if r.get("ticker")]

    def short_interest(self, ticker: str, *, limit: int = 12) -> list[dict]:
        """Bi-monthly short-interest settlements (desc). Denser coverage than the
        FINRA-derived `short_interest` table. Fields incl. short_interest (shares),
        avg_daily_volume, days_to_cover, settlement_date."""
        url = (f"{_BASE}/stocks/v1/short-interest?ticker={ticker}"
               f"&order=desc&limit={limit}&apiKey={self.api_key}")
        return self._get(url).get("results") or []

    def _get(self, url: str) -> dict:
        for attempt in range(self._max_retries):
            resp = self._session.get(url, timeout=_TIMEOUT)
            if resp.status_code == 429:                       # rate-limited: back off and retry
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code != 200:
                raise PolygonError(f"{resp.status_code} {url.split('?')[0]}: {resp.text[:200]}")
            return resp.json()
        raise PolygonError(f"rate-limited after {self._max_retries} retries: {url.split('?')[0]}")


def _as_date_str(d) -> str:
    import pandas as pd
    return pd.Timestamp(d).date().isoformat()
