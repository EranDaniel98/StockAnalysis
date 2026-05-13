"""Live-only yfinance fetcher for the options_skew analyzer.

yfinance's Ticker.option_chain(expiry) returns calls + puts DataFrames
for the current chain. Historical chains are NOT available via yfinance
free — the options_skew analyzer is therefore live-scan only and is
never called by the backtest engine.
"""

from src.market_data.options_chains_yf.fetcher import (
    fetch_chain,
    fetch_chains_batch,
)

__all__ = ["fetch_chain", "fetch_chains_batch"]
