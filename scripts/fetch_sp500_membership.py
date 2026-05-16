"""Cache S&P 500 current constituents + change history from Wikipedia.

Writes two CSVs under ``data/universe/``:

- ``sp500_current.csv``    — symbol, security, sector, date_added, cik
- ``sp500_changes.csv``    — date, action ("add"/"remove"), ticker, security, reason

Wikipedia's "Selected changes" table only goes back to roughly the
mid-2000s. That's a known limitation; do NOT claim PIT coverage older
than the earliest event in ``sp500_changes.csv``.

Run unattended on a weekly cadence to keep the cache fresh. The
scraper is intentionally minimal — we capture raw Wikipedia data
verbatim (no in-script cleanup) so audit trail is preserved. The
PIT loader (``src/universe/sp500_pit.py``) does the normalization.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd


WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
USER_AGENT = (
    "StockNew-Research/0.1 (personal research; "
    "contact: erand1998@gmail.com)"
)
OUT_DIR = Path("data/universe")
CURRENT_CSV = OUT_DIR / "sp500_current.csv"
CHANGES_CSV = OUT_DIR / "sp500_changes.csv"
META_TXT = OUT_DIR / "sp500_source.txt"

logger = logging.getLogger("fetch_sp500_membership")


def _scrape() -> tuple[pd.DataFrame, pd.DataFrame]:
    logger.info("Reading %s", WIKIPEDIA_URL)
    # Wikipedia blocks the default urllib UA — fetch via httpx with a
    # contact-providing UA, then hand the HTML string to pandas.
    resp = httpx.get(
        WIKIPEDIA_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        timeout=30.0,
        follow_redirects=True,
    )
    resp.raise_for_status()
    from io import StringIO
    tables = pd.read_html(StringIO(resp.text))
    if len(tables) < 2:
        raise RuntimeError(
            f"Expected ≥2 tables on Wikipedia page, got {len(tables)}",
        )
    current = tables[0]
    changes_raw = tables[1]
    logger.info("Current table: %d rows / %d cols",
                len(current), len(current.columns))
    logger.info("Changes table (raw): %d rows / multilevel cols=%s",
                len(changes_raw),
                isinstance(changes_raw.columns, pd.MultiIndex))
    return current, changes_raw


def _normalize_current(df: pd.DataFrame) -> pd.DataFrame:
    cols = {c.lower(): c for c in df.columns}
    sym = cols.get("symbol")
    sec = cols.get("security")
    sector = cols.get("gics sector")
    date_added = cols.get("date added")
    cik = cols.get("cik")
    if not all((sym, sec, date_added)):
        raise RuntimeError(
            f"Unexpected Wikipedia 'current' columns: {list(df.columns)}",
        )
    out = pd.DataFrame({
        "symbol": df[sym].astype(str).str.strip(),
        "security": df[sec].astype(str).str.strip(),
        "sector": df[sector].astype(str).str.strip() if sector else "",
        "date_added": df[date_added].astype(str).str.strip(),
        "cik": df[cik].astype(str).str.strip() if cik else "",
    })
    return out


def _normalize_changes(df: pd.DataFrame) -> pd.DataFrame:
    # The changes table is a MultiIndex: ("Date", "Date"), ("Added",
    # "Ticker"), ("Added", "Security"), ("Removed", "Ticker"),
    # ("Removed", "Security"), ("Reason", "Reason"). Flatten to a long
    # form: one row per add OR remove event.
    if not isinstance(df.columns, pd.MultiIndex):
        # Fallback: assume already-flat columns.
        raise RuntimeError(
            "Expected MultiIndex columns on changes table — Wikipedia "
            "format may have changed. Inspect manually.",
        )
    # Wikipedia uses either ("Date", "Date") or ("Effective Date", "Effective
    # Date") at the top level — accept both.
    date_candidates = [c for c in df.columns
                       if "date" in c[0].lower()]
    date_col = date_candidates[0] if date_candidates else ("Date", "Date")
    reason_cols = [c for c in df.columns
                   if c[0].lower().startswith("reason")]
    added_ticker = next(
        (c for c in df.columns
         if c[0].lower().startswith("added") and "ticker" in c[1].lower()),
        None,
    )
    added_security = next(
        (c for c in df.columns
         if c[0].lower().startswith("added") and "security" in c[1].lower()),
        None,
    )
    removed_ticker = next(
        (c for c in df.columns
         if c[0].lower().startswith("removed") and "ticker" in c[1].lower()),
        None,
    )
    removed_security = next(
        (c for c in df.columns
         if c[0].lower().startswith("removed") and "security" in c[1].lower()),
        None,
    )
    if not all((added_ticker, removed_ticker)):
        raise RuntimeError(
            f"Changes table missing Added/Removed ticker columns: "
            f"{list(df.columns)}",
        )
    if date_col not in df.columns:
        raise RuntimeError(
            f"No Date column resolvable in changes table: "
            f"{list(df.columns)}",
        )
    reason_col = reason_cols[0] if reason_cols else None

    rows: list[dict] = []
    for _, r in df.iterrows():
        raw_date = str(r[date_col]).strip()
        # Wikipedia date strings: "March 21, 2024" — let pandas parse.
        try:
            dt = pd.to_datetime(raw_date, errors="coerce")
        except (ValueError, TypeError):
            dt = pd.NaT
        if pd.isna(dt):
            continue
        date_iso = dt.strftime("%Y-%m-%d")
        reason = str(r[reason_col]).strip() if reason_col else ""

        add_t = str(r[added_ticker]).strip()
        if add_t and add_t.lower() not in ("nan", ""):
            rows.append({
                "date": date_iso,
                "action": "add",
                "ticker": add_t,
                "security": (str(r[added_security]).strip()
                             if added_security else ""),
                "reason": reason,
            })

        rem_t = str(r[removed_ticker]).strip()
        if rem_t and rem_t.lower() not in ("nan", ""):
            rows.append({
                "date": date_iso,
                "action": "remove",
                "ticker": rem_t,
                "security": (str(r[removed_security]).strip()
                             if removed_security else ""),
                "reason": reason,
            })

    out = pd.DataFrame(rows)
    out = out.sort_values(["date", "action", "ticker"]).reset_index(drop=True)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", default=str(OUT_DIR))
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    current_raw, changes_raw = _scrape()
    current = _normalize_current(current_raw)
    changes = _normalize_changes(changes_raw)

    earliest = changes["date"].min() if not changes.empty else "N/A"
    latest = changes["date"].max() if not changes.empty else "N/A"
    logger.info("Current constituents: %d", len(current))
    logger.info("Changes: %d events, earliest=%s latest=%s",
                len(changes), earliest, latest)

    # Write with quoting=QUOTE_MINIMAL — security names contain commas.
    current.to_csv(
        out_dir / CURRENT_CSV.name,
        index=False, quoting=csv.QUOTE_MINIMAL,
    )
    changes.to_csv(
        out_dir / CHANGES_CSV.name,
        index=False, quoting=csv.QUOTE_MINIMAL,
    )

    now = datetime.now(timezone.utc).isoformat()
    (out_dir / META_TXT.name).write_text(
        f"source: {WIKIPEDIA_URL}\n"
        f"fetched_at_utc: {now}\n"
        f"current_count: {len(current)}\n"
        f"changes_count: {len(changes)}\n"
        f"changes_earliest: {earliest}\n"
        f"changes_latest: {latest}\n"
        f"WARNING: Wikipedia 'Selected changes' table is NOT comprehensive. "
        f"Do not claim PIT coverage older than changes_earliest.\n",
        encoding="utf-8",
    )
    logger.info("Wrote %s, %s, %s",
                out_dir / CURRENT_CSV.name,
                out_dir / CHANGES_CSV.name,
                out_dir / META_TXT.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
