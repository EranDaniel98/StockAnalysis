"""Market-regime classifier — pure functions over SPY + VIX history.

The same rule used by the API ``/api/market/regime`` snapshot and by the
backtest entry gate. Keeping it in one module means a future tweak to the
rule (different SMA period, different VIX threshold, regime persistence)
shifts both the live recommendation and the backtest measurement in
lock-step — you cannot accidentally backtest a different policy than the
one you trade.

``classify_at`` is the backtest-friendly entry: takes already-fetched
DataFrames + an ``as_of`` date, returns a snapshot using only data
strictly before ``as_of`` (no look-ahead). The API path calls
``classify_at`` with ``as_of=now`` and pre-fetched frames.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

import pandas as pd

RegimeLabel = Literal["bull", "bear", "chop", "unknown"]


@dataclass(frozen=True)
class RegimeParams:
    """Tunable classifier inputs. Sourced from ``config/settings.yaml``
    via ``Config.get_regime_filter()`` — defaults match the project's
    long-running convention (SMA200 + VIX 20/25 bands)."""

    sma_period: int = 200
    vix_low: float = 20.0
    vix_high: float = 25.0


@dataclass(frozen=True)
class RegimeSnapshot:
    """Classification result for a single ``as_of`` timestamp.

    ``label`` is the categorical regime; the numeric inputs are kept so
    the caller can render them in UI / log them with the trade record
    (audit trail — important when a gate fires).
    """

    label: RegimeLabel
    spy_price: Optional[float] = None
    spy_sma: Optional[float] = None
    spy_above_sma: Optional[bool] = None
    spy_pct_from_sma: Optional[float] = None
    vix_level: Optional[float] = None
    notes: list[str] = field(default_factory=list)


def _normalize_index(df: pd.DataFrame) -> pd.DataFrame:
    """Make the DataFrame index a tz-naive DatetimeIndex.

    Both yfinance and the project's Parquet store can return tz-aware
    UTC indices; the backtest works in tz-naive Timestamps for safe
    comparisons. We normalize defensively so the classifier doesn't
    care which path supplied the data.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    return df


def _last_value_before(
    df: Optional[pd.DataFrame], column: str, as_of: pd.Timestamp
) -> Optional[float]:
    if df is None or df.empty or column not in df.columns:
        return None
    df = _normalize_index(df)
    slice_ = df.loc[df.index <= as_of, column].dropna()
    if slice_.empty:
        return None
    return float(slice_.iloc[-1])


def _sma_before(
    df: Optional[pd.DataFrame], column: str, as_of: pd.Timestamp, period: int
) -> Optional[float]:
    if df is None or df.empty or column not in df.columns:
        return None
    df = _normalize_index(df)
    series = df.loc[df.index <= as_of, column].dropna()
    if len(series) < period:
        return None
    return float(series.tail(period).mean())


def _classify(
    spy_above_sma: Optional[bool],
    vix_level: Optional[float],
    params: RegimeParams,
) -> tuple[RegimeLabel, list[str]]:
    notes: list[str] = []
    if spy_above_sma is None or vix_level is None:
        notes.append("missing inputs — regime undetermined")
        return "unknown", notes

    if spy_above_sma and vix_level < params.vix_low:
        notes.append(
            f"SPY > {params.sma_period}-SMA and VIX < {params.vix_low} → risk-on"
        )
        return "bull", notes
    if (not spy_above_sma) and vix_level > params.vix_high:
        notes.append(
            f"SPY < {params.sma_period}-SMA and VIX > {params.vix_high} → risk-off"
        )
        return "bear", notes

    if spy_above_sma:
        notes.append(
            f"SPY above trend but VIX {vix_level:.1f} ≥ {params.vix_low} → caution"
        )
    else:
        notes.append(
            f"SPY below trend, VIX {vix_level:.1f} not panic yet → caution"
        )
    return "chop", notes


def classify_at(
    spy_df: Optional[pd.DataFrame],
    vix_df: Optional[pd.DataFrame],
    as_of: pd.Timestamp,
    params: RegimeParams | None = None,
) -> RegimeSnapshot:
    """Classify the regime as of ``as_of`` using only data with index
    ``<= as_of`` (no look-ahead).

    Both DataFrames are expected to have a 'Close' column (matches the
    yfinance + Parquet schemas). ``vix_df`` should be the ^VIX series.
    Missing inputs degrade gracefully to ``label='unknown'`` so the
    caller can decide whether to gate (most callers do NOT gate on
    unknown — that would silently turn a data outage into a flat
    portfolio).
    """
    params = params or RegimeParams()
    as_of = pd.Timestamp(as_of)
    if as_of.tz is not None:
        as_of = as_of.tz_localize(None)

    spy_price = _last_value_before(spy_df, "Close", as_of)
    spy_sma = _sma_before(spy_df, "Close", as_of, params.sma_period)
    vix_level = _last_value_before(vix_df, "Close", as_of)

    spy_above_sma: Optional[bool] = None
    spy_pct: Optional[float] = None
    if spy_price is not None and spy_sma is not None and spy_sma > 0:
        spy_above_sma = spy_price > spy_sma
        spy_pct = (spy_price / spy_sma - 1.0) * 100

    label, notes = _classify(spy_above_sma, vix_level, params)

    return RegimeSnapshot(
        label=label,
        spy_price=spy_price,
        spy_sma=spy_sma,
        spy_above_sma=spy_above_sma,
        spy_pct_from_sma=spy_pct,
        vix_level=vix_level,
        notes=notes,
    )


GateMode = Literal["off", "skip_bear", "skip_bear_and_chop"]


def gate_allows_entry(label: RegimeLabel, mode: GateMode) -> bool:
    """True when a fresh entry is permitted under the given gate mode.

    'unknown' always allows entry — the gate should not turn data
    outages into forced flat exposure. If you want strict behavior,
    feed the classifier the data it needs.
    """
    if mode == "off":
        return True
    if mode == "skip_bear":
        return label != "bear"
    if mode == "skip_bear_and_chop":
        return label not in ("bear", "chop")
    return True
