"""SPY 200-day-SMA trend regime filter.

When SPY closes below its 200-day SMA, the market is in a confirmed
downtrend. Historically, the majority of large drawdowns (>20%)
happen during these periods — the regime filter keeps the strategy
in cash through them.

The 200-day SMA is the canonical trend filter (Faber 2007, "A
Quantitative Approach to Tactical Asset Allocation"). It's simple,
robust across regimes, and adds Sharpe + reduces drawdown in
backtests across multiple decades of data. The cost is mild
underperformance in trendless or whippy markets where the SMA
flip-flops; net of that, the literature consensus is positive.
"""

from __future__ import annotations

import logging

import pandas as pd


logger = logging.getLogger(__name__)

SMA_WINDOW = 200  # trading days


def trend_state_series(spy_df: pd.DataFrame) -> pd.Series:
    """Boolean series indexed by date: True = risk-on (SPY ≥ 200-SMA).

    The first ``SMA_WINDOW - 1`` rows are NaN (insufficient history)
    and will read as False. Callers should align this series with the
    backtest schedule and forward-fill any sub-daily gaps.
    """
    if spy_df is None or spy_df.empty or "Close" not in spy_df.columns:
        raise ValueError(
            "trend_state_series needs an OHLCV-style SPY frame with "
            "a 'Close' column"
        )
    close = spy_df["Close"].astype(float)
    sma = close.rolling(window=SMA_WINDOW, min_periods=SMA_WINDOW).mean()
    state = close >= sma
    # Index NaN-row positions to False explicitly (boolean dtype).
    state = state.where(sma.notna(), other=False)
    return state.astype(bool)


def is_risk_on(spy_df: pd.DataFrame, as_of: pd.Timestamp | str) -> bool:
    """True iff SPY's last close at or before ``as_of`` is ≥ its 200-SMA.

    Returns False (defensive default) if there's no SPY data on or
    before ``as_of`` or if the SMA isn't computable yet.
    """
    as_of_ts = pd.Timestamp(as_of)
    series = trend_state_series(spy_df)
    eligible = series[series.index <= as_of_ts]
    if eligible.empty:
        logger.warning(
            "is_risk_on: no SPY data on or before %s — defaulting risk-off",
            as_of_ts.date(),
        )
        return False
    return bool(eligible.iloc[-1])
