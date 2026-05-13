"""Convert yfinance options chain data into the options_skew analyzer's shape.

Each call to ``yf.Ticker(t).options`` yields a tuple of expiry-date
strings; ``yf.Ticker(t).option_chain(expiry)`` then returns a
``(calls_df, puts_df)`` namedtuple. The fetcher walks every expiry and
builds an ``OptionsChain`` with the union of contracts.

Performance: each ticker requires 1 + N HTTP calls (1 for the expiry
list, then 1 per expiry actually loaded). For a 50-ticker scan with
~8 expiries fetched each, that's ~450 HTTP calls — meaningful but
manageable with parallelism. The analyzer only needs the nearest
21+d expiry, so we can stop after finding the first qualifier and
its neighbor, capping the per-ticker cost at 2-3 HTTP calls.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Optional

import pandas as pd

from src.scoring.analyzers.options_skew import (
    OptionContract,
    OptionsChain,
)

logger = logging.getLogger(__name__)

# Minimum number of expiries to load per ticker so the analyzer's
# "nearest 21+d expiry" pick has a backup if the front one is unusable.
_MAX_EXPIRIES_TO_LOAD = 3


def _df_to_contracts(
    df: pd.DataFrame,
    expiry: date,
    contract_type: str,
) -> list[OptionContract]:
    """Walk one calls or puts DataFrame and emit OptionContracts.

    yfinance column names: 'strike', 'impliedVolatility', 'volume',
    'openInterest', 'lastPrice', 'inTheMoney'. Some fields are nullable
    on illiquid contracts."""
    out: list[OptionContract] = []
    if df is None or df.empty:
        return out
    for _, row in df.iterrows():
        strike = row.get("strike")
        iv = row.get("impliedVolatility")
        if pd.isna(strike) or pd.isna(iv) or iv is None or iv <= 0:
            continue
        try:
            strike_f = float(strike)
            iv_f = float(iv)
        except (TypeError, ValueError):
            continue
        volume = row.get("volume", 0)
        oi = row.get("openInterest", 0)
        out.append(
            OptionContract(
                strike=strike_f,
                expiry=expiry,
                contract_type=contract_type,  # type: ignore[arg-type]
                implied_volatility=iv_f,
                volume=int(volume) if pd.notna(volume) and volume is not None else 0,
                open_interest=int(oi) if pd.notna(oi) and oi is not None else 0,
                delta=None,  # yfinance doesn't expose deltas
            )
        )
    return out


def _parse_expiry(expiry_str: str) -> date | None:
    try:
        return datetime.strptime(expiry_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def fetch_chain(ticker: str, *, min_days: int = 21) -> Optional[OptionsChain]:
    """Fetch one ticker's options chain. Returns None when no usable
    expiry exists or yfinance refuses the symbol (futures, ETFs that
    don't list options, foreign ADRs without US options trading).

    Loads the nearest two expiries that satisfy ``min_days`` — enough
    for the analyzer to pick its target expiry without us preempting
    that decision here.
    """
    import yfinance as yf

    try:
        t = yf.Ticker(ticker)
        expiries_raw = t.options
        if not expiries_raw:
            return None
        today = date.today()
        # Filter to expiries with >=min_days, take first N
        qualifying: list[tuple[str, date]] = []
        for e_str in expiries_raw:
            d = _parse_expiry(e_str)
            if d is None:
                continue
            if (d - today).days < min_days:
                continue
            qualifying.append((e_str, d))
            if len(qualifying) >= _MAX_EXPIRIES_TO_LOAD:
                break
        if not qualifying:
            return None
        contracts: list[OptionContract] = []
        for e_str, e_date in qualifying:
            try:
                chain = t.option_chain(e_str)
            except Exception as e:
                logger.debug("option_chain(%s, %s) failed: %s", ticker, e_str, e)
                continue
            contracts.extend(_df_to_contracts(chain.calls, e_date, "call"))
            contracts.extend(_df_to_contracts(chain.puts, e_date, "put"))
        if not contracts:
            return None
        return OptionsChain(
            underlying=ticker.upper(),
            snapshot_time=datetime.now(),
            contracts=tuple(contracts),
        )
    except Exception as e:
        logger.debug("chain fetch failed for %s: %s", ticker, e)
        return None


def fetch_chains_batch(
    tickers: list[str],
    *,
    max_workers: int = 6,
    min_days: int = 21,
) -> dict[str, OptionsChain]:
    """Parallel fetch over a ticker universe.

    Excludes tickers without options (most ETFs, foreign ADRs, recently
    IPO'd names) — they map to no entry rather than an empty OptionsChain.
    """
    results: dict[str, OptionsChain] = {}
    if not tickers:
        return results
    workers = min(max_workers, len(tickers))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fetch_chain, t, min_days=min_days): t for t in tickers}
        for fut in as_completed(futures):
            ticker = futures[fut]
            try:
                chain = fut.result()
            except Exception as e:
                logger.debug("worker error %s: %s", ticker, e)
                chain = None
            if chain is not None:
                results[ticker] = chain
    logger.info(
        "options_chains: fetched chains for %d/%d tickers",
        len(results), len(tickers),
    )
    return results
