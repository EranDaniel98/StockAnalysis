"""Per-position stop/TP sizing for bracket orders.

Pure-function helpers shared by the paper-trade runner and the live-trade
runner. The factor strategy is buy-and-hold-for-quarter; stops here are
catastrophe protection, not entry/exit timing.

Two paths exist intentionally:

* ``atr_bracket_levels`` — preferred. Takes an OHLC frame and returns
  (stop, take_profit) computed from ATR14 with the configured multipliers.
  This matches ``src/scoring/analyzers/technical.py:_calc_atr`` and the
  recommender's risk model.
* ``percentage_bracket_levels`` — fallback for tickers without enough
  price history. Symmetric percentage stop with the configured RR multiple
  on the upside.

Both return ``BracketLevels(stop, take_profit)`` so the caller can swap
between them on a per-ticker basis without branching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class BracketLevels:
    """Stop + take-profit prices for one bracket order."""

    stop: float
    take_profit: float
    basis: str  # "atr" | "percentage" — surfaced for diagnostics


def _atr14(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14,
) -> Optional[float]:
    """Wilder-style ATR over ``period`` bars. Returns ``None`` when there
    aren't enough bars to form a clean window."""
    if len(close) < period + 1:
        return None
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean().iloc[-1]
    if pd.isna(atr) or atr <= 0:
        return None
    return float(atr)


def atr_bracket_levels(
    *,
    entry: float,
    ohlc: pd.DataFrame,
    atr_multiplier: float = 2.0,
    risk_reward: float = 3.0,
    period: int = 14,
) -> Optional[BracketLevels]:
    """Compute (stop, TP) from ATR. Returns None when ATR can't be formed."""
    if entry <= 0 or ohlc.empty:
        return None
    needed = {"High", "Low", "Close"}
    if not needed.issubset(ohlc.columns):
        return None
    atr = _atr14(ohlc["High"], ohlc["Low"], ohlc["Close"], period=period)
    if atr is None:
        return None
    stop = entry - atr_multiplier * atr
    if stop <= 0:
        return None
    take_profit = entry + risk_reward * (entry - stop)
    return BracketLevels(
        stop=round(stop, 2),
        take_profit=round(take_profit, 2),
        basis="atr",
    )


def percentage_bracket_levels(
    *,
    entry: float,
    stop_pct: float = 0.10,
    risk_reward: float = 3.0,
) -> Optional[BracketLevels]:
    """Fallback: symmetric percentage stop with configured RR.

    The factor strategy default cap of 30% sector concentration + quarterly
    rebalance suggests catastrophe-protection sizing rather than active
    risk management. A 10% stop with 3:1 RR (= 30% TP) gives names room
    to breathe through normal vol while bounding tail risk.
    """
    if entry <= 0 or not (0 < stop_pct < 1):
        return None
    stop = entry * (1.0 - stop_pct)
    take_profit = entry + risk_reward * (entry - stop)
    return BracketLevels(
        stop=round(stop, 2),
        take_profit=round(take_profit, 2),
        basis="percentage",
    )


__all__ = ["BracketLevels", "atr_bracket_levels", "percentage_bracket_levels"]
