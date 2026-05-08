"""
Statistical analysis engine.
Momentum scoring, mean reversion, seasonality, and trend regression.
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def analyze(df, config):
    """
    Run statistical analysis on price data.

    Args:
        df: DataFrame with Close prices (DatetimeIndex)
        config: Config object

    Returns:
        dict with keys: metrics, signals, score (0-100)
    """
    if df is None or len(df) < 60:
        return {"metrics": {}, "signals": [], "score": 50, "error": "Insufficient data"}

    metrics = {}
    signals = []
    scores = []

    close = df["Close"]

    # --- Momentum Analysis ---
    mom_score = _calc_momentum(close, metrics, signals)
    scores.append(mom_score)

    # --- Mean Reversion (Z-Score) ---
    mr_score = _calc_mean_reversion(close, metrics, signals)
    scores.append(mr_score)

    # --- Seasonality ---
    season_score = _calc_seasonality(df, metrics, signals)
    if season_score is not None:
        scores.append(season_score)

    # --- Trend Regression ---
    trend_score = _calc_trend_regression(close, metrics, signals)
    scores.append(trend_score)

    # --- Volatility Analysis ---
    _calc_volatility(close, metrics, signals)

    # --- 52-Week Position ---
    week52_score = _calc_52week_position(close, metrics, signals)
    scores.append(week52_score)

    valid_scores = [s for s in scores if s is not None]
    composite = np.mean(valid_scores) if valid_scores else 50

    return {
        "metrics": metrics,
        "signals": signals,
        "score": round(float(composite), 2),
    }


def _calc_momentum(close, metrics, signals):
    """Calculate multi-timeframe momentum scores."""
    current = close.iloc[-1]
    scores = []

    periods = {
        "1m": 21,     # ~1 month of trading days
        "3m": 63,
        "6m": 126,
        "12m": 252,
    }

    for label, days in periods.items():
        if len(close) < days:
            continue
        past_price = close.iloc[-days]
        ret = (current / past_price - 1) * 100
        metrics[f"return_{label}"] = round(ret, 2)

        # Score: positive returns = bullish, scaled
        if ret > 50:
            scores.append(85)
        elif ret > 20:
            scores.append(75)
        elif ret > 10:
            scores.append(65)
        elif ret > 0:
            scores.append(55)
        elif ret > -10:
            scores.append(45)
        elif ret > -20:
            scores.append(35)
        else:
            scores.append(20)

    if not scores:
        return 50

    mom_composite = np.mean(scores)

    # Signal for extreme momentum
    ret_3m = metrics.get("return_3m")
    if ret_3m is not None:
        if ret_3m > 30:
            signals.append({"type": "bullish", "source": "Momentum", "detail": f"Strong 3M momentum: +{ret_3m:.1f}%"})
        elif ret_3m < -20:
            signals.append({"type": "bearish", "source": "Momentum", "detail": f"Weak 3M momentum: {ret_3m:.1f}%"})

    return mom_composite


def _calc_mean_reversion(close, metrics, signals, lookback=200):
    """
    Calculate z-score: how far the current price is from its historical mean.
    Extreme deviations may signal reversion.
    """
    if len(close) < lookback:
        lookback = len(close)

    window = close.tail(lookback)
    mean_price = window.mean()
    std_price = window.std()

    if std_price == 0:
        return 50

    z_score = (close.iloc[-1] - mean_price) / std_price
    metrics["z_score"] = round(float(z_score), 2)
    metrics["mean_price"] = round(float(mean_price), 2)

    # Z-score interpretation for mean reversion strategy
    if z_score < -2:
        signals.append({"type": "bullish", "source": "MeanReversion", "detail": f"Very oversold: z={z_score:.2f}"})
        return 80
    elif z_score < -1:
        signals.append({"type": "bullish", "source": "MeanReversion", "detail": f"Oversold: z={z_score:.2f}"})
        return 65
    elif z_score > 2:
        signals.append({"type": "bearish", "source": "MeanReversion", "detail": f"Very overbought: z={z_score:.2f}"})
        return 20
    elif z_score > 1:
        signals.append({"type": "bearish", "source": "MeanReversion", "detail": f"Overbought: z={z_score:.2f}"})
        return 35
    else:
        # In normal range, slight bias based on direction
        return 50 - z_score * 10


def _calc_seasonality(df, metrics, signals):
    """
    Analyze historical month-by-month performance.
    Check if the current month is historically strong or weak.
    """
    if len(df) < 252:  # Need at least ~1 year
        return None

    close = df["Close"].copy()

    # Ensure DatetimeIndex for resample
    if not isinstance(close.index, pd.DatetimeIndex):
        try:
            close.index = pd.to_datetime(close.index, utc=True)
        except Exception:
            return None

    try:
        monthly_returns = close.resample("ME").last().pct_change().dropna()
    except Exception:
        return None

    if len(monthly_returns) < 12:
        return None

    # Group by month
    monthly_returns_grouped = {}
    for date, ret in monthly_returns.items():
        month = date.month
        if month not in monthly_returns_grouped:
            monthly_returns_grouped[month] = []
        monthly_returns_grouped[month].append(ret)

    # Current month
    current_month = datetime.now().month
    if current_month not in monthly_returns_grouped:
        return None

    month_data = monthly_returns_grouped[current_month]
    avg_return = np.mean(month_data) * 100
    win_rate = sum(1 for r in month_data if r > 0) / len(month_data) * 100

    metrics["seasonality_avg_return"] = round(avg_return, 2)
    metrics["seasonality_win_rate"] = round(win_rate, 1)
    metrics["seasonality_sample_size"] = len(month_data)

    month_names = [
        "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]

    if avg_return > 2:
        signals.append({
            "type": "bullish",
            "source": "Seasonality",
            "detail": f"{month_names[current_month]} historically strong: avg +{avg_return:.1f}%, {win_rate:.0f}% win rate",
        })
        return 65
    elif avg_return < -2:
        signals.append({
            "type": "bearish",
            "source": "Seasonality",
            "detail": f"{month_names[current_month]} historically weak: avg {avg_return:.1f}%, {win_rate:.0f}% win rate",
        })
        return 35
    else:
        return 50


def _calc_trend_regression(close, metrics, signals, lookback=60):
    """
    Linear regression on log prices to determine trend strength and direction.
    R-squared measures how clean the trend is.
    """
    if len(close) < lookback:
        lookback = len(close)

    prices = close.tail(lookback).values
    log_prices = np.log(prices)
    x = np.arange(lookback)

    # Linear regression
    coeffs = np.polyfit(x, log_prices, 1)
    slope = coeffs[0]

    # R-squared
    predicted = np.polyval(coeffs, x)
    ss_res = np.sum((log_prices - predicted) ** 2)
    ss_tot = np.sum((log_prices - np.mean(log_prices)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    # Annualized return from slope
    annualized_return = (np.exp(slope * 252) - 1) * 100

    metrics["trend_slope"] = round(float(slope), 6)
    metrics["trend_r_squared"] = round(float(r_squared), 3)
    metrics["trend_annualized_return"] = round(float(annualized_return), 2)

    # Strong uptrend with clean trend = bullish
    if slope > 0 and r_squared > 0.7:
        signals.append({
            "type": "bullish",
            "source": "Trend",
            "detail": f"Strong uptrend (R²={r_squared:.2f}, ann. return={annualized_return:.0f}%)",
        })
        return min(85, 60 + r_squared * 25)
    elif slope > 0:
        return 55 + r_squared * 15
    elif slope < 0 and r_squared > 0.7:
        signals.append({
            "type": "bearish",
            "source": "Trend",
            "detail": f"Strong downtrend (R²={r_squared:.2f}, ann. return={annualized_return:.0f}%)",
        })
        return max(15, 40 - r_squared * 25)
    else:
        return 45 - r_squared * 15


def _calc_volatility(close, metrics, signals):
    """Calculate historical volatility metrics."""
    if len(close) < 30:
        return

    returns = close.pct_change().dropna()

    # 20-day historical volatility (annualized)
    vol_20d = returns.tail(20).std() * np.sqrt(252) * 100
    metrics["volatility_20d"] = round(float(vol_20d), 2)

    # 60-day historical volatility
    if len(returns) >= 60:
        vol_60d = returns.tail(60).std() * np.sqrt(252) * 100
        metrics["volatility_60d"] = round(float(vol_60d), 2)

        # Volatility contraction/expansion
        vol_ratio = vol_20d / vol_60d if vol_60d > 0 else 1
        metrics["volatility_ratio"] = round(float(vol_ratio), 2)

        if vol_ratio < 0.7:
            signals.append({
                "type": "neutral",
                "source": "Volatility",
                "detail": f"Volatility contracting ({vol_ratio:.2f}x) - breakout potential",
            })

    # Max drawdown (last 252 days)
    lookback = min(252, len(close))
    window = close.tail(lookback)
    peak = window.expanding().max()
    drawdown = ((window - peak) / peak * 100)
    max_dd = drawdown.min()
    metrics["max_drawdown_1y"] = round(float(max_dd), 2)

    if max_dd < -30:
        signals.append({
            "type": "bearish",
            "source": "Drawdown",
            "detail": f"Deep drawdown: {max_dd:.1f}% from peak",
        })


def _calc_52week_position(close, metrics, signals):
    """Calculate position within 52-week range."""
    lookback = min(252, len(close))
    if lookback < 50:
        return 50

    window = close.tail(lookback)
    high_52w = window.max()
    low_52w = window.min()
    current = close.iloc[-1]

    range_52w = high_52w - low_52w
    if range_52w == 0:
        return 50

    position = (current - low_52w) / range_52w
    metrics["52w_high"] = round(float(high_52w), 2)
    metrics["52w_low"] = round(float(low_52w), 2)
    metrics["52w_position"] = round(float(position), 2)

    pct_from_high = (current / high_52w - 1) * 100
    metrics["pct_from_52w_high"] = round(float(pct_from_high), 2)

    if position > 0.95:
        signals.append({"type": "bullish", "source": "52Week", "detail": f"Near 52-week high ({pct_from_high:+.1f}%)"})
        return 70  # Strength (not overbought in trend context)
    elif position < 0.2:
        signals.append({"type": "bearish", "source": "52Week", "detail": f"Near 52-week low ({pct_from_high:.1f}% from high)"})
        return 35
    else:
        return 40 + position * 30
