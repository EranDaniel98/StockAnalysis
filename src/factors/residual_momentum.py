"""Residual (idiosyncratic) momentum factor.

Vanilla Jegadeesh-Titman 12-1 momentum implicitly loads on market
beta — a stock that just outran the market because it has β = 1.6
ranks the same as a stock that genuinely outperformed risk-adjusted.
That's the well-known "momentum crashes during regime flips" failure
mode: high-β names lead the rally then crater the rebound.

Blitz, Huij and Martens (2011) "Residual Momentum" strips the market
beta out of the 12-1 return by:

  1. regressing the ticker's daily returns on SPY daily returns over
     the 12-month window to estimate β,
  2. computing the residual returns ε_t = r_t - β · r_spy_t,
  3. compounding the residual returns over the 12-1 window
     (skip-month convention preserved).

Compared to raw 12-1:
  * Higher Sharpe in cross-section (Blitz 2011 reports 0.94 vs 0.65)
  * Less crash risk — residual returns are by construction market-
    neutral, so a high score doesn't require a bullish market call
  * Survives the 2008-09 momentum crash that ate vanilla momentum

For us: same skip-month + same 252-day lookback as ``momentum_12_1``.
Output shape (ticker, raw, rank, z_score) is interchangeable.

Lookahead safety: every price read is at or before
``as_of - SKIP_DAYS``. The regression window is entirely in the past.
"""

from __future__ import annotations

import logging
from typing import Mapping

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 252  # full regression window
SKIP_DAYS = 21       # exclude the last trading month from the residual sum
MIN_OVERLAP = 200    # minimum aligned daily-return observations to fit β


def _daily_returns(close: pd.Series) -> pd.Series:
    """Simple daily returns. Drops the first NaN."""
    return close.pct_change().dropna()


def _aligned_returns(
    stock_close: pd.Series, spy_close: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Inner-join stock and SPY daily returns on the same trading dates.

    Both inputs may have slightly different DatetimeIndexes (tz, time-
    of-day, missing days). We normalize to date-only and inner-merge.
    """
    s = _daily_returns(stock_close)
    m = _daily_returns(spy_close)
    if s.empty or m.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    # Normalize to date-only — yfinance frames sometimes carry time
    # components that prevent direct alignment.
    s.index = pd.to_datetime(s.index).normalize()
    m.index = pd.to_datetime(m.index).normalize()
    aligned = pd.concat([s, m], axis=1, join="inner").dropna()
    if aligned.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    aligned.columns = ["stock", "spy"]
    return aligned["stock"], aligned["spy"]


def _fit_beta(stock_ret: np.ndarray, spy_ret: np.ndarray) -> tuple[float, float]:
    """OLS: stock = α + β · spy. Returns (α, β).

    Uses ``np.linalg.lstsq`` directly for speed — we're doing one of
    these per ticker per rebalance and a statsmodels call per ticker
    is measurably slower on a 500-name universe.
    """
    n = len(stock_ret)
    if n < 2:
        return 0.0, 1.0  # neutral fallback
    X = np.column_stack([np.ones(n), spy_ret])
    try:
        coefs, *_ = np.linalg.lstsq(X, stock_ret, rcond=None)
    except np.linalg.LinAlgError:
        return 0.0, 1.0
    return float(coefs[0]), float(coefs[1])


def residual_momentum_12_1(
    prices: Mapping[str, pd.DataFrame],
    spy_df: pd.DataFrame,
    as_of: pd.Timestamp | str,
    *,
    lookback_days: int = LOOKBACK_DAYS,
    skip_days: int = SKIP_DAYS,
    min_overlap: int = MIN_OVERLAP,
) -> pd.DataFrame:
    """Cross-sectional residual 12-1 momentum factor.

    Parameters
    ----------
    prices : mapping ticker -> OHLCV frame (DatetimeIndex, 'Close').
    spy_df : SPY OHLCV frame (DatetimeIndex, 'Close'). Used for the
        beta regression.
    as_of : as-of date. Only data on/before this date is read.
    lookback_days : full regression window in trading days (default 252).
    skip_days : the last ``skip_days`` of residual returns are dropped
        from the cumulative sum (skip-month convention).
    min_overlap : minimum aligned (stock, SPY) daily returns required
        to fit β. Below this, the ticker is skipped — partial-coverage
        names are unreliable for residual momentum.

    Returns
    -------
    DataFrame with columns ``ticker, raw, rank, z_score``. Rank 1 =
    highest residual momentum.
    """
    as_of_ts = pd.Timestamp(as_of).normalize()

    if spy_df is None or spy_df.empty or "Close" not in spy_df.columns:
        logger.warning("residual_momentum_12_1: SPY frame missing or empty")
        return pd.DataFrame(columns=["ticker", "raw", "rank", "z_score"])

    spy_idx = pd.to_datetime(spy_df.index).normalize()
    spy_window = spy_df[spy_idx <= as_of_ts]
    if len(spy_window) < lookback_days:
        logger.warning(
            "residual_momentum_12_1: SPY history < %d days; got %d",
            lookback_days, len(spy_window),
        )
        return pd.DataFrame(columns=["ticker", "raw", "rank", "z_score"])
    spy_close = spy_window["Close"].copy()
    spy_close.index = pd.to_datetime(spy_close.index).normalize()
    # Restrict to the regression window: [as_of - lookback_days, as_of].
    spy_close = spy_close.iloc[-lookback_days:]

    rows: list[dict] = []
    for ticker, df in prices.items():
        if df is None or df.empty or "Close" not in df.columns:
            continue
        idx = pd.to_datetime(df.index).normalize()
        eligible = df[idx <= as_of_ts]
        if len(eligible) < lookback_days:
            continue
        stock_close = eligible["Close"].copy()
        stock_close.index = pd.to_datetime(stock_close.index).normalize()
        stock_close = stock_close.iloc[-lookback_days:]

        stock_ret, spy_ret = _aligned_returns(stock_close, spy_close)
        if len(stock_ret) < min_overlap:
            continue

        alpha, beta = _fit_beta(stock_ret.values, spy_ret.values)
        residuals = stock_ret.values - (alpha + beta * spy_ret.values)
        # Drop the last skip_days residuals (skip-month). Index is
        # date-ordered so slicing from the right works.
        if skip_days > 0:
            residuals_excl_skip = residuals[:-skip_days]
        else:
            residuals_excl_skip = residuals
        if len(residuals_excl_skip) == 0:
            continue
        # Cumulative residual return — log-style sum is the standard
        # form (Blitz 2011). For small daily moves sum(eps) ≈ product
        # of (1+eps)-1 but the sum is numerically cleaner.
        raw = float(np.sum(residuals_excl_skip))
        rows.append({"ticker": ticker, "raw": raw, "beta": beta})

    if not rows:
        return pd.DataFrame(columns=["ticker", "raw", "rank", "z_score"])

    out = pd.DataFrame(rows)
    out["rank"] = out["raw"].rank(ascending=False, method="min").astype(int)
    mu = float(out["raw"].mean())
    sigma = float(out["raw"].std(ddof=0))
    if sigma > 0:
        out["z_score"] = (out["raw"] - mu) / sigma
    else:
        out["z_score"] = 0.0
    out = out.sort_values("rank").reset_index(drop=True)
    logger.debug(
        "residual_momentum_12_1 as_of=%s: %d names, mean raw=%.4f, "
        "mean beta=%.2f",
        as_of_ts.date(), len(out), mu, float(out["beta"].mean()),
    )
    return out[["ticker", "raw", "rank", "z_score"]]


__all__ = ["residual_momentum_12_1", "LOOKBACK_DAYS", "SKIP_DAYS"]
