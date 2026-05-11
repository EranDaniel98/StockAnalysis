"""
Alpha158 — port of 25 of the most useful factors from Microsoft Qlib's Alpha158
library. These are hand-engineered technical/statistical factors with documented
information coefficient (IC) on US and Chinese equities.

Reference: https://github.com/microsoft/qlib/blob/main/qlib/contrib/data/handler.py

Each factor is a 0-100 score. The module returns a composite Alpha158 score
plus the raw factor values for downstream analysis.

Methodology adaptation: Qlib's Alpha158 is designed for cross-sectional ranking
across thousands of stocks at once. For single-stock daily scoring we z-score
each factor against its own 252-day history, then map z-scores to 0-100 using
each factor's known bullish/bearish direction.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Factor direction: +1 = higher is bullish, -1 = lower is bullish, 0 = U-shaped (use absolute z)
#
# Sign conventions are calibrated for SHORT-HORIZON (1-5 day) US equity returns,
# which exhibit *reversal* (Jegadeesh 1990; Lehmann 1990; Khandani & Lo 2007),
# not continuation. Qlib's defaults assume momentum continuation, which is
# correct for Chinese A-shares + weekly rebalancing but wrong for US daily.
#
# Empirical IC test on 36-ticker themes universe × 3 years (~26k obs) showed
# +1 short-term factors produced IC ≈ -0.024 at 5D — flipping to reversal
# convention reverses the sign. Mid-term (60-day) factors keep momentum sign
# (Jegadeesh-Titman 1993 effect kicks in past ~21 trading days).
FACTOR_DIRECTION = {
    # K-series candles: today's strong close → tomorrow's reversal candidate
    "KMID": -1,    # bullish candle today → likely revert
    "KMID2": -1,
    "KLEN": 0,     # range — U-shaped (use |z|)
    "KUP": +1,     # large upper shadow → continuation of selling pressure (rejection)
    "KUP2": +1,
    "KLOW": -1,    # large lower shadow → revert (initial defense often unwinds)
    "KLOW2": -1,
    "KSFT": -1,    # close near day high → revert
    "KSFT2": -1,
    # Short-horizon ROC: well-documented reversal (Lehmann 1990)
    "ROC5": -1,
    "ROC10": -1,
    "ROC20": -1,
    "ROC30": +1,   # 30d sits near the inflection — mild momentum
    # MA distance: close above short MAs → revert; above long MA → trend
    "MA5": -1,
    "MA10": -1,
    "MA20": -1,
    "MA60": +1,    # 60d momentum (Jegadeesh-Titman)
    # Volatility — risk-off
    "STD20": -1,
    # Distance to extremes — at top of range = revert candidate
    "MAX20": +1,   # (max - close) / close — far below max is bullish revert setup
    "MIN20": -1,   # (close - min) / close — far above min = stretched, revert
    # Stochastic / rank — high = stretched
    "RSV20": -1,
    "RANK20": -1,
    # Volume — high volume often = climactic move (revert at short horizons)
    "VMA20": -1,
    # Price-volume correlation
    "CORR20": +1,
}


def analyze(df: pd.DataFrame, config) -> dict:
    """
    Run Alpha158 factor analysis on OHLCV data.

    Args:
        df: DataFrame with Open, High, Low, Close, Volume columns
        config: Config object (unused for now; reserved for future tuning)

    Returns:
        dict with keys: indicators, signals, score (0-100)
    """
    if df is None or len(df) < 260:  # need 252 for z-score history + lookback
        return {"indicators": {}, "signals": [], "score": 50, "error": "Insufficient data (need 260+ bars)"}

    factors = _compute_factor_series(df)
    if factors is None or factors.empty:
        return {"indicators": {}, "signals": [], "score": 50, "error": "Factor computation failed"}

    indicators: dict = {}
    signals: list = []
    factor_scores: list[float] = []

    for name, series in factors.items():
        series = series.dropna()
        if len(series) < 252:
            continue
        # Latest value vs trailing 252-day history
        history = series.iloc[-252:-1]  # exclude today
        today = series.iloc[-1]
        if history.std() == 0 or not np.isfinite(today):
            continue
        z = (today - history.mean()) / history.std()
        # Clamp extreme z to prevent outliers from dominating
        z = np.clip(z, -3.0, 3.0)

        direction = FACTOR_DIRECTION.get(name, 0)
        if direction == 0:
            # U-shaped — extreme deviations either side are notable
            score = 50.0 - abs(z) * 10.0
        else:
            score = 50.0 + (z * direction) * 10.0
        score = float(np.clip(score, 0.0, 100.0))

        indicators[f"alpha158_{name}"] = round(float(today), 4)
        indicators[f"alpha158_{name}_z"] = round(float(z), 2)
        factor_scores.append(score)

        # Generate signals only for strongest extremes
        if abs(z) >= 2.0 and direction != 0:
            kind = "bullish" if (z * direction > 0) else "bearish"
            signals.append({
                "type": kind,
                "source": f"Alpha158/{name}",
                "detail": f"z={z:+.1f} ({today:+.3f})",
            })

    if not factor_scores:
        return {"indicators": indicators, "signals": signals, "score": 50, "error": "No valid factors"}

    composite = float(np.mean(factor_scores))
    indicators["alpha158_n_factors"] = len(factor_scores)
    indicators["alpha158_composite_raw"] = round(composite, 2)

    return {
        "indicators": indicators,
        "signals": signals,
        "score": round(composite, 2),
    }


def _compute_factor_series(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Return a DataFrame where each column is one Alpha158 factor's time series."""
    try:
        close = df["Close"].astype(float)
        open_ = df["Open"].astype(float)
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        volume = df["Volume"].astype(float).replace(0, np.nan)

        factors: dict[str, pd.Series] = {}

        # ---- K-series candle features ----
        body = close - open_
        range_ = (high - low).replace(0, np.nan)
        upper_shadow = high - np.maximum(open_, close)
        lower_shadow = np.minimum(open_, close) - low

        factors["KMID"] = body / open_
        factors["KMID2"] = body / range_
        factors["KLEN"] = range_ / open_
        factors["KUP"] = upper_shadow / open_
        factors["KUP2"] = upper_shadow / range_
        factors["KLOW"] = lower_shadow / open_
        factors["KLOW2"] = lower_shadow / range_
        factors["KSFT"] = (2 * close - high - low) / open_
        factors["KSFT2"] = (2 * close - high - low) / range_

        # ---- Rate of change ----
        for d in (5, 10, 20, 30):
            factors[f"ROC{d}"] = close.pct_change(d)

        # ---- MA distance: close vs moving average ----
        for d in (5, 10, 20, 60):
            ma = close.rolling(d, min_periods=d).mean()
            factors[f"MA{d}"] = close / ma - 1

        # ---- Realized volatility ----
        returns = close.pct_change()
        factors["STD20"] = returns.rolling(20, min_periods=20).std()

        # ---- Distance to recent extremes ----
        rolling_max20 = close.rolling(20, min_periods=20).max()
        rolling_min20 = close.rolling(20, min_periods=20).min()
        factors["MAX20"] = (rolling_max20 - close) / close
        factors["MIN20"] = (close - rolling_min20) / close

        # ---- Raw stochastic value ----
        denom = (rolling_max20 - rolling_min20).replace(0, np.nan)
        factors["RSV20"] = (close - rolling_min20) / denom

        # ---- Volume relative to its MA ----
        vol_ma20 = volume.rolling(20, min_periods=20).mean()
        factors["VMA20"] = volume / vol_ma20 - 1

        # ---- Price-volume correlation ----
        log_close = np.log(close.replace(0, np.nan))
        log_volume = np.log(volume)
        factors["CORR20"] = log_close.rolling(20).corr(log_volume)

        # ---- Rank of latest close within trailing window ----
        factors["RANK20"] = close.rolling(20, min_periods=20).rank(pct=True)

        result = pd.DataFrame(factors)
        return result
    except Exception as e:
        logger.error(f"Alpha158 factor computation failed: {e}")
        return None
