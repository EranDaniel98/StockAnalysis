"""
Post-Earnings-Announcement Drift (PEAD) detector.

PEAD is one of the most replicated anomalies in finance literature (Bernard &
Thomas 1989; Chordia & Shivakumar 2006; Garfinkel et al. 2024). Stocks that
report large positive earnings surprises tend to continue drifting upward for
1-3 months post-announcement; conversely for large negative surprises. The
drift is driven by analyst underreaction and slow information diffusion.

Implementation: detect stocks in the "drift window" (days +1 to +60 after
their most recent earnings announcement) with a large standardized surprise,
and add an additive bonus to the composite score.

Caveat: yfinance's `get_earnings_dates` returns surprises only for some
tickers and time windows. When data is missing the detector returns a neutral
no-bonus result.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def analyze(
    ticker: str,
    earnings_history: Optional[pd.DataFrame],
    as_of_date: Optional[pd.Timestamp] = None,
    drift_window_days: int = 60,
    min_surprise_pct: float = 5.0,
    max_bonus: float = 10.0,
) -> dict:
    """
    Compute PEAD signal for a single ticker.

    Args:
        ticker: stock symbol (for signal text)
        earnings_history: DataFrame from yfinance Ticker.get_earnings_dates(), or None
        as_of_date: pseudo-current date for backtesting; defaults to now
        drift_window_days: post-earnings window length (PEAD literature: 60d)
        min_surprise_pct: minimum |surprise %| to register a signal
        max_bonus: maximum score-point bonus (positive or negative)

    Returns:
        dict with:
          score: 50-baseline reference (always 50 — PEAD is additive)
          composite_bonus: +/- score points to ADD to composite (read by scoring engine)
          indicators: dict of pead_* fields
          signals: list of dicts
    """
    indicators: dict = {}
    signals: list = []
    bonus = 0.0

    if earnings_history is None or earnings_history.empty:
        return {"score": 50, "composite_bonus": 0.0, "indicators": indicators, "signals": signals}

    if as_of_date is None:
        as_of_date = pd.Timestamp.now().normalize()
    else:
        as_of_date = pd.Timestamp(as_of_date)
        if as_of_date.tz is not None:
            as_of_date = as_of_date.tz_localize(None)

    # Normalize earnings_history index
    try:
        eh = earnings_history.copy()
        if isinstance(eh.index, pd.DatetimeIndex) and eh.index.tz is not None:
            eh.index = eh.index.tz_localize(None)
        else:
            eh.index = pd.to_datetime(eh.index)
    except Exception as e:
        logger.debug(f"PEAD {ticker}: bad earnings index: {e}")
        return {"score": 50, "composite_bonus": 0.0, "indicators": indicators, "signals": signals}

    # Past earnings only (announced and in drift window)
    past = eh.loc[(eh.index < as_of_date) & (eh.index >= as_of_date - pd.Timedelta(days=drift_window_days))]
    if past.empty:
        return {"score": 50, "composite_bonus": 0.0, "indicators": indicators, "signals": signals}

    # Latest within window
    latest_date = past.index.max()
    latest_row = past.loc[latest_date]
    days_since = (as_of_date - latest_date).days
    indicators["pead_days_since_earnings"] = int(days_since)

    surprise_pct = _extract_surprise_pct(latest_row)
    if surprise_pct is None:
        return {"score": 50, "composite_bonus": 0.0, "indicators": indicators, "signals": signals}

    indicators["pead_surprise_pct"] = round(float(surprise_pct), 2)

    # Decay over drift window — strongest signal at day +5, faded by day +60
    if days_since < 1 or days_since > drift_window_days:
        decay = 0.0
    elif days_since < 5:
        decay = days_since / 5.0  # ramp up: market needs a few days to slow-walk reaction
    else:
        decay = max(0.0, 1.0 - (days_since - 5) / (drift_window_days - 5))

    indicators["pead_drift_decay"] = round(float(decay), 2)

    if abs(surprise_pct) < min_surprise_pct:
        return {"score": 50, "composite_bonus": 0.0, "indicators": indicators, "signals": signals}

    # Map surprise magnitude to bonus magnitude. Cap so a single huge surprise
    # doesn't dominate the composite.
    surprise_capped = float(np.clip(surprise_pct, -50.0, 50.0))
    raw_bonus = (surprise_capped / 50.0) * max_bonus
    bonus = float(raw_bonus * decay)

    if bonus > 1:
        signals.append({
            "type": "bullish",
            "source": "PEAD",
            "detail": f"Positive earnings surprise {surprise_pct:+.1f}% {days_since}d ago",
        })
    elif bonus < -1:
        signals.append({
            "type": "bearish",
            "source": "PEAD",
            "detail": f"Negative earnings surprise {surprise_pct:+.1f}% {days_since}d ago",
        })

    return {
        "score": 50,
        "composite_bonus": round(bonus, 2),
        "indicators": indicators,
        "signals": signals,
    }


def _extract_surprise_pct(row) -> Optional[float]:
    """Pull the surprise % from a yfinance earnings_dates row. Schema varies."""
    candidates = [
        "Surprise(%)", "Surprise (%)", "surprisePercent",
        "Earnings Surprise (%)", "earnings_surprise_pct",
    ]
    for key in candidates:
        if hasattr(row, "get"):
            val = row.get(key)
            if val is not None and pd.notna(val):
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
    # Fallback: compute from EPS columns if present
    try:
        actual = row.get("EPS Estimate") if hasattr(row, "get") else None
        reported = row.get("Reported EPS") if hasattr(row, "get") else None
        if actual is not None and reported is not None and pd.notna(actual) and pd.notna(reported) and actual != 0:
            return float((reported - actual) / abs(actual)) * 100
    except Exception:
        pass
    return None


def fetch_earnings_history(ticker: str) -> Optional[pd.DataFrame]:
    """
    Fetch historical earnings dates + surprises for a ticker via yfinance.
    Returns DataFrame indexed by datetime, or None on failure.
    """
    import yfinance as yf
    try:
        return yf.Ticker(ticker).get_earnings_dates(limit=40)
    except Exception as e:
        logger.debug(f"PEAD earnings fetch failed for {ticker}: {e}")
        return None
