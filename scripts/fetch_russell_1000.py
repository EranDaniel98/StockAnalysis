"""Fetch the current Russell 1000 ticker list from iShares IWB holdings.

The Russell 1000 reconstitutes annually (late June) and its constituents
drift throughout the year. iShares publishes the live IWB ETF holdings as
a free CSV; downloading it gives us the most-current index snapshot
without scraping Wikipedia or paying for Russell's direct feed.

Usage:
    uv run python -m scripts.fetch_russell_1000

Output:
    config/russell_1000_tickers.txt  (one ticker per line, sorted)

Run quarterly to refresh — iShares updates the CSV daily.
"""

from __future__ import annotations

import csv
import io
import logging
import sys
from pathlib import Path

import httpx

IWB_HOLDINGS_URL = (
    "https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/"
    "1467271812596.ajax?fileType=csv&fileName=IWB_holdings&dataType=fund"
)

OUTPUT_PATH = Path(__file__).parent.parent / "config" / "russell_1000_tickers.txt"

# Asset-class strings iShares uses for non-equity holdings. We drop these so
# the output is a clean equity universe — no cash, futures, or derivatives.
EQUITY_ASSET_CLASSES = {"equity", "Equity"}

# Header row in the IWB CSV starts with the literal "Ticker" string. iShares
# prepends ~9 metadata rows (fund name, NAV, date, etc.) which we skip.
HEADER_MARKER = "Ticker"

# A few ticker shapes that iShares emits but yfinance refuses or treats
# differently. None of these are real US equities for our purposes — they're
# either cash positions, futures, or class-share variants that conflict with
# the parent (BRK.B handled separately).
SKIP_TICKERS = {
    "-",         # cash holding
    "USD",       # cash holding
    "BRK",       # parent of BRK.B; iShares uses BRK.B
    "MARGIN_USD",  # cash collateral
}

# iShares uses BRK.B notation; yfinance wants BRK-B (dot → dash for
# multi-share-class tickers). Map both ways so we emit the yfinance form.
TICKER_DOT_REPLACEMENTS = (".", "-")


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fetch_russell_1000")


def _download_csv(url: str = IWB_HOLDINGS_URL) -> str:
    """Pull the IWB holdings CSV. Returns the body as text. Raises on
    non-200 — caller decides how to recover."""
    # iShares blocks default httpx user-agents; mimic a browser.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/csv,text/plain,*/*",
    }
    with httpx.Client(timeout=30.0, headers=headers, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text


def _parse_holdings_csv(text: str) -> list[str]:
    """Walk the CSV, skip preamble rows until the Ticker header, then read
    equity rows. Returns the deduplicated, sorted list of US-form tickers."""
    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith(HEADER_MARKER + ","):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError(
            "Could not find header row starting with 'Ticker' in IWB CSV — "
            "iShares may have changed the format."
        )

    rows_io = io.StringIO("\n".join(lines[header_idx:]))
    reader = csv.DictReader(rows_io)
    tickers: set[str] = set()
    for row in reader:
        raw = (row.get("Ticker") or "").strip().strip('"')
        asset_class = (row.get("Asset Class") or "").strip()
        if not raw or raw in SKIP_TICKERS:
            continue
        # iShares occasionally lists futures/cash with empty or non-equity
        # asset class. When the column is present we filter strictly; when
        # it's missing (older CSV format) we fall through and keep the row.
        if asset_class and asset_class not in EQUITY_ASSET_CLASSES:
            continue
        # Normalize multi-share-class notation (BRK.B → BRK-B).
        normalized = raw.replace(*TICKER_DOT_REPLACEMENTS)
        # Filter out anything that doesn't look like an equity ticker — pure
        # letters + optional dash for share classes.
        if not all(c.isalpha() or c == "-" for c in normalized):
            continue
        tickers.add(normalized.upper())
    return sorted(tickers)


def main() -> int:
    logger.info("Downloading IWB holdings from iShares...")
    try:
        text = _download_csv()
    except httpx.HTTPError as e:
        logger.error("iShares download failed: %s", e)
        return 1

    logger.info("Parsing %d bytes of CSV...", len(text))
    tickers = _parse_holdings_csv(text)
    if len(tickers) < 800:
        logger.warning(
            "Only %d tickers parsed — Russell 1000 should be ~1000. "
            "Format may have changed; inspect the CSV.",
            len(tickers),
        )
        if len(tickers) < 100:
            logger.error("Too few tickers to be plausibly the Russell 1000. Aborting.")
            return 2
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(tickers) + "\n", encoding="utf-8")
    logger.info("Wrote %d tickers to %s", len(tickers), OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
