"""Continuous VIX-based exposure scaling.

Motivation
----------
Bull-DD diagnostic (`reports/bull_dd_diagnostic_2026_05_19.md`)
showed ~70% of d03's wider 2024-26 drawdown was mechanical: higher
beta from concentration -> more market exposure during corrections.
Binary gates (VIX percentile / VIX absolute) failed in the
regime-gating battery (memory `project_regime_gating_battery`)
because a single missed rebalance during V-shape recovery costs
~32pp.

Continuous scaling avoids the binary failure mode. Below a calm
threshold, run full exposure. Between calm and stress, linearly
scale down. At or above a stress threshold, run at a floor (not
zero -- never fully gate so V-shape recoveries can still earn).

Calibration anchors (matching `vix_regime.is_stress_absolute`):
* `low_threshold` = 20.0 (median VIX in calm regimes)
* `high_threshold` = 30.0 (sustained stress; calibrated to fire on
  2022 spring and not on Aug-2024 carry spike when smoothed over 21d)
* `floor` = 0.3 (keep 30% capital deployed even at stress)
* `smoothing_window` = 21 (matches existing absolute gate default)

Usage:

>>> exp = exposure_for(vix_df, as_of=pd.Timestamp("2025-04-08"))
>>> exp  # e.g., 0.55 if smoothed VIX is partway between thresholds
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_LOW_THRESHOLD = 20.0
DEFAULT_HIGH_THRESHOLD = 30.0
DEFAULT_FLOOR = 0.30
DEFAULT_SMOOTHING_WINDOW = 21


def exposure_from_vix(
    vix_smoothed: float,
    *,
    low_threshold: float = DEFAULT_LOW_THRESHOLD,
    high_threshold: float = DEFAULT_HIGH_THRESHOLD,
    floor: float = DEFAULT_FLOOR,
) -> float:
    """Map a smoothed VIX value to an exposure multiplier in [floor, 1].

    Piecewise linear:
      vix <= low_threshold        -> 1.0          (full exposure)
      low < vix < high_threshold  -> linear ramp  (smooth derisking)
      vix >= high_threshold       -> floor        (minimum exposure)

    The linearity is deliberate -- a single-day VIX move from 25 to
    27 (mid-band) changes exposure by ~20pp. That keeps the response
    smooth enough to avoid the V-shape problem that binary gates have.
    """
    if high_threshold <= low_threshold:
        raise ValueError(
            f"high_threshold ({high_threshold}) must be > low_threshold "
            f"({low_threshold})"
        )
    if not 0.0 <= floor <= 1.0:
        raise ValueError(f"floor must be in [0, 1], got {floor}")
    if vix_smoothed <= low_threshold:
        return 1.0
    if vix_smoothed >= high_threshold:
        return floor
    # Linear ramp from 1.0 (at low) to floor (at high).
    progress = (vix_smoothed - low_threshold) / (high_threshold - low_threshold)
    return 1.0 - progress * (1.0 - floor)


def exposure_series(
    vix_df: pd.DataFrame | pd.Series,
    *,
    smoothing_window: int = DEFAULT_SMOOTHING_WINDOW,
    low_threshold: float = DEFAULT_LOW_THRESHOLD,
    high_threshold: float = DEFAULT_HIGH_THRESHOLD,
    floor: float = DEFAULT_FLOOR,
) -> pd.Series:
    """Daily exposure multiplier series, indexed by VIX dates.

    First ``smoothing_window - 1`` rows are NaN (insufficient smoothing
    history). Callers should treat NaN as "default to 1.0" (no data =
    no gate) and forward-fill weekend/holiday gaps if aligning to a
    backtest schedule.
    """
    if isinstance(vix_df, pd.DataFrame):
        if "Close" not in vix_df.columns:
            raise ValueError("vix_df needs a 'Close' column")
        close = vix_df["Close"].astype(float)
    else:
        close = vix_df.astype(float)
    if close.empty:
        return pd.Series(dtype="float64")
    smoothed = close.rolling(
        window=smoothing_window, min_periods=smoothing_window,
    ).mean()
    return smoothed.apply(
        lambda v: float("nan") if pd.isna(v) else exposure_from_vix(
            v, low_threshold=low_threshold,
            high_threshold=high_threshold, floor=floor,
        )
    )


def exposure_at(
    vix_df: pd.DataFrame | pd.Series,
    as_of: pd.Timestamp | str,
    *,
    smoothing_window: int = DEFAULT_SMOOTHING_WINDOW,
    low_threshold: float = DEFAULT_LOW_THRESHOLD,
    high_threshold: float = DEFAULT_HIGH_THRESHOLD,
    floor: float = DEFAULT_FLOOR,
) -> float:
    """Exposure multiplier for ``as_of``, defaulting to 1.0 if no data.

    Permissive default mirrors ``vix_regime.is_calm`` / ``is_stress_absolute``:
    a missing data feed should NOT silently derisk the strategy.
    """
    as_of_ts = pd.Timestamp(as_of)
    series = exposure_series(
        vix_df, smoothing_window=smoothing_window,
        low_threshold=low_threshold, high_threshold=high_threshold,
        floor=floor,
    )
    if series.empty:
        logger.warning(
            "exposure_at: empty VIX series -- defaulting to full exposure.",
        )
        return 1.0
    eligible = series[series.index <= as_of_ts].dropna()
    if eligible.empty:
        logger.warning(
            "exposure_at: no smoothed-VIX data on or before %s "
            "(window=%d) -- defaulting to full exposure (1.0).",
            as_of_ts.date(), smoothing_window,
        )
        return 1.0
    exp = float(eligible.iloc[-1])
    if exp < 1.0:
        logger.info(
            "exposure_at: VIX %dd-MA derisks exposure to %.2f at %s "
            "(low=%.1f high=%.1f floor=%.2f)",
            smoothing_window, exp, as_of_ts.date(),
            low_threshold, high_threshold, floor,
        )
    return exp


__all__ = [
    "exposure_from_vix",
    "exposure_series",
    "exposure_at",
    "DEFAULT_LOW_THRESHOLD",
    "DEFAULT_HIGH_THRESHOLD",
    "DEFAULT_FLOOR",
    "DEFAULT_SMOOTHING_WINDOW",
]
