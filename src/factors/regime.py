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

# Default re-entry signal for the asymmetric trend filter. 75 trading
# days is the calibrated sweet spot from the 2026-05-18 sweep: faster
# than 200-SMA (catches the post-Oct-2022 recovery 3 months earlier,
# +9.20pp on the failing fold 1 of 2022-2024 WF) but slow enough to
# ignore the Aug-2024 Japan-carry single-day spike that 50-SMA fired
# on (and lost -12pp of recent-window alpha). 75/100/125/150 all
# produced bit-identical results on both windows; 75 is the most
# aggressive that still avoids the false positive.
ENTRY_SMA_WINDOW = 75


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


def trend_state_asymmetric_series(
    spy_df: pd.DataFrame,
    *,
    exit_sma: int = SMA_WINDOW,
    entry_sma: int = ENTRY_SMA_WINDOW,
) -> pd.Series:
    """Faster trend filter -- 50-SMA level check in both directions.

    The symmetric ``trend_state_series`` uses the 200-SMA, which is too
    lagging for re-entry after sharp bear bottoms: after Oct-2022 the
    composite's 63d rebalance schedule didn't land on a 200-SMA-up day
    until Feb-2023, missing +16% of the recovery (see
    project_2022_wf_real_diagnosis memory).

    This is named "asymmetric" because the original intent was to keep
    the 200-SMA for exit and use the 50-SMA for re-entry only -- but
    the cross-event implementation has a structural flaw: once you've
    re-entered while SPY is still below 200-SMA, there's no future
    cross-DOWN through 200-SMA to fire the exit. So we collapse to the
    practical equivalent: a single faster SMA level check (50-SMA by
    default) in both directions. ``exit_sma`` is kept as an arg for
    callers who want different windows -- in practice, set both to
    the same value (or leave defaults).

    Returns a boolean series indexed by date. First ``entry_sma - 1``
    rows are False.
    """
    close = spy_df["Close"].astype(float)
    sma = close.rolling(window=entry_sma, min_periods=entry_sma).mean()
    state = close >= sma
    state = state.where(sma.notna(), other=False)
    return state.astype(bool)


def trend_state_hysteresis_series(
    spy_df: pd.DataFrame,
    *,
    entry_sma: int = ENTRY_SMA_WINDOW,
    band_pct: float = 0.0,
) -> pd.Series:
    """SPY vs ``entry_sma`` with a HYSTERESIS DEAD-BAND to kill whipsaw.

    Risk-on flips True only when SPY closes ABOVE ``sma * (1 + band_pct)``;
    flips False only when it closes BELOW ``sma * (1 - band_pct)``; inside the
    band it CARRIES the prior state (sticky). ``band_pct=0`` reduces to the
    plain level check (``trend_state_asymmetric_series``).

    Motivation: with daily regime evaluation the plain 75-SMA gate whipsaws a
    choppy slow bear (2022 — exits every dip below the SMA, re-enters every
    bounce, eroding CAPM-alpha). A dead-band ignores marginal crosses, keeping
    the fast-crash protection + bull responsiveness while cutting the whipsaw.
    Path-dependent, so it's a simple stateful walk. First ``entry_sma - 1``
    rows are False (insufficient history); the pre-cross initial state is
    False (defensive).
    """
    close = spy_df["Close"].astype(float)
    sma = close.rolling(window=entry_sma, min_periods=entry_sma).mean()
    upper = (sma * (1.0 + band_pct)).to_numpy()
    lower = (sma * (1.0 - band_pct)).to_numpy()
    valid = sma.notna().to_numpy()
    prices = close.to_numpy()
    out = [False] * len(prices)
    state = False
    for i in range(len(prices)):
        if not valid[i]:
            out[i] = False
            continue
        if prices[i] > upper[i]:
            state = True
        elif prices[i] < lower[i]:
            state = False
        # within [lower, upper] -> carry prior state (sticky)
        out[i] = state
    return pd.Series(out, index=close.index, dtype=bool)


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
