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


def short_atr_bracket_levels(
    *,
    entry: float,
    ohlc: pd.DataFrame,
    atr_multiplier: float = 2.0,
    risk_reward: float = 3.0,
    period: int = 14,
) -> Optional[BracketLevels]:
    """Compute (stop_above_entry, TP_below_entry) for a SHORT position.

    Mirror image of ``atr_bracket_levels``: when you short at entry, your
    catastrophe risk is the price RISING, so the stop is ``entry +
    atr_multiplier * ATR``. Profit is the price FALLING, so the TP is
    ``entry - risk_reward * (stop - entry)``.

    Returns None when ATR can't be formed OR when the TP would imply a
    negative price (i.e., a stop so wide that 3x its risk goes through
    zero). Refuse to ship junk levels rather than silently round.
    """
    if entry <= 0 or ohlc.empty:
        return None
    needed = {"High", "Low", "Close"}
    if not needed.issubset(ohlc.columns):
        return None
    atr = _atr14(ohlc["High"], ohlc["Low"], ohlc["Close"], period=period)
    if atr is None:
        return None
    stop = entry + atr_multiplier * atr
    take_profit = entry - risk_reward * (stop - entry)
    if take_profit <= 0:
        return None
    return BracketLevels(
        stop=round(stop, 2),
        take_profit=round(take_profit, 2),
        basis="atr",
    )


def short_percentage_bracket_levels(
    *,
    entry: float,
    stop_pct: float = 0.10,
    risk_reward: float = 3.0,
) -> Optional[BracketLevels]:
    """Mirror of percentage_bracket_levels for shorts.

    ``stop_pct=0.10`` => stop at ``entry * 1.10`` (10% above), TP at
    ``entry - 3 * 0.10 * entry = 0.70 * entry``. Caps short loss at 10%
    of entry notional with 3:1 R/R on the down side.
    """
    if entry <= 0 or not (0 < stop_pct < 1):
        return None
    stop = entry * (1.0 + stop_pct)
    take_profit = entry - risk_reward * (stop - entry)
    if take_profit <= 0:
        return None
    return BracketLevels(
        stop=round(stop, 2),
        take_profit=round(take_profit, 2),
        basis="percentage",
    )


@dataclass(frozen=True)
class PositionPlan:
    """Output of ``size_position``. Either a sized order or an explicit
    skip with a human-readable reason."""

    target_shares: int       # signed: positive = long, negative = short
    delta_shares: int        # target - current; what we'd trade
    skip_reason: Optional[str]  # set when the plan can't open a position


def size_position(
    *,
    price: float,
    per_slot: float,
    current_shares: int,
    is_long: bool,
) -> PositionPlan:
    """Decide the target share count for one ticker.

    Parameters
    ----------
    price : current quote per share. Must be > 0.
    per_slot : dollar capital allocated per position (per-long or
        per-short side).
    current_shares : signed share count currently held — positive for a
        long position, negative for a short. 0 = flat.
    is_long : True = build a long target (positive shares); False = build
        a short target (negative shares).

    Returns
    -------
    PositionPlan with one of two outcomes:

    1. **sized** — ``target_shares`` and ``delta_shares`` populated, no
       skip_reason. The caller submits ``abs(delta_shares)`` in the
       direction of ``sign(delta_shares)``.
    2. **skipped** — ``skip_reason`` populated. This happens when the
       ticker's price exceeds the slot so ``int(per // price) == 0``
       AND we'd be opening a brand-new position. The pick is reported
       to the operator instead of silently sized to zero.

    A held position we can no longer resize at the same direction
    (price exceeds slot but we already own some) still returns a
    sized plan — ``target_shares = 0`` so the delta closes the
    existing position. That's safer than holding ghost positions.

    Edge: when the operator targets a SHORT but currently holds a
    LONG of the same name (or vice versa), the delta closes the
    wrong-direction position AND opens the targeted side simultaneously
    only if the slot fits. If the slot doesn't fit, the existing
    position is closed and no new one is opened (we don't carry the
    operator's intent through a partial fill).
    """
    if price <= 0:
        return PositionPlan(
            target_shares=0, delta_shares=0,
            skip_reason=f"non_positive_price ({price})",
        )
    if per_slot <= 0:
        return PositionPlan(
            target_shares=0, delta_shares=0,
            skip_reason=f"non_positive_slot ({per_slot})",
        )

    magnitude = int(per_slot // price)
    target_shares = magnitude if is_long else -magnitude
    delta_shares = target_shares - current_shares

    if magnitude == 0 and current_shares == 0:
        return PositionPlan(
            target_shares=0, delta_shares=0,
            skip_reason=(
                f"price ${price:.2f} exceeds per-position slot "
                f"${per_slot:.2f} (would size 0 shares — increase "
                f"capital allocation or accept this name's skip)"
            ),
        )

    return PositionPlan(
        target_shares=target_shares,
        delta_shares=delta_shares,
        skip_reason=None,
    )


def is_position_flip(current_shares: int, target_shares: int) -> bool:
    """True when current and target are on opposite sides of flat.

    Alpaca rejects a bracket order on a name with existing same-direction-
    opposite shares (e.g., bracket sell on +4 long) with ``bracket orders
    must be entry orders``. The caller must close the existing position
    FIRST, then submit the bracket as a clean entry.

    Strict definition: both must be non-zero AND have opposite signs.
    Zero on either side is NOT a flip — it's an open or a close, not both.
    """
    if current_shares == 0 or target_shares == 0:
        return False
    return (current_shares > 0) != (target_shares > 0)


__all__ = [
    "BracketLevels",
    "PositionPlan",
    "atr_bracket_levels",
    "is_position_flip",
    "percentage_bracket_levels",
    "short_atr_bracket_levels",
    "short_percentage_bracket_levels",
    "size_position",
]
