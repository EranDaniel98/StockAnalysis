"""SEC DERA financial-statement-dataset bulk ingestor.

A parallel ingestion path to ``src.market_data.edgar``. Instead of one HTTP
request per CIK against ``data.sec.gov/api/xbrl/companyfacts/...``, this
package consumes the quarterly bulk zips published at

    https://www.sec.gov/files/dera/data/financial-statement-data-sets/

Each zip contains every 10-K / 10-Q filing's XBRL facts for one calendar
quarter (sub.txt + num.txt). For a backfill across the full Russell 1000
that's ~1 download per quarter (~40 downloads for a 10-year history)
instead of ~1000 individual companyfacts requests.

Output type is the same ``FundamentalSnapshot`` produced by the existing
``parser.parse_company_facts`` — repositories and downstream code are
shape-compatible.

Modules:
  client  — manages the local zip cache + download URL resolution.
  parser  — reads sub.txt + num.txt from an open zip handle, joins,
            produces ``list[FundamentalSnapshot]`` per ticker.
  ingest  — orchestrator: open zip, parse, filter to ticker universe,
            upsert via PostgresFundamentalsRepository.
"""

from src.market_data.edgar_bulk.client import (
    BulkArchiveClient,
    quarter_url,
)
from src.market_data.edgar_bulk.parser import parse_quarter_zip

__all__ = [
    "BulkArchiveClient",
    "parse_quarter_zip",
    "quarter_url",
]
