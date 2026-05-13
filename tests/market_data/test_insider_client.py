"""Unit tests for src.market_data.insider.client.

Only covers the pure helpers (submissions filter, archive URL builder).
The HTTP-fetch paths share infrastructure with EDGARClient which has
its own coverage; testing them again here would just retest httpx.
"""

from __future__ import annotations

from datetime import date

from src.market_data.insider.client import (
    Form4Filing,
    _archive_dir_url,
    _filings_from_submissions,
)


class TestFilingsFromSubmissions:
    def test_extracts_only_form4_entries(self) -> None:
        submissions = {
            "filings": {
                "recent": {
                    "accessionNumber": ["a-1", "a-2", "a-3", "a-4"],
                    "filingDate": ["2024-01-15", "2024-01-16", "2024-01-17", "2024-01-18"],
                    "form": ["4", "10-Q", "4/A", "8-K"],
                    "primaryDocument": ["x.xml", "y.htm", "z.xml", "w.htm"],
                }
            }
        }
        filings = _filings_from_submissions(submissions)
        assert [f.accession_no for f in filings] == ["a-1", "a-3"]
        assert [f.form for f in filings] == ["4", "4/A"]
        assert all(isinstance(f.filing_date, date) for f in filings)

    def test_handles_missing_keys_gracefully(self) -> None:
        """Old/empty submissions JSON shapes shouldn't crash."""
        assert _filings_from_submissions({}) == []
        assert _filings_from_submissions({"filings": {}}) == []
        assert _filings_from_submissions(
            {"filings": {"recent": {}}}
        ) == []

    def test_skips_invalid_dates(self) -> None:
        submissions = {
            "filings": {
                "recent": {
                    "accessionNumber": ["a-1", "a-2"],
                    "filingDate": ["2024-01-15", "not-a-date"],
                    "form": ["4", "4"],
                    "primaryDocument": ["x.xml", "y.xml"],
                }
            }
        }
        filings = _filings_from_submissions(submissions)
        assert len(filings) == 1
        assert filings[0].accession_no == "a-1"


class TestArchiveDirUrl:
    def test_strips_dashes_from_accession(self) -> None:
        url = _archive_dir_url(320193, "0000320193-24-000001")
        assert url == "https://www.sec.gov/Archives/edgar/data/320193/000032019324000001/"
