"""
Technical analysis engine.
Calculates RSI, MACD, Moving Averages, Bollinger Bands, Stochastic, Volume,
and ATR from price data. All parameters come from config.

Design — pure functional helpers
--------------------------------
Each ``_calc_*`` is a pure function: takes inputs, returns an
``IndicatorBlock`` carrying scores + indicators + signals it produced.
The orchestrator ``analyze`` merges blocks. Pre-2026-05-17 these
helpers mutated caller-supplied ``indicators``/``signals`` buffers,
which made unit-testing one indicator in isolation impractical
(callers had to set up shared mutable state). With the block return
type each helper is independently testable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class IndicatorBlock:
    """One indicator's contribution to the technical composite.

    ``scores`` is a list so multi-evaluation indicators (e.g. the
    moving-averages block which produces one score per SMA period +
    a golden/death cross score) can return all their scores in one
    block. The composite is the mean of all non-None scores across
    all blocks — matching the pre-refactor aggregation exactly.
    """

    scores: list[float] = field(default_factory=list)
    indicators: dict = field(default_factory=dict)
    signals: list[dict] = field(default_factory=list)

    def add_score(self, value: Optional[float]) -> None:
        if value is not None:
            self.scores.append(float(value))


def _merge_blocks(blocks: list[IndicatorBlock]) -> tuple[dict, list, float]:
    """Combine block deltas into the final (indicators, signals, score) shape."""
    indicators: dict = {}
    signals: list = []
    all_scores: list[float] = []
    for b in blocks:
        indicators.update(b.indicators)
        signals.extend(b.signals)
        all_scores.extend(b.scores)
    composite = float(np.mean(all_scores)) if all_scores else 50.0
    return indicators, signals, composite


def analyze(df: Optional[pd.DataFrame], config) -> dict:
    """Run full technical analysis on OHLCV data.

    Args:
        df: DataFrame with Open, High, Low, Close, Volume columns.
            None or fewer than 50 rows returns a neutral-50 result
            tagged with ``error="Insufficient data"`` which the engine's
            ``_infer_status`` excludes from the weighted denominator.
        config: Config object

    Returns:
        dict with keys: indicators, signals, score (0-100)
    """
    if df is None or len(df) < 50:
        return {"indicators": {}, "signals": [], "score": 50, "error": "Insufficient data"}

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    blocks: list[IndicatorBlock] = []

    # Moving averages (SMAs + Golden/Death cross + EMAs).
    blocks.append(_calc_moving_averages(close, config))

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
        blocks.append(_calc_rsi_stoch_merged(close, high, low, config))
        blocks.append(_calc_macd(close, config))
        blocks.append(_calc_bollinger(close, config))
        blocks.append(_calc_volume(volume, config))
    else:
        blocks.append(_calc_rsi(close, config))
        blocks.append(_calc_macd(close, config))
        blocks.append(_calc_bollinger(close, config))
        blocks.append(_calc_volume(volume, config))
        blocks.append(_calc_stochastic(high, low, close, config))

    blocks.append(_calc_regression_slope_momentum(close, config))

    # ATR contributes no score (used for stop-loss/take-profit only).
    blocks.append(_calc_atr(high, low, close, config))

    indicators, signals, composite = _merge_blocks(blocks)

    return {
        "indicators": indicators,
        "signals": signals,
        "score": round(composite, 2),
    }


# --- Indicator helpers (each returns an IndicatorBlock) ---------------


def _calc_moving_averages(close: pd.Series, config) -> IndicatorBlock:
    """SMAs, EMAs, and Golden/Death cross detection.

    Multi-score block: one score per SMA period (60-80 bullish / 20-40
    bearish band depending on distance from the SMA) plus one
    Golden/Death cross score when applicable.
    """
    block = IndicatorBlock()
    sma_periods = config.get("technical_indicators", "sma_periods", default=[20, 50, 200])
    ema_periods = config.get("technical_indicators", "ema_periods", default=[9, 12, 26])
    current_price = close.iloc[-1]

    # Price-vs-SMA scoring is a "distance band": being above the SMA is
    # baseline 60 (mild bullish) and being further above adds up to +20
    # points (cap). The coefficient 200 means a 10% distance fills the
    # full 20-point bonus: (1.10 - 1) * 200 = 20. Below the SMA mirrors.
    # The 60/40 baseline and 20-pt cap match the band the recommender
    # uses for "moderate" technical signals — see the RSI/MACD bands
    # below which top out at 70-90 for stronger setups so SMA distance
    # alone never dominates the technical composite.
    _SMA_BASELINE_BULL = 60
    _SMA_BASELINE_BEAR = 40
    _SMA_DISTANCE_CAP = 20      # max ±points from baseline
    _SMA_DISTANCE_COEF = 200    # 1% distance → 2 points
    for period in sma_periods:
        if len(close) < period:
            continue
        sma = close.rolling(window=period).mean()
        block.indicators[f"sma_{period}"] = round(float(sma.iloc[-1]), 2)

        if current_price > sma.iloc[-1]:
            block.signals.append({
                "type": "bullish", "source": f"SMA{period}",
                "detail": f"Price above SMA{period}",
            })
            block.add_score(_SMA_BASELINE_BULL + min(
                _SMA_DISTANCE_CAP,
                (current_price / sma.iloc[-1] - 1) * _SMA_DISTANCE_COEF,
            ))
        else:
            block.signals.append({
                "type": "bearish", "source": f"SMA{period}",
                "detail": f"Price below SMA{period}",
            })
            block.add_score(_SMA_BASELINE_BEAR - min(
                _SMA_DISTANCE_CAP,
                (1 - current_price / sma.iloc[-1]) * _SMA_DISTANCE_COEF,
            ))

    # Golden Cross / Death Cross (SMA50 vs SMA200)
    if len(close) >= 200 and 50 in sma_periods and 200 in sma_periods:
        sma50 = close.rolling(window=50).mean()
        sma200 = close.rolling(window=200).mean()
        sma50_prev = sma50.iloc[-2]
        sma200_prev = sma200.iloc[-2]
        sma50_now = sma50.iloc[-1]
        sma200_now = sma200.iloc[-1]

        if sma50_prev <= sma200_prev and sma50_now > sma200_now:
            block.signals.append({
                "type": "bullish", "source": "GoldenCross",
                "detail": "SMA50 crossed above SMA200",
            })
            block.indicators["golden_cross"] = True
            block.add_score(90)
        elif sma50_prev >= sma200_prev and sma50_now < sma200_now:
            block.signals.append({
                "type": "bearish", "source": "DeathCross",
                "detail": "SMA50 crossed below SMA200",
            })
            block.indicators["death_cross"] = True
            block.add_score(10)

    # EMAs are computed for display only (no score contribution).
    for period in ema_periods:
        if len(close) < period:
            continue
        ema = close.ewm(span=period, adjust=False).mean()
        block.indicators[f"ema_{period}"] = round(float(ema.iloc[-1]), 2)

    return block


def _calc_rsi(close: pd.Series, config) -> IndicatorBlock:
    """RSI with overbought/oversold bands."""
    block = IndicatorBlock()
    period = config.get("technical_indicators", "rsi", "period", default=14)
    overbought = config.get("technical_indicators", "rsi", "overbought", default=70)
    oversold = config.get("technical_indicators", "rsi", "oversold", default=30)

    if len(close) < period + 1:
        return block

    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()

    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi_value = float(rsi.iloc[-1])
    block.indicators["rsi"] = round(rsi_value, 2)

    if rsi_value <= oversold:
        block.signals.append({
            "type": "bullish", "source": "RSI",
            "detail": f"Oversold at {rsi_value:.1f}",
        })
        # Lower RSI = more bullish (potential reversal up).
        block.add_score(70 + (oversold - rsi_value))
    elif rsi_value >= overbought:
        block.signals.append({
            "type": "bearish", "source": "RSI",
            "detail": f"Overbought at {rsi_value:.1f}",
        })
        block.add_score(30 - (rsi_value - overbought))
    else:
        # Neutral zone, slight bullish bias below 50.
        block.add_score(50 + (50 - rsi_value) * 0.3)

    return block


def _calc_macd(close: pd.Series, config) -> IndicatorBlock:
    """MACD line, signal line, and histogram acceleration."""
    block = IndicatorBlock()
    fast = config.get("technical_indicators", "macd", "fast_period", default=12)
    slow = config.get("technical_indicators", "macd", "slow_period", default=26)
    signal_period = config.get("technical_indicators", "macd", "signal_period", default=9)

    if len(close) < slow + signal_period:
        return block

    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line

    block.indicators["macd_line"] = round(float(macd_line.iloc[-1]), 4)
    block.indicators["macd_signal"] = round(float(signal_line.iloc[-1]), 4)
    block.indicators["macd_histogram"] = round(float(histogram.iloc[-1]), 4)

    macd_now = macd_line.iloc[-1]
    signal_now = signal_line.iloc[-1]
    macd_prev = macd_line.iloc[-2]
    signal_prev = signal_line.iloc[-2]
    hist_now = histogram.iloc[-1]
    hist_prev = histogram.iloc[-2]

    score = 50

    if macd_prev <= signal_prev and macd_now > signal_now:
        block.signals.append({"type": "bullish", "source": "MACD", "detail": "Bullish crossover"})
        score = 75
    elif macd_prev >= signal_prev and macd_now < signal_now:
        block.signals.append({"type": "bearish", "source": "MACD", "detail": "Bearish crossover"})
        score = 25

    if hist_now > 0 and hist_now > hist_prev:
        block.signals.append({"type": "bullish", "source": "MACD", "detail": "Histogram accelerating up"})
        score = min(score + 10, 90)
    elif hist_now < 0 and hist_now < hist_prev:
        block.signals.append({"type": "bearish", "source": "MACD", "detail": "Histogram accelerating down"})
        score = max(score - 10, 10)

    block.add_score(score)
    return block


def _calc_bollinger(close: pd.Series, config) -> IndicatorBlock:
    """Bollinger Bands, position-within-band, squeeze detection."""
    block = IndicatorBlock()
    period = config.get("technical_indicators", "bollinger", "period", default=20)
    std_dev = config.get("technical_indicators", "bollinger", "std_dev", default=2.0)

    if len(close) < period:
        return block

    sma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std

    block.indicators["bb_upper"] = round(float(upper.iloc[-1]), 2)
    block.indicators["bb_middle"] = round(float(sma.iloc[-1]), 2)
    block.indicators["bb_lower"] = round(float(lower.iloc[-1]), 2)

    current_price = close.iloc[-1]
    bb_width = (upper.iloc[-1] - lower.iloc[-1]) / sma.iloc[-1]
    block.indicators["bb_width"] = round(float(bb_width), 4)

    avg_width = ((upper - lower) / sma).rolling(window=period).mean()
    if not avg_width.empty and avg_width.iloc[-1] > 0:
        squeeze_ratio = bb_width / avg_width.iloc[-1]
        block.indicators["bb_squeeze_ratio"] = round(float(squeeze_ratio), 2)
        if squeeze_ratio < 0.5:
            block.signals.append({
                "type": "neutral", "source": "Bollinger",
                "detail": "Squeeze detected - breakout imminent",
            })

    # Endpoints: touching the lower band = mean-reversion long setup
    # (score 70), touching the upper band = mean-reversion short setup
    # (score 30). The 70/30 baseline matches the band the technical
    # composite uses for "single-indicator buy/sell" — see RSI's
    # oversold/overbought banding which uses the same magnitudes.
    #
    # Interior linear map: band_pos ∈ [0, 1] → score ∈ [70, 30] with the
    # midline at 50. The coefficient 40 makes the map continuous with
    # the endpoint scores (band_pos=0 → 50 + 0.5*40 = 70, band_pos=1 →
    # 50 - 0.5*40 = 30). Lower position = more bullish per the Bollinger
    # mean-reversion convention.
    if current_price <= lower.iloc[-1]:
        block.signals.append({
            "type": "bullish", "source": "Bollinger",
            "detail": "Price at/below lower band",
        })
        block.add_score(70)
    elif current_price >= upper.iloc[-1]:
        block.signals.append({
            "type": "bearish", "source": "Bollinger",
            "detail": "Price at/above upper band",
        })
        block.add_score(30)
    else:
        band_pos = (current_price - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1])
        block.indicators["bb_position"] = round(float(band_pos), 2)
        block.add_score(50 + (0.5 - band_pos) * 40)

    return block


def _calc_volume(volume: pd.Series, config) -> IndicatorBlock:
    """Volume spike + trend detection."""
    block = IndicatorBlock()
    avg_period = config.get("technical_indicators", "volume", "avg_period", default=20)
    spike_mult = config.get("technical_indicators", "volume", "spike_multiplier", default=2.0)

    if len(volume) < avg_period:
        return block

    avg_vol = volume.rolling(window=avg_period).mean()
    current_vol = volume.iloc[-1]
    vol_ratio = current_vol / avg_vol.iloc[-1] if avg_vol.iloc[-1] > 0 else 1.0

    block.indicators["volume_current"] = int(current_vol)
    block.indicators["volume_avg"] = int(avg_vol.iloc[-1])
    block.indicators["volume_ratio"] = round(float(vol_ratio), 2)

    if len(volume) >= avg_period:
        vol_5d = volume.tail(5).mean()
        block.indicators["volume_trend"] = round(float(vol_5d / avg_vol.iloc[-1]), 2)

    if vol_ratio >= spike_mult:
        block.signals.append({
            "type": "neutral", "source": "Volume",
            "detail": f"Volume spike: {vol_ratio:.1f}x average",
        })
        block.add_score(65)  # Unusual volume is slightly bullish (attention).
    elif vol_ratio < 0.5:
        block.add_score(45)  # Low volume = less conviction.
    else:
        block.add_score(50)
    return block


def _calc_stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series, config,
) -> IndicatorBlock:
    """Stochastic %K and %D with overbought/oversold bands."""
    block = IndicatorBlock()
    k_period = config.get("technical_indicators", "stochastic", "k_period", default=14)
    d_period = config.get("technical_indicators", "stochastic", "d_period", default=3)
    overbought = config.get("technical_indicators", "stochastic", "overbought", default=80)
    oversold = config.get("technical_indicators", "stochastic", "oversold", default=20)

    if len(close) < k_period + d_period:
        return block

    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()

    denom = highest_high - lowest_low
    denom = denom.replace(0, np.nan)
    k = 100 * (close - lowest_low) / denom
    d = k.rolling(window=d_period).mean()

    k_value = float(k.iloc[-1])
    d_value = float(d.iloc[-1])
    block.indicators["stoch_k"] = round(k_value, 2)
    block.indicators["stoch_d"] = round(d_value, 2)

    if k_value <= oversold and d_value <= oversold:
        block.signals.append({
            "type": "bullish", "source": "Stochastic",
            "detail": f"Oversold: K={k_value:.0f}, D={d_value:.0f}",
        })
        block.add_score(70)
    elif k_value >= overbought and d_value >= overbought:
        block.signals.append({
            "type": "bearish", "source": "Stochastic",
            "detail": f"Overbought: K={k_value:.0f}, D={d_value:.0f}",
        })
        block.add_score(30)
    else:
        block.add_score(50 + (50 - k_value) * 0.2)
    return block


def _calc_rsi_stoch_merged(
    close: pd.Series, high: pd.Series, low: pd.Series, config,
) -> IndicatorBlock:
    """Merged momentum oscillator: average of RSI + Stochastic scores
    with a single ``MomOsc`` signal that fires only when both agree.

    Computes RSI and Stochastic blocks via the standalone helpers,
    keeps their indicators (rsi, stoch_k, stoch_d), and synthesizes a
    single agreement signal — discarding the per-indicator signals so
    the consensus path doesn't double-count.

    Returns an empty block when neither sub-indicator has enough bars.
    Returns the single non-None sub-score when only one fires — keeps
    information when one indicator has enough history and the other
    doesn't.
    """
    block = IndicatorBlock()
    rsi_block = _calc_rsi(close, config)
    stoch_block = _calc_stochastic(high, low, close, config)

    # Merge the diagnostic indicators (rsi value, stoch_k/d).
    block.indicators.update(rsi_block.indicators)
    block.indicators.update(stoch_block.indicators)

    rsi_score = rsi_block.scores[0] if rsi_block.scores else None
    stoch_score = stoch_block.scores[0] if stoch_block.scores else None

    if rsi_score is None and stoch_score is None:
        return block
    if rsi_score is None:
        block.add_score(stoch_score)
        return block
    if stoch_score is None:
        block.add_score(rsi_score)
        return block

    rsi_signal = next((s for s in rsi_block.signals if s["source"] == "RSI"), None)
    stoch_signal = next((s for s in stoch_block.signals if s["source"] == "Stochastic"), None)
    rsi_type = rsi_signal["type"] if rsi_signal else None
    stoch_type = stoch_signal["type"] if stoch_signal else None

    if rsi_type == "bullish" and stoch_type == "bullish":
        block.signals.append({
            "type": "bullish", "source": "MomOsc",
            "detail": (
                f"RSI {block.indicators.get('rsi')} + Stoch K "
                f"{block.indicators.get('stoch_k')} both oversold"
            ),
        })
    elif rsi_type == "bearish" and stoch_type == "bearish":
        block.signals.append({
            "type": "bearish", "source": "MomOsc",
            "detail": (
                f"RSI {block.indicators.get('rsi')} + Stoch K "
                f"{block.indicators.get('stoch_k')} both overbought"
            ),
        })
    # When the two disagree, no signal — the averaged score already
    # represents the conflict; emitting a signal in that case would
    # reintroduce the double-counting we're trying to kill.

    block.add_score((rsi_score + stoch_score) / 2.0)
    return block


def _calc_atr(
    high: pd.Series, low: pd.Series, close: pd.Series, config,
) -> IndicatorBlock:
    """Average True Range — recorded as an indicator, never scored.

    Used by the recommender for stop-loss/take-profit sizing, so it
    must populate ``atr`` and ``atr_pct`` in the indicator dict but
    contribute nothing to the technical composite.
    """
    block = IndicatorBlock()
    period = config.get("technical_indicators", "atr", "period", default=14)
    if len(close) < period + 1:
        return block

    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()

    block.indicators["atr"] = round(float(atr.iloc[-1]), 2)
    block.indicators["atr_pct"] = round(float(atr.iloc[-1] / close.iloc[-1] * 100), 2)
    return block


def _calc_regression_slope_momentum(close: pd.Series, config) -> IndicatorBlock:
    """Clenow's "Stocks on the Move" momentum: annualized exponential regression
    slope multiplied by R^2 of the fit. Penalizes choppy moves, rewards smooth
    trends. Audited via Alpha Architect's QMOM ETF methodology family and
    independently replicated on QuantConnect.

    Returns a block whose score is in [0, 100]; 50 is neutral.
    """
    block = IndicatorBlock()
    period = config.get("technical_indicators", "regression_momentum", "period", default=90)
    if len(close) < period + 1:
        return block

    series = close.iloc[-period:].astype(float).to_numpy()
    if (series <= 0).any():
        return block

    log_prices = np.log(series)
    x = np.arange(period)
    x_mean = x.mean()
    y_mean = log_prices.mean()
    slope = ((x - x_mean) * (log_prices - y_mean)).sum() / ((x - x_mean) ** 2).sum()
    y_pred = y_mean + slope * (x - x_mean)
    ss_res = ((log_prices - y_pred) ** 2).sum()
    ss_tot = ((log_prices - y_mean) ** 2).sum()
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    annualized_slope_pct = (np.exp(slope * 252) - 1) * 100
    clenow_score_raw = annualized_slope_pct * r_squared

    block.indicators["regression_slope_pct"] = round(float(annualized_slope_pct), 2)
    block.indicators["regression_r_squared"] = round(float(r_squared), 3)
    block.indicators["clenow_momentum"] = round(float(clenow_score_raw), 2)

    # Map raw Clenow score to 0-100. A score of 0 = 50. A score of +50 = ~80.
    # Empirically S&P 500 leaders cluster in the +20 to +100 range.
    if clenow_score_raw <= 0:
        score = max(20.0, 50.0 + clenow_score_raw)
    else:
        # Diminishing-returns mapping: 50 + 30 * (1 - exp(-x/40))
        score = 50.0 + 30.0 * (1.0 - np.exp(-clenow_score_raw / 40.0))

    if clenow_score_raw > 40 and r_squared > 0.7:
        block.signals.append({
            "type": "bullish", "source": "ClenowMomentum",
            "detail": f"Smooth uptrend: slope {annualized_slope_pct:.0f}%/yr, R^2 {r_squared:.2f}",
        })
    elif clenow_score_raw < -40 and r_squared > 0.7:
        block.signals.append({
            "type": "bearish", "source": "ClenowMomentum",
            "detail": f"Smooth downtrend: slope {annualized_slope_pct:.0f}%/yr, R^2 {r_squared:.2f}",
        })

    block.add_score(score)
    return block
