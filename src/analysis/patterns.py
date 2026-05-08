"""
Pattern detection engine.
Detects candlestick patterns and support/resistance levels from price data.
"""

import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def analyze(df, config):
    """
    Detect candlestick patterns and support/resistance levels.

    Args:
        df: DataFrame with Open, High, Low, Close columns
        config: Config object

    Returns:
        dict with keys: patterns (list), support_resistance, signals, score (0-100)
    """
    if df is None or len(df) < 20:
        return {"patterns": [], "support_resistance": {}, "signals": [], "score": 50}

    patterns = []
    signals = []
    scores = []

    open_ = df["Open"]
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    # --- Candlestick Patterns (last 5 bars) ---
    candle_patterns = _detect_candlestick_patterns(open_, high, low, close)
    patterns.extend(candle_patterns)

    for p in candle_patterns:
        signals.append({"type": p["direction"], "source": "Candlestick", "detail": p["name"]})
        if p["direction"] == "bullish":
            scores.append(65 + p.get("strength", 1) * 5)
        else:
            scores.append(35 - p.get("strength", 1) * 5)

    # --- Support and Resistance Levels ---
    support_resistance = _find_support_resistance(high, low, close)

    current_price = close.iloc[-1]
    sr_score = _score_support_resistance(current_price, support_resistance, signals)
    if sr_score is not None:
        scores.append(sr_score)

    # --- RSI Divergence ---
    div_score = _detect_divergence(close, config, signals)
    if div_score is not None:
        scores.append(div_score)

    composite = np.mean(scores) if scores else 50

    return {
        "patterns": patterns,
        "support_resistance": support_resistance,
        "signals": signals,
        "score": round(float(composite), 2),
    }


def _detect_candlestick_patterns(open_, high, low, close):
    """Detect common candlestick patterns in the last few bars."""
    patterns = []
    if len(close) < 3:
        return patterns

    # Use the last few bars
    o = open_.values
    h = high.values
    c = close.values
    lo = low.values

    # Body and shadow calculations for last bar
    body = abs(c[-1] - o[-1])
    upper_shadow = h[-1] - max(c[-1], o[-1])
    lower_shadow = min(c[-1], o[-1]) - lo[-1]
    total_range = h[-1] - lo[-1]

    if total_range == 0:
        return patterns

    body_pct = body / total_range

    # --- Doji (small body relative to range) ---
    if body_pct < 0.1:
        patterns.append({
            "name": "Doji",
            "direction": "neutral",
            "bar": -1,
            "strength": 1,
            "meaning": "Indecision - potential reversal",
        })

    # --- Hammer (bullish reversal at bottom) ---
    if (lower_shadow >= body * 2
            and upper_shadow < body * 0.5
            and c[-1] > o[-1]
            and c[-2] > c[-1]):  # preceded by decline
        patterns.append({
            "name": "Hammer",
            "direction": "bullish",
            "bar": -1,
            "strength": 2,
            "meaning": "Bullish reversal signal",
        })

    # --- Inverted Hammer ---
    if (upper_shadow >= body * 2
            and lower_shadow < body * 0.5
            and c[-2] > c[-1]):  # preceded by decline
        patterns.append({
            "name": "Inverted Hammer",
            "direction": "bullish",
            "bar": -1,
            "strength": 1,
            "meaning": "Potential bullish reversal",
        })

    # --- Shooting Star (bearish reversal at top) ---
    if (upper_shadow >= body * 2
            and lower_shadow < body * 0.5
            and c[-2] < c[-1]  # preceded by rise
            and o[-1] > c[-1]):  # bearish close
        patterns.append({
            "name": "Shooting Star",
            "direction": "bearish",
            "bar": -1,
            "strength": 2,
            "meaning": "Bearish reversal signal",
        })

    # --- Bullish Engulfing ---
    if (len(close) >= 2
            and o[-2] > c[-2]  # previous bar was bearish
            and c[-1] > o[-1]  # current bar is bullish
            and c[-1] > o[-2]  # current close > prev open
            and o[-1] < c[-2]):  # current open < prev close
        patterns.append({
            "name": "Bullish Engulfing",
            "direction": "bullish",
            "bar": -1,
            "strength": 3,
            "meaning": "Strong bullish reversal",
        })

    # --- Bearish Engulfing ---
    if (len(close) >= 2
            and c[-2] > o[-2]  # previous bar was bullish
            and o[-1] > c[-1]  # current bar is bearish
            and o[-1] > c[-2]  # current open > prev close
            and c[-1] < o[-2]):  # current close < prev open
        patterns.append({
            "name": "Bearish Engulfing",
            "direction": "bearish",
            "bar": -1,
            "strength": 3,
            "meaning": "Strong bearish reversal",
        })

    # --- Morning Star (3-bar bullish reversal) ---
    if len(close) >= 3:
        bar1_bearish = c[-3] < o[-3]
        bar2_small = abs(c[-2] - o[-2]) < abs(c[-3] - o[-3]) * 0.3
        bar3_bullish = c[-1] > o[-1] and c[-1] > (o[-3] + c[-3]) / 2

        if bar1_bearish and bar2_small and bar3_bullish:
            patterns.append({
                "name": "Morning Star",
                "direction": "bullish",
                "bar": -1,
                "strength": 3,
                "meaning": "Strong bullish reversal pattern",
            })

    # --- Evening Star (3-bar bearish reversal) ---
    if len(close) >= 3:
        bar1_bullish = c[-3] > o[-3]
        bar2_small = abs(c[-2] - o[-2]) < abs(c[-3] - o[-3]) * 0.3
        bar3_bearish = c[-1] < o[-1] and c[-1] < (o[-3] + c[-3]) / 2

        if bar1_bullish and bar2_small and bar3_bearish:
            patterns.append({
                "name": "Evening Star",
                "direction": "bearish",
                "bar": -1,
                "strength": 3,
                "meaning": "Strong bearish reversal pattern",
            })

    # --- Three White Soldiers ---
    if len(close) >= 3:
        if (c[-3] > o[-3] and c[-2] > o[-2] and c[-1] > o[-1]  # 3 bullish bars
                and c[-2] > c[-3] and c[-1] > c[-2]  # each closes higher
                and o[-2] > o[-3] and o[-1] > o[-2]):  # each opens higher
            patterns.append({
                "name": "Three White Soldiers",
                "direction": "bullish",
                "bar": -1,
                "strength": 3,
                "meaning": "Strong uptrend confirmation",
            })

    # --- Three Black Crows ---
    if len(close) >= 3:
        if (c[-3] < o[-3] and c[-2] < o[-2] and c[-1] < o[-1]  # 3 bearish bars
                and c[-2] < c[-3] and c[-1] < c[-2]  # each closes lower
                and o[-2] < o[-3] and o[-1] < o[-2]):  # each opens lower
            patterns.append({
                "name": "Three Black Crows",
                "direction": "bearish",
                "bar": -1,
                "strength": 3,
                "meaning": "Strong downtrend confirmation",
            })

    return patterns


def _find_support_resistance(high, low, close, lookback=60, num_levels=3):
    """
    Find key support and resistance levels using pivot points
    and price clustering.
    """
    if len(close) < lookback:
        lookback = len(close)

    recent_high = high.tail(lookback).values
    recent_low = low.tail(lookback).values
    recent_close = close.tail(lookback).values
    current_price = close.iloc[-1]

    # Find local minima and maxima
    support_levels = []
    resistance_levels = []
    window = 5

    for i in range(window, len(recent_close) - window):
        # Local minimum -> support
        if recent_low[i] == min(recent_low[i - window:i + window + 1]):
            support_levels.append(recent_low[i])
        # Local maximum -> resistance
        if recent_high[i] == max(recent_high[i - window:i + window + 1]):
            resistance_levels.append(recent_high[i])

    # Cluster nearby levels (within 2% of each other)
    support_levels = _cluster_levels(support_levels, threshold=0.02)
    resistance_levels = _cluster_levels(resistance_levels, threshold=0.02)

    # Filter: support below price, resistance above price
    supports = sorted([s for s in support_levels if s < current_price], reverse=True)
    resistances = sorted([r for r in resistance_levels if r > current_price])

    return {
        "support": [round(s, 2) for s in supports[:num_levels]],
        "resistance": [round(r, 2) for r in resistances[:num_levels]],
        "current_price": round(current_price, 2),
    }


def _cluster_levels(levels, threshold=0.02):
    """Merge nearby price levels into clusters."""
    if not levels:
        return []

    levels = sorted(levels)
    clusters = []
    current_cluster = [levels[0]]

    for level in levels[1:]:
        if (level - current_cluster[-1]) / current_cluster[-1] < threshold:
            current_cluster.append(level)
        else:
            clusters.append(np.mean(current_cluster))
            current_cluster = [level]

    clusters.append(np.mean(current_cluster))
    return clusters


def _score_support_resistance(current_price, sr, signals):
    """Score based on proximity to support/resistance."""
    supports = sr.get("support", [])
    resistances = sr.get("resistance", [])

    if not supports and not resistances:
        return None

    score = 50

    # Near support = bullish (potential bounce)
    if supports:
        nearest_support = supports[0]
        dist_to_support_pct = (current_price - nearest_support) / current_price * 100
        if dist_to_support_pct < 2:
            signals.append({
                "type": "bullish",
                "source": "Support",
                "detail": f"Near support at ${nearest_support:.2f} ({dist_to_support_pct:.1f}% away)",
            })
            score += 15

    # Near resistance = caution
    if resistances:
        nearest_resistance = resistances[0]
        dist_to_resist_pct = (nearest_resistance - current_price) / current_price * 100
        if dist_to_resist_pct < 2:
            signals.append({
                "type": "bearish",
                "source": "Resistance",
                "detail": f"Near resistance at ${nearest_resistance:.2f} ({dist_to_resist_pct:.1f}% away)",
            })
            score -= 15

    return max(5, min(95, score))


def _detect_divergence(close, config, signals):
    """Detect RSI divergence (price vs RSI direction mismatch)."""
    period = config.get("technical_indicators", "rsi", "period", default=14)
    if len(close) < period + 20:
        return None

    # Calculate RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    # Compare last 20 bars: price trend vs RSI trend
    lookback = 20
    price_recent = close.tail(lookback)
    rsi_recent = rsi.tail(lookback)

    price_slope = np.polyfit(range(lookback), price_recent.values, 1)[0]
    rsi_slope = np.polyfit(range(lookback), rsi_recent.dropna().values[-lookback:], 1)[0] if len(rsi_recent.dropna()) >= lookback else 0

    # Bearish divergence: price rising, RSI falling
    if price_slope > 0 and rsi_slope < -0.3:
        signals.append({
            "type": "bearish",
            "source": "Divergence",
            "detail": "Bearish RSI divergence (price up, RSI down)",
        })
        return 35

    # Bullish divergence: price falling, RSI rising
    if price_slope < 0 and rsi_slope > 0.3:
        signals.append({
            "type": "bullish",
            "source": "Divergence",
            "detail": "Bullish RSI divergence (price down, RSI up)",
        })
        return 65

    return None
