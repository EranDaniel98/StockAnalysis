"""Local cache + URL resolution for SEC DERA quarterly bulk zips.

URL pattern (per SEC's DERA financial-statement-dataset distribution):

    https://www.sec.gov/files/dera/data/financial-statement-data-sets/{YYYY}qN.zip

Files in the cache directory follow the same ``{YYYY}qN.zip`` naming so a
populated cache is a drop-in replacement for live downloads. Tests rely on
this contract — they create a synthetic zip at the expected cache path and
parser code never touches the network.

Why a separate client (not reused EDGARClient): the bulk zip endpoint
serves from ``www.sec.gov`` (static asset CDN) rather than ``data.sec.gov``,
the responses are 50-500MB binary blobs (not JSON), and the rate-limit
characteristics differ. Sharing the User-Agent helper avoids drift on the
SEC contact-info convention.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

import httpx

from src.contracts.errors import ExternalAPIError
from src.market_data.edgar.client import DEFAULT_TIMEOUT_S, get_user_agent

logger = logging.getLogger(__name__)

BULK_BASE_URL = "https://www.sec.gov/files/dera/data/financial-statement-data-sets"
"""SEC DERA financial-statement-dataset distribution root. Documented at
https://www.sec.gov/dera/data/financial-statement-data-sets."""

DEFAULT_CACHE_DIR = ".cache/edgar_bulk"


def quarter_url(year: int, quarter: int) -> str:
    """Compose the SEC DERA bulk-zip URL for one calendar quarter.

    Quarters are 1..4. The SEC publishes ~6-8 weeks after quarter-end —
    callers asking for the current quarter will 404.
    """
    if quarter not in (1, 2, 3, 4):
        raise ValueError(f"quarter must be 1..4, got {quarter!r}")
    return f"{BULK_BASE_URL}/{year}q{quarter}.zip"


def quarter_filename(year: int, quarter: int) -> str:
    if quarter not in (1, 2, 3, 4):
        raise ValueError(f"quarter must be 1..4, got {quarter!r}")
    return f"{year}q{quarter}.zip"


def cached_path(year: int, quarter: int, cache_dir: str | Path = DEFAULT_CACHE_DIR) -> Path:
    return Path(cache_dir) / quarter_filename(year, quarter)


class BulkArchiveClient:
    """Manages the on-disk cache of DERA quarter zips.

    Typical use:

        client = BulkArchiveClient()
        path = client.download_quarter(2023, 4)  # cached after first call
        with zipfile.ZipFile(path) as zf:
            ...

    ``download_quarter`` is a no-op when the cache hit is present, making
    the orchestrator safe to re-run.
    """

    def __init__(
        self,
        cache_dir: str | Path = DEFAULT_CACHE_DIR,
        user_agent: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S * 6,  # zips are big, give more headroom
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._user_agent = user_agent or get_user_agent()
        self._timeout_s = timeout_s

    def cache_dir(self) -> Path:
        return self._cache_dir

    def cached_path(self, year: int, quarter: int) -> Path:
        return cached_path(year, quarter, self._cache_dir)

    def is_cached(self, year: int, quarter: int) -> bool:
        return self.cached_path(year, quarter).is_file()

    def download_quarter(self, year: int, quarter: int) -> Path:
        """Download one quarter's zip if not already cached. Returns the
        local path. Idempotent — subsequent calls return immediately when
        the cache file already exists.

        Raises ExternalAPIError on non-200 responses. Network usage is
        gated entirely by this method; parser/ingest paths never call out.
        """
        dest = self.cached_path(year, quarter)
        if dest.is_file():
            logger.debug("Bulk zip cache hit: %s", dest)
            return dest
        url = quarter_url(year, quarter)
        dest.parent.mkdir(parents=True, exist_ok=True)
        headers = {"User-Agent": self._user_agent, "Accept-Encoding": "identity"}
        logger.info("Downloading DERA bulk zip %s → %s", url, dest)
        # Stream to disk so we don't load 500MB into memory.
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with httpx.stream(
                "GET", url, headers=headers, timeout=self._timeout_s, follow_redirects=True
            ) as resp:
                if resp.status_code != 200:
                    raise ExternalAPIError(
                        f"DERA bulk zip {url} returned {resp.status_code}"
                    )
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_bytes(chunk_size=1 << 20):
                        fh.write(chunk)
            os.replace(tmp, dest)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return dest


def iter_year_quarter_pairs(
    start_year: int, start_q: int, end_year: int, end_q: int
) -> Iterable[tuple[int, int]]:
    """Inclusive iteration over (year, quarter) pairs in chronological order.

    Used by the CLI driver to enumerate which zips to ingest for a range.
    """
    if (start_year, start_q) > (end_year, end_q):
        raise ValueError("start must be <= end")
    y, q = start_year, start_q
    while (y, q) <= (end_year, end_q):
        yield y, q
        q += 1
        if q > 4:
            q = 1
            y += 1
