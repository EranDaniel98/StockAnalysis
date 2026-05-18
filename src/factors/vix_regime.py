"""VIX-percentile regime gate for factor strategies.

Motivation (2026-05-18 IC regime report): the m+q+v composite's
fundamental analyzer is STRONG at 44D in low_vix (IC +0.058) but
collapses to WEAK in high_vix (IC +0.017) — a 3.5x degradation.
Composite IC goes NEGATIVE in high_vix at every horizon past 5D.

Existing trend-state regime (200d SMA, ``regime.py``) was net-negative
in the 2022-2026 backtest because it whipsaws through V-shaped
corrections. A VIX-based gate avoids that by reacting to volatility
itself rather than a derived price-trend signal — the high-vol periods
that should trigger us out are exactly when SMA whipsaws are loudest.

This module ships two complementary primitives so the backtest +
production paths can pick the same gate:

* ``vix_percentile_series`` — rolling-window percentile of VIX close.
* ``is_calm`` — True iff today's VIX percentile is below the cutoff.

Choose the cutoff conservatively: 0.80 means "block entries in the
top 20% most-volatile days of the lookback window." Higher cutoffs
reduce the gate's bite; lower cutoffs (0.60-0.70) start blocking too
many bull-market dips.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_WINDOW = 252  # trading days = 1 year of history
DEFAULT_CUTOFF = 0.80  # block when VIX is in the top 20% of the window

# Absolute-VIX gate defaults. The percentile gate above self-normalizes
# (a year of sustained 25-35 VIX reads as median); these knobs trade
# normalization for an absolute level + smoothing window. Threshold 28
# on a 21-day rolling mean catches deep stress (e.g., May 2022, VIX
# 21d-MA peaked at 28.3) while ignoring transient spikes (Aug 2024
# Japan-carry blew raw VIX to 52 for two days but the 21d-MA never
# exceeded 19.4 by the next rebalance date). See the 2026-05-18
# regime-gating battery for the calibration table.
DEFAULT_ABSOLUTE_THRESHOLD = 28.0
DEFAULT_SMOOTHING_WINDOW = 21


def vix_percentile_series(
    vix_df: pd.DataFrame | pd.Series,
    *,
    window: int = DEFAULT_WINDOW,
) -> pd.Series:
    """Rolling-window percentile rank of VIX close, in [0, 1].

    A value of 0.95 means "today's VIX is in the 95th percentile of the
    last ``window`` trading days." The first ``window - 1`` rows are NaN.
    Callers should align with their backtest schedule and forward-fill
    weekend/holiday gaps.
    """
    if isinstance(vix_df, pd.DataFrame):
        if "Close" not in vix_df.columns:
            raise ValueError("vix_df needs a 'Close' column")
        close = vix_df["Close"].astype(float)
    else:
        close = vix_df.astype(float)
    if close.empty:
        return pd.Series(dtype="float64")
    # pct_rank inside a rolling window. apply over rolling().rank()
    # would be O(N*W); pandas's rolling.rank exists in 1.4+ and is
    # vectorized.
    pct = close.rolling(window=window, min_periods=window).rank(pct=True)
    return pct


def is_calm(
    vix_df: pd.DataFrame | pd.Series,
    as_of: pd.Timestamp | str,
    *,
    window: int = DEFAULT_WINDOW,
    cutoff: float = DEFAULT_CUTOFF,
) -> bool:
    """True iff VIX at-or-before ``as_of`` is below the percentile cutoff.

    Returns True (permissive default) when there's no VIX data yet at
    as_of — the gate should not gate-out a strategy purely because
    the data feed is cold. Backtests should align as_of to a trading
    day where VIX data is available; ``vix_percentile_series`` is the
    underlying primitive when the caller needs the raw number.
    """
    as_of_ts = pd.Timestamp(as_of)
    series = vix_percentile_series(vix_df, window=window)
    eligible = series[series.index <= as_of_ts].dropna()
    if eligible.empty:
        logger.warning(
            "is_calm: no VIX-percentile data on or before %s "
            "(window=%d) — defaulting to calm.",
            as_of_ts.date(), window,
        )
        return True
    latest_pct = float(eligible.iloc[-1])
    calm = latest_pct < cutoff
    if not calm:
        logger.info(
            "is_calm: VIX percentile %.2f >= cutoff %.2f at %s — "
            "regime gate blocking entries.",
            latest_pct, cutoff, as_of_ts.date(),
        )
    return calm


def vix_smoothed_series(
    vix_df: pd.DataFrame | pd.Series,
    *,
    window: int = DEFAULT_SMOOTHING_WINDOW,
) -> pd.Series:
    """Rolling-mean of VIX close. Lower-pass filter so the gate reads
    SUSTAINED elevation, not single-day spikes.

    Designed for absolute-threshold use: the raw VIX hit 52 on
    2024-08-05 (Japan-carry unwind) but the 21d-MA peaked at 19.4 days
    later -- so a 28-threshold gate doesn't fire on transient panic.
    """
    if isinstance(vix_df, pd.DataFrame):
        if "Close" not in vix_df.columns:
            raise ValueError("vix_df needs a 'Close' column")
        close = vix_df["Close"].astype(float)
    else:
        close = vix_df.astype(float)
    if close.empty:
        return pd.Series(dtype="float64")
    return close.rolling(window=window, min_periods=window).mean()


def is_stress_absolute(
    vix_df: pd.DataFrame | pd.Series,
    as_of: pd.Timestamp | str,
    *,
    threshold: float = DEFAULT_ABSOLUTE_THRESHOLD,
    window: int = DEFAULT_SMOOTHING_WINDOW,
) -> bool:
    """True iff the smoothed VIX at-or-before ``as_of`` is >= threshold.

    Complement to ``is_calm``: that one normalizes against a trailing
    year (so sustained 2022 stress reads as median); this one uses an
    absolute level (so 2022 actually fires). Smoothing the input is
    what protects against single-day false positives.

    Returns False (permissive default) when smoothing hasn't warmed up
    yet OR no VIX data is present -- same default-to-calm semantic as
    ``is_calm``, so a missing data feed never gates the strategy out
    by mistake.
    """
    as_of_ts = pd.Timestamp(as_of)
    series = vix_smoothed_series(vix_df, window=window)
    eligible = series[series.index <= as_of_ts].dropna()
    if eligible.empty:
        logger.warning(
            "is_stress_absolute: no smoothed-VIX data on or before %s "
            "(window=%d) -- defaulting to calm.",
            as_of_ts.date(), window,
        )
        return False
    latest = float(eligible.iloc[-1])
    stressed = latest >= threshold
    if stressed:
        logger.info(
            "is_stress_absolute: VIX %dd-MA %.1f >= %.1f at %s -- gate firing.",
            window, latest, threshold, as_of_ts.date(),
        )
    return stressed


__all__ = [
    "vix_percentile_series",
    "vix_smoothed_series",
    "is_calm",
    "is_stress_absolute",
    "DEFAULT_WINDOW",
    "DEFAULT_CUTOFF",
    "DEFAULT_ABSOLUTE_THRESHOLD",
    "DEFAULT_SMOOTHING_WINDOW",
]
