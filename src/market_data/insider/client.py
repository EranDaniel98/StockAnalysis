"""Form 4 listing + document fetch.

Built on top of ``EDGARClient`` rather than as a separate HTTP layer —
shares the same User-Agent, rate limiter, and connection pool.

Two operations:
  * ``list_form4_filings(cik)`` — returns accession numbers + filing
    dates for all Form 4 / 4/A filings in the company's recent
    submissions index.
  * ``fetch_form4_xml(cik, accession_no)`` — fetches the structured
    Form 4 XML (which lives at a predictable path under the filing's
    archive folder).

Why we resolve the XML path from a directory listing rather than
trusting ``primaryDocument`` from submissions JSON: EDGAR's Form 4
filings sometimes set primaryDocument to an HTML wrapper rather than
the underlying XML. Grabbing the directory index lets us find the
machine-readable XML reliably.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from src.contracts.errors import ExternalAPIError
from src.market_data.edgar.client import EDGARClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Form4Filing:
    """Lightweight handle to a Form 4 filing — just enough to fetch
    the XML or pass to the parser."""

    accession_no: str  # e.g. "0001214156-24-000123"
    filing_date: date
    form: str  # "4" or "4/A"
    primary_document: str  # path inside the archive folder


def _filings_from_submissions(submissions: dict[str, Any]) -> list[Form4Filing]:
    """Pluck Form 4 / 4/A entries out of an EDGAR submissions JSON.

    Schema (excerpt):
        {
          "filings": {
            "recent": {
              "accessionNumber": ["...", ...],
              "filingDate": ["YYYY-MM-DD", ...],
              "form": ["4", "10-Q", ...],
              "primaryDocument": ["..."]
            }
          }
        }
    """
    recent = (submissions.get("filings") or {}).get("recent") or {}
    accessions = recent.get("accessionNumber") or []
    filing_dates = recent.get("filingDate") or []
    forms = recent.get("form") or []
    primary_docs = recent.get("primaryDocument") or []

    out: list[Form4Filing] = []
    for accn, fd_str, form, primary in zip(
        accessions, filing_dates, forms, primary_docs
    ):
        if form not in ("4", "4/A"):
            continue
        try:
            fd = date.fromisoformat(fd_str)
        except ValueError:
            continue
        out.append(Form4Filing(
            accession_no=accn,
            filing_date=fd,
            form=form,
            primary_document=primary or "",
        ))
    return out


_XML_HREF_RE = re.compile(
    r'href="([^"]+\.xml)"', re.IGNORECASE,
)


async def list_form4_filings(
    client: EDGARClient,
    cik: int | str,
    *,
    since: date | None = None,
) -> list[Form4Filing]:
    """Return Form 4 / 4/A filings for one CIK.

    ``since`` filters to filings on or after a given date — useful for
    incremental backfills that don't want to re-list older filings on
    every run. The EDGAR submissions index covers the most recent ~1000
    filings; older filings live in paginated overflow JSON files we
    don't fetch today (Form 4 cadence is dense enough that the recent
    block usually spans 2-5 years for an actively-trading large-cap).
    """
    submissions = await client.fetch_submissions(int(cik))
    filings = _filings_from_submissions(submissions)
    if since is not None:
        filings = [f for f in filings if f.filing_date >= since]
    return filings


def _archive_dir_url(cik: int | str, accession_no: str) -> str:
    cik_str = str(int(cik))
    accession_clean = accession_no.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik_str}/{accession_clean}/"
    )


async def fetch_form4_xml(
    client: EDGARClient,
    cik: int | str,
    accession_no: str,
    *,
    primary_document: str | None = None,
) -> str:
    """Fetch the Form 4 XML body for one filing.

    Strategy:
      1. If ``primary_document`` ends in ``.xml``, take just the
         file's basename (strip any ``xslF345X05/`` subdirectory —
         that path serves the XSL-rendered HTML, not the raw XML).
      2. Otherwise list the archive directory and pick the first
         root-level ``.xml`` file (again skipping ``xsl*`` subdirs
         and the ``FilingSummary.xml`` metadata file).

    Raises ``ExternalAPIError`` on HTTP failure or when no XML can be
    located — caller catches and skips so one broken filing doesn't
    sink a batch backfill.
    """
    if primary_document and primary_document.lower().endswith(".xml"):
        # The raw XML lives at the root of the accession folder. EDGAR's
        # submissions JSON sometimes points primaryDocument at the XSL
        # subpath (e.g. "xslF345X05/form4.xml") which serves rendered
        # HTML — drop the prefix so we hit the raw XML.
        xml_name = primary_document.rsplit("/", 1)[-1]
        return await client.fetch_filing_text(
            int(cik), accession_no, xml_name
        )

    # Need to discover the XML filename — list the archive dir.
    dir_url = _archive_dir_url(cik, accession_no)
    await client._rate.acquire()  # type: ignore[attr-defined]
    resp = await client._client.get(dir_url)  # type: ignore[attr-defined]
    if resp.status_code != 200:
        raise ExternalAPIError(
            f"Form 4 archive listing returned {resp.status_code} for {accession_no}"
        )
    candidates = []
    for href in _XML_HREF_RE.findall(resp.text):
        lower = href.lower()
        if lower.endswith("filingsummary.xml"):
            continue
        # The xslF* subdirectories serve XSL-rendered HTML — skip them.
        # We want the root-level raw XML only.
        basename = href.rsplit("/", 1)[-1]
        path_only = href.rsplit("/", 1)[0] if "/" in href else ""
        if path_only and path_only.lower().lstrip("/").startswith("xsl"):
            continue
        candidates.append(basename)
    if not candidates:
        raise ExternalAPIError(
            f"No raw XML document found in Form 4 archive for {accession_no}"
        )
    return await client.fetch_filing_text(int(cik), accession_no, candidates[0])
