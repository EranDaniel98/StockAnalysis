"""Live-only yfinance fetcher for the analyst_revisions analyzer.

yfinance only exposes the current snapshot of analyst recommendations + a
short trailing history — sufficient for the analyzer's 60-day rolling
window in the scan path. Historical replay (backtest) is NOT supported
because yfinance does not archive analyst-revision timestamps. The
scoring service intentionally does not call this in the backtest engine.
"""

from src.market_data.analyst_revisions_yf.fetcher import (
    fetch_revisions,
    fetch_revisions_batch,
)

__all__ = ["fetch_revisions", "fetch_revisions_batch"]
