"""Async HTTP client for FINRA Reg SHO daily short-sale-volume CSVs.

Endpoint (Option A, preferred):

    https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt

Pipe-delimited text. Header row + one data row per (Symbol, Market).
Columns: Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market

Coverage: ~2009-08-01 to T-1 (today's file appears after FINRA's
end-of-day batch ~02:00 ET the next day). Files are ~5MB compressed,
~15MB uncompressed; FINRA's CDN serves them gzipped transparently.

Anti-bot: FINRA's CDN is permissive — no User-Agent gate, no rate
limit published. We default to 1 req/sec to stay polite. If we ever
get throttled, drop to 0.5/sec; if blocked, fall back to Option B
(NYSE Reg SHO daily file at https://www.nyse.com/regulation/threshold-securities).

Missing days: market holidays + weekends → 404. The orchestrator
treats 404 as a non-fatal skip (we never produced a file for that
date) rather than a hard error.

Ticker normalization: FINRA's Symbol column is plain ASCII tickers
(e.g. ``BRK.A`` shows as ``BRKA`` — FINRA strips dots). We upper-case
on read and leave the dot-stripped form alone — the analyzer matches
on the value the ingester wrote, so this is consistent. Loader callers
should pass the FINRA-flavor ticker (no dots) if their universe uses
``BRK.A`` form.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import date
from io import StringIO
from typing import Iterable

import httpx
import pandas as pd

from src.contracts.errors import ExternalAPIError

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "StockNew local-dev contact@stocknew.local"
"""FINRA doesn't require a User-Agent but we send one for polite
parity with other ingestion clients. Override via
``STOCKNEW_FINRA_USER_AGENT`` env var."""

DEFAULT_TIMEOUT_S = 30.0
DEFAULT_REQ_PER_SEC = 1.0
"""Polite default — FINRA publishes no rate-limit; 1 req/sec is light
enough to never trip whatever silent throttle they may have."""

BASE_URL = "https://cdn.finra.org/equity/regsho/daily"


def get_user_agent() -> str:
    return os.environ.get("STOCKNEW_FINRA_USER_AGENT", DEFAULT_USER_AGENT)


@dataclass(frozen=True)
class DailyShortRow:
    """One row of the FINRA CNMS daily file, post-aggregation across
    market segments.

    FINRA publishes per-(symbol, market) breakdowns (Q=Nasdaq, N=NYSE,
    A=NYSE American, etc.). We aggregate across markets so each
    (symbol, settlement_date) ends up as one row — that's the unique
    natural key in the Postgres table.
    """

    settlement_date: date
    ticker: str
    short_volume: int
    total_volume: int
    short_exempt_volume: int = 0


class _RateLimiter:
    """Token-bucket-ish sleep limiter (same pattern as EDGARClient)."""

    def __init__(self, req_per_sec: float) -> None:
        self._interval = 1.0 / max(req_per_sec, 0.1)
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._interval - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()


def _url_for(d: date) -> str:
    """Build the FINRA daily-file URL for a given trading date."""
    return f"{BASE_URL}/CNMSshvol{d.strftime('%Y%m%d')}.txt"


def parse_daily_csv(content: str, *, default_date: date | None = None) -> list[DailyShortRow]:
    """Parse one FINRA CNMS daily file into aggregated rows.

    Aggregation: FINRA reports one row per (Symbol, Market). Some
    symbols trade across multiple consolidated venues so the same
    symbol shows up twice or three times in a single file. We sum
    ShortVolume + TotalVolume + ShortExemptVolume across markets so
    the natural key (ticker, settlement_date) holds.

    FINRA appends a trailer line "File Trailer|<n>|<sum>" — we drop it
    via pandas's lenient parser (rows with NaN in the numeric columns
    after coercion).

    ``default_date`` is used as a fallback when a row's Date column is
    missing or malformed (rare — happens with the trailer line).
    Production callers always know the date from the URL they hit.
    """
    if not content.strip():
        return []
    # pandas handles the trailer line cleanly when we coerce numerics
    # and drop NaNs after.
    try:
        df = pd.read_csv(
            StringIO(content),
            sep="|",
            engine="python",
            on_bad_lines="skip",
        )
    except Exception as e:  # noqa: BLE001
        raise ExternalAPIError(f"FINRA CSV parse error: {e}") from e

    required = {"Symbol", "ShortVolume", "TotalVolume"}
    missing = required - set(df.columns)
    if missing:
        raise ExternalAPIError(f"FINRA CSV missing columns: {sorted(missing)}")

    # Coerce numerics; drop rows where required ints are NaN (e.g. trailer).
    for col in ("ShortVolume", "TotalVolume", "ShortExemptVolume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Symbol", "ShortVolume", "TotalVolume"])

    # Settlement date: prefer the row's Date column (YYYYMMDD), fall
    # back to the caller-supplied default. We standardize on the
    # parsed-from-URL date when both disagree — FINRA has been known
    # to swap the Date field on re-publishes.
    def _row_date(raw: object) -> date | None:
        try:
            s = str(int(raw))  # handles both int and str repr
        except (TypeError, ValueError):
            return None
        if len(s) != 8:
            return None
        try:
            return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
        except ValueError:
            return None

    rows: list[DailyShortRow] = []
    # Aggregate across markets per symbol.
    by_symbol: dict[str, dict[str, int | date | None]] = {}
    for _, r in df.iterrows():
        sym = str(r["Symbol"]).strip().upper()
        if not sym:
            continue
        d = _row_date(r.get("Date")) if "Date" in df.columns else None
        if d is None:
            d = default_date
        if d is None:
            # No date anywhere — skip rather than fabricate one.
            continue
        slot = by_symbol.setdefault(sym, {
            "settlement_date": d,
            "short_volume": 0,
            "total_volume": 0,
            "short_exempt_volume": 0,
        })
        slot["short_volume"] = int(slot["short_volume"]) + int(r["ShortVolume"])
        slot["total_volume"] = int(slot["total_volume"]) + int(r["TotalVolume"])
        if "ShortExemptVolume" in df.columns:
            sev = r.get("ShortExemptVolume")
            if pd.notna(sev):
                slot["short_exempt_volume"] = (
                    int(slot["short_exempt_volume"]) + int(sev)
                )
    for sym, vals in by_symbol.items():
        # Drop rows with zero total volume — those are FINRA artifacts
        # (suspended symbols still listed). Keep zero short_volume rows
        # since "no shorting that day" is a real datum.
        if int(vals["total_volume"]) <= 0:
            continue
        rows.append(DailyShortRow(
            settlement_date=vals["settlement_date"],  # type: ignore[arg-type]
            ticker=sym,
            short_volume=int(vals["short_volume"]),
            total_volume=int(vals["total_volume"]),
            short_exempt_volume=int(vals["short_exempt_volume"]),
        ))
    return rows


class FINRADailyShortClient:
    """Async client for FINRA's CNMS Reg SHO daily files.

    Lifecycle mirrors ``EDGARClient`` — single ``httpx.AsyncClient``
    reused across all calls; call ``aclose()`` at process shutdown.
    """

    def __init__(
        self,
        user_agent: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        req_per_sec: float = DEFAULT_REQ_PER_SEC,
    ) -> None:
        headers = {
            "User-Agent": user_agent or get_user_agent(),
            "Accept-Encoding": "gzip, deflate",
        }
        self._client = httpx.AsyncClient(timeout=timeout_s, headers=headers)
        self._rate = _RateLimiter(req_per_sec)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch_daily(self, d: date) -> list[DailyShortRow]:
        """Fetch + parse the FINRA CNMS file for one trading day.

        Returns ``[]`` for weekends, market holidays, and any other
        date where FINRA returns 404 — that's a missing-data signal,
        not an error. Raises ``ExternalAPIError`` only on real HTTP
        failures (5xx, timeout, malformed CSV).
        """
        url = _url_for(d)
        await self._rate.acquire()
        try:
            resp = await self._client.get(url)
        except httpx.HTTPError as e:
            raise ExternalAPIError(f"FINRA fetch error for {d}: {e}") from e
        if resp.status_code == 404:
            logger.debug("No FINRA file for %s (holiday or weekend)", d)
            return []
        if resp.status_code != 200:
            raise ExternalAPIError(
                f"FINRA returned {resp.status_code} for {d}: {resp.text[:200]}"
            )
        return parse_daily_csv(resp.text, default_date=d)

    async def fetch_range(
        self,
        start: date,
        end: date,
    ) -> dict[date, list[DailyShortRow]]:
        """Fetch all daily files in the inclusive date range.

        Sequential (NOT concurrent) to stay under our polite 1 req/sec
        default. Returns ``{settlement_date: rows}``; empty dates
        (holidays, weekends) are omitted from the result.
        """
        out: dict[date, list[DailyShortRow]] = {}
        cur = start
        while cur <= end:
            try:
                rows = await self.fetch_daily(cur)
            except ExternalAPIError as e:
                logger.warning("FINRA error for %s: %s (skipping)", cur, e)
                rows = []
            if rows:
                out[cur] = rows
            cur = date.fromordinal(cur.toordinal() + 1)
        return out


def trading_days(start: date, end: date) -> Iterable[date]:
    """Yield weekday dates between start and end inclusive.

    Doesn't filter US market holidays — FINRA returns 404 for those
    and the client treats 404 as a non-fatal skip, so listing the
    extra dates costs ~1 second per holiday and keeps the helper free
    of holiday-calendar dependencies.
    """
    cur = start
    while cur <= end:
        if cur.weekday() < 5:  # Mon-Fri
            yield cur
        cur = date.fromordinal(cur.toordinal() + 1)
