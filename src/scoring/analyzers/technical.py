"""
Technical analysis engine.
Calculates RSI, MACD, Moving Averages, Bollinger Bands, Stochastic, Volume,
and ATR from price data. All parameters come from config.
"""

import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def analyze(df, config):
    """
    Run full technical analysis on OHLCV data.

    Args:
        df: DataFrame with Open, High, Low, Close, Volume columns
        config: Config object

    Returns:
        dict with keys: indicators, signals, score (0-100)
    """
    if df is None or len(df) < 50:
        return {"indicators": {}, "signals": [], "score": 50, "error": "Insufficient data"}

    indicators = {}
    signals = []
    scores = []

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    # --- Moving Averages ---
    sma_scores = _calc_moving_averages(close, config, indicators, signals)
    scores.extend(sma_scores)

    # RSI + Stochastic. By default they're treated as independent
    # indicators (legacy behavior); when ``risk_management.momentum_
    # oscillator.merge_rsi_stoch`` is true they collapse into a single
    # composite entry with a single signal that only fires when both
    # agree — kills the double-counting in the signal-consensus path.
    merge_osc = bool(config.get(
        "risk_management", "momentum_oscillator", "merge_rsi_stoch",
        default=False,
    ))
    if merge_osc:
        rsi_stoch_score = _calc_rsi_stoch_merged(
            close, high, low, config, indicators, signals,
        )
        scores.append(rsi_stoch_score)

        # --- MACD ---
        macd_score = _calc_macd(close, config, indicators, signals)
        scores.append(macd_score)

        # --- Bollinger Bands ---
        bb_score = _calc_bollinger(close, config, indicators, signals)
        scores.append(bb_score)

        # --- Volume Analysis ---
        vol_score = _calc_volume(volume, config, indicators, signals)
        scores.append(vol_score)
    else:
        # --- RSI ---
        rsi_score = _calc_rsi(close, config, indicators, signals)
        scores.append(rsi_score)

        # --- MACD ---
        macd_score = _calc_macd(close, config, indicators, signals)
        scores.append(macd_score)

        # --- Bollinger Bands ---
        bb_score = _calc_bollinger(close, config, indicators, signals)
        scores.append(bb_score)

        # --- Volume Analysis ---
        vol_score = _calc_volume(volume, config, indicators, signals)
        scores.append(vol_score)

        # --- Stochastic ---
        stoch_score = _calc_stochastic(high, low, close, config, indicators, signals)
        scores.append(stoch_score)

    # --- Clenow regression-slope momentum (slope * R^2) ---
    clenow_score = _calc_regression_slope_momentum(close, config, indicators, signals)
    scores.append(clenow_score)

    # --- ATR (for risk management, not scored) ---
    _calc_atr(high, low, close, config, indicators)

    # Composite score
    valid_scores = [s for s in scores if s is not None]
    composite = np.mean(valid_scores) if valid_scores else 50

    return {
        "indicators": indicators,
        "signals": signals,
        "score": round(float(composite), 2),
    }


def _calc_moving_averages(close, config, indicators, signals):
    """Calculate SMAs and EMAs, detect crossovers."""
    scores = []
    sma_periods = config.get("technical_indicators", "sma_periods", default=[20, 50, 200])
    ema_periods = config.get("technical_indicators", "ema_periods", default=[9, 12, 26])
    current_price = close.iloc[-1]

    # SMAs
    for period in sma_periods:
        if len(close) < period:
            continue
        sma = close.rolling(window=period).mean()
        indicators[f"sma_{period}"] = round(float(sma.iloc[-1]), 2)

        # Price vs SMA
        if current_price > sma.iloc[-1]:
            signals.append({"type": "bullish", "source": f"SMA{period}", "detail": f"Price above SMA{period}"})
            scores.append(60 + min(20, (current_price / sma.iloc[-1] - 1) * 200))
        else:
            signals.append({"type": "bearish", "source": f"SMA{period}", "detail": f"Price below SMA{period}"})
            scores.append(40 - min(20, (1 - current_price / sma.iloc[-1]) * 200))

    # Golden Cross / Death Cross (SMA50 vs SMA200)
    if len(close) >= 200 and 50 in sma_periods and 200 in sma_periods:
        sma50 = close.rolling(window=50).mean()
        sma200 = close.rolling(window=200).mean()
        sma50_prev = sma50.iloc[-2]
        sma200_prev = sma200.iloc[-2]
        sma50_now = sma50.iloc[-1]
        sma200_now = sma200.iloc[-1]

        if sma50_prev <= sma200_prev and sma50_now > sma200_now:
            signals.append({"type": "bullish", "source": "GoldenCross", "detail": "SMA50 crossed above SMA200"})
            indicators["golden_cross"] = True
            scores.append(90)
        elif sma50_prev >= sma200_prev and sma50_now < sma200_now:
            signals.append({"type": "bearish", "source": "DeathCross", "detail": "SMA50 crossed below SMA200"})
            indicators["death_cross"] = True
            scores.append(10)

    # EMAs
    for period in ema_periods:
        if len(close) < period:
            continue
        ema = close.ewm(span=period, adjust=False).mean()
        indicators[f"ema_{period}"] = round(float(ema.iloc[-1]), 2)

    return scores


def _calc_rsi(close, config, indicators, signals):
    """Calculate RSI and generate signals."""
    period = config.get("technical_indicators", "rsi", "period", default=14)
    overbought = config.get("technical_indicators", "rsi", "overbought", default=70)
    oversold = config.get("technical_indicators", "rsi", "oversold", default=30)

    if len(close) < period + 1:
        return None

    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()

    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi_value = float(rsi.iloc[-1])
    indicators["rsi"] = round(rsi_value, 2)

    if rsi_value <= oversold:
        signals.append({"type": "bullish", "source": "RSI", "detail": f"Oversold at {rsi_value:.1f}"})
        # Lower RSI = more bullish (potential reversal up)
        return 70 + (oversold - rsi_value)
    elif rsi_value >= overbought:
        signals.append({"type": "bearish", "source": "RSI", "detail": f"Overbought at {rsi_value:.1f}"})
        return 30 - (rsi_value - overbought)
    else:
        # Neutral zone, slight bullish bias below 50
        return 50 + (50 - rsi_value) * 0.3

    # RSI divergence detection
    # (price makes new high but RSI doesn't = bearish divergence)
    # Implemented in patterns.py for more detailed analysis


def _calc_macd(close, config, indicators, signals):
    """Calculate MACD line, signal line, histogram."""
    fast = config.get("technical_indicators", "macd", "fast_period", default=12)
    slow = config.get("technical_indicators", "macd", "slow_period", default=26)
    signal_period = config.get("technical_indicators", "macd", "signal_period", default=9)

    if len(close) < slow + signal_period:
        return None

    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line

    indicators["macd_line"] = round(float(macd_line.iloc[-1]), 4)
    indicators["macd_signal"] = round(float(signal_line.iloc[-1]), 4)
    indicators["macd_histogram"] = round(float(histogram.iloc[-1]), 4)

    macd_now = macd_line.iloc[-1]
    signal_now = signal_line.iloc[-1]
    macd_prev = macd_line.iloc[-2]
    signal_prev = signal_line.iloc[-2]
    hist_now = histogram.iloc[-1]
    hist_prev = histogram.iloc[-2]

    score = 50

    # Crossover signals
    if macd_prev <= signal_prev and macd_now > signal_now:
        signals.append({"type": "bullish", "source": "MACD", "detail": "Bullish crossover"})
        score = 75
    elif macd_prev >= signal_prev and macd_now < signal_now:
        signals.append({"type": "bearish", "source": "MACD", "detail": "Bearish crossover"})
        score = 25

    # Histogram momentum
    if hist_now > 0 and hist_now > hist_prev:
        signals.append({"type": "bullish", "source": "MACD", "detail": "Histogram accelerating up"})
        score = min(score + 10, 90)
    elif hist_now < 0 and hist_now < hist_prev:
        signals.append({"type": "bearish", "source": "MACD", "detail": "Histogram accelerating down"})
        score = max(score - 10, 10)

    return score


def _calc_bollinger(close, config, indicators, signals):
    """Calculate Bollinger Bands and generate signals."""
    period = config.get("technical_indicators", "bollinger", "period", default=20)
    std_dev = config.get("technical_indicators", "bollinger", "std_dev", default=2.0)

    if len(close) < period:
        return None

    sma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std

    indicators["bb_upper"] = round(float(upper.iloc[-1]), 2)
    indicators["bb_middle"] = round(float(sma.iloc[-1]), 2)
    indicators["bb_lower"] = round(float(lower.iloc[-1]), 2)

    current_price = close.iloc[-1]
    bb_width = (upper.iloc[-1] - lower.iloc[-1]) / sma.iloc[-1]
    indicators["bb_width"] = round(float(bb_width), 4)

    # Bandwidth squeeze detection (low volatility -> potential breakout)
    avg_width = ((upper - lower) / sma).rolling(window=period).mean()
    if not avg_width.empty and avg_width.iloc[-1] > 0:
        squeeze_ratio = bb_width / avg_width.iloc[-1]
        indicators["bb_squeeze_ratio"] = round(float(squeeze_ratio), 2)
        if squeeze_ratio < 0.5:
            signals.append({"type": "neutral", "source": "Bollinger", "detail": "Squeeze detected - breakout imminent"})

    # Position within bands
    if current_price <= lower.iloc[-1]:
        signals.append({"type": "bullish", "source": "Bollinger", "detail": "Price at/below lower band"})
        return 70
    elif current_price >= upper.iloc[-1]:
        signals.append({"type": "bearish", "source": "Bollinger", "detail": "Price at/above upper band"})
        return 30
    else:
        # Position within band (0 = lower, 1 = upper)
        band_pos = (current_price - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1])
        indicators["bb_position"] = round(float(band_pos), 2)
        return 50 + (0.5 - band_pos) * 40  # Lower = more bullish


def _calc_volume(volume, config, indicators, signals):
    """Analyze volume for unusual activity."""
    avg_period = config.get("technical_indicators", "volume", "avg_period", default=20)
    spike_mult = config.get("technical_indicators", "volume", "spike_multiplier", default=2.0)

    if len(volume) < avg_period:
        return None

    avg_vol = volume.rolling(window=avg_period).mean()
    current_vol = volume.iloc[-1]
    vol_ratio = current_vol / avg_vol.iloc[-1] if avg_vol.iloc[-1] > 0 else 1.0

    indicators["volume_current"] = int(current_vol)
    indicators["volume_avg"] = int(avg_vol.iloc[-1])
    indicators["volume_ratio"] = round(float(vol_ratio), 2)

    # Volume trend (5-day average vs 20-day average)
    if len(volume) >= avg_period:
        vol_5d = volume.tail(5).mean()
        indicators["volume_trend"] = round(float(vol_5d / avg_vol.iloc[-1]), 2)

    if vol_ratio >= spike_mult:
        signals.append({
            "type": "neutral",
            "source": "Volume",
            "detail": f"Volume spike: {vol_ratio:.1f}x average",
        })
        return 65  # Unusual volume is slightly bullish (attention)
    elif vol_ratio < 0.5:
        return 45  # Low volume = less conviction
    else:
        return 50


def _calc_stochastic(high, low, close, config, indicators, signals):
    """Calculate Stochastic oscillator."""
    k_period = config.get("technical_indicators", "stochastic", "k_period", default=14)
    d_period = config.get("technical_indicators", "stochastic", "d_period", default=3)
    overbought = config.get("technical_indicators", "stochastic", "overbought", default=80)
    oversold = config.get("technical_indicators", "stochastic", "oversold", default=20)

    if len(close) < k_period + d_period:
        return None

    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()

    denom = highest_high - lowest_low
    denom = denom.replace(0, np.nan)
    k = 100 * (close - lowest_low) / denom
    d = k.rolling(window=d_period).mean()

    k_value = float(k.iloc[-1])
    d_value = float(d.iloc[-1])
    indicators["stoch_k"] = round(k_value, 2)
    indicators["stoch_d"] = round(d_value, 2)

    if k_value <= oversold and d_value <= oversold:
        signals.append({"type": "bullish", "source": "Stochastic", "detail": f"Oversold: K={k_value:.0f}, D={d_value:.0f}"})
        return 70
    elif k_value >= overbought and d_value >= overbought:
        signals.append({"type": "bearish", "source": "Stochastic", "detail": f"Overbought: K={k_value:.0f}, D={d_value:.0f}"})
        return 30
    else:
        return 50 + (50 - k_value) * 0.2


def _calc_rsi_stoch_merged(close, high, low, config, indicators, signals):
    """Merged momentum oscillator: average of RSI + Stochastic scores
    with a single ``MomOsc`` signal that fires only when both agree.

    Calls the existing single-indicator functions with a private
    signal buffer (so their per-indicator signals never reach the
    global ``signals`` list), then synthesizes one merged signal.

    Returns None if both indicators return None (insufficient bars).
    Returns the single non-None score when only one fires — keeps
    information when one indicator has enough history and the other
    doesn't, instead of returning None for the whole bucket.
    """
    private_signals: list[dict] = []
    rsi_score = _calc_rsi(close, config, indicators, private_signals)
    stoch_score = _calc_stochastic(high, low, close, config, indicators, private_signals)

    if rsi_score is None and stoch_score is None:
        return None
    if rsi_score is None:
        return stoch_score
    if stoch_score is None:
        return rsi_score

    rsi_signal = next((s for s in private_signals if s["source"] == "RSI"), None)
    stoch_signal = next((s for s in private_signals if s["source"] == "Stochastic"), None)
    rsi_type = rsi_signal["type"] if rsi_signal else None
    stoch_type = stoch_signal["type"] if stoch_signal else None

    if rsi_type == "bullish" and stoch_type == "bullish":
        signals.append({
            "type": "bullish",
            "source": "MomOsc",
            "detail": (
                f"RSI {indicators.get('rsi')} + Stoch K {indicators.get('stoch_k')} both oversold"
            ),
        })
    elif rsi_type == "bearish" and stoch_type == "bearish":
        signals.append({
            "type": "bearish",
            "source": "MomOsc",
            "detail": (
                f"RSI {indicators.get('rsi')} + Stoch K {indicators.get('stoch_k')} both overbought"
            ),
        })
    # When the two disagree, no signal is emitted — the averaged score
    # already represents the conflict; emitting a signal in that case
    # would just reintroduce the double-counting we're trying to kill.

    return (rsi_score + stoch_score) / 2.0


def _calc_atr(high, low, close, config, indicators):
    """Calculate Average True Range (used for stop-loss/take-profit, not scored)."""
    period = config.get("technical_indicators", "atr", "period", default=14)

    if len(close) < period + 1:
        return

    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()

    indicators["atr"] = round(float(atr.iloc[-1]), 2)
    indicators["atr_pct"] = round(float(atr.iloc[-1] / close.iloc[-1] * 100), 2)


def _calc_regression_slope_momentum(close, config, indicators, signals):
    """
    Clenow's "Stocks on the Move" momentum: annualized exponential regression
    slope multiplied by R^2 of the fit. Penalizes choppy moves, rewards smooth
    trends. Audited via Alpha Architect's QMOM ETF methodology family and
    independently replicated on QuantConnect.

    Returns a score in [0, 100]; 50 is neutral.
    """
    period = config.get("technical_indicators", "regression_momentum", "period", default=90)
    if len(close) < period + 1:
        return None

    series = close.iloc[-period:].astype(float).to_numpy()
    if (series <= 0).any():
        return None

    log_prices = np.log(series)
    x = np.arange(period)
    # Least-squares slope and intercept
    x_mean = x.mean()
    y_mean = log_prices.mean()
    slope = ((x - x_mean) * (log_prices - y_mean)).sum() / ((x - x_mean) ** 2).sum()
    # R^2
    y_pred = y_mean + slope * (x - x_mean)
    ss_res = ((log_prices - y_pred) ** 2).sum()
    ss_tot = ((log_prices - y_mean) ** 2).sum()
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    # Annualized continuously-compounded return
    annualized_slope_pct = (np.exp(slope * 252) - 1) * 100
    clenow_score_raw = annualized_slope_pct * r_squared

    indicators["regression_slope_pct"] = round(float(annualized_slope_pct), 2)
    indicators["regression_r_squared"] = round(float(r_squared), 3)
    indicators["clenow_momentum"] = round(float(clenow_score_raw), 2)

    # Map raw Clenow score to 0-100. A score of 0 = 50. A score of +50 = ~80.
    # Empirically S&P 500 leaders cluster in the +20 to +100 range.
    if clenow_score_raw <= 0:
        score = max(20.0, 50.0 + clenow_score_raw)  # negative trends pull below 50
    else:
        # Diminishing-returns mapping: 50 + 30 * (1 - exp(-x/40))
        score = 50.0 + 30.0 * (1.0 - np.exp(-clenow_score_raw / 40.0))

    if clenow_score_raw > 40 and r_squared > 0.7:
        signals.append({
            "type": "bullish",
            "source": "ClenowMomentum",
            "detail": f"Smooth uptrend: slope {annualized_slope_pct:.0f}%/yr, R^2 {r_squared:.2f}",
        })
    elif clenow_score_raw < -40 and r_squared > 0.7:
        signals.append({
            "type": "bearish",
            "source": "ClenowMomentum",
            "detail": f"Smooth downtrend: slope {annualized_slope_pct:.0f}%/yr, R^2 {r_squared:.2f}",
        })

    return float(score)
