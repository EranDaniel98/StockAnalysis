"""Post-Earnings-Announcement Drift (PEAD) detector.

PEAD is one of the most replicated anomalies in finance literature
(Ball & Brown 1968; Bernard & Thomas 1989/1990; Chordia & Shivakumar 2006;
Garfinkel et al. 2024). Stocks that report large positive earnings
surprises tend to continue drifting upward for ~60 trading days
post-announcement; conversely for large negative surprises. The drift is
driven by analyst underreaction and slow information diffusion, and its
strength scales with the magnitude of the standardized earnings surprise
(SUE) relative to consensus.

What this module computes
-------------------------
For a given ticker on a given as-of date, we look at the most recent
earnings announcement that falls inside the drift window (default 60
calendar days back). We then:

  1. **Surprise magnitude band.** Map the actual-vs-consensus surprise to a
     0-100 score band. Large beats land in the 70-85 range, large misses
     in the 15-30 range, in-line prints near 50.
     (Bernard & Thomas 1989 showed top-decile SUE earned ~6% abnormal
     return in the 60 days following announcement.)

  2. **Drift decay.** Score is at full strength on days +1..+5
     post-announcement (the market needs a few days to slow-walk the
     reaction). Beyond day +5, the score linearly fades toward the
     neutral 50 baseline by day +drift_window_days. After the window
     closes the drift_window_active flag goes False and the score
     snaps to 50.

  3. **Multi-earnings memory bonus.** If the prior 2-3 earnings prints
     were all beats (or all misses), this is a stronger persistence
     signal than a one-off — Bernard & Thomas (1990) document
     autocorrelation in earnings surprises. Adds a small +/- nudge.

  4. **Volatility scaling.** When a recent price-history slice is
     supplied, we divide the surprise by the stock's daily-return
     std-dev to compute a quasi-SUE. This shrinks the apparent surprise
     for very noisy names where +10% beats happen routinely.

Backward compatibility
----------------------
The composite scoring engine reads ``composite_bonus`` (additive, not
weighted) — that legacy key is preserved with the original semantics.
The new ``score`` field (0-100, baseline 50) is added on top, gated by
drift_window_active so it stays at the neutral 50 outside the drift
window. New callers (the composite engine, the diagnostics page, the
backtest reporter) can pick whichever signal best matches their wiring.

Caveat
------
yfinance's ``get_earnings_dates`` returns surprises only for some
tickers and time windows. When data is missing the detector returns a
neutral no-bonus result with ``drift_window_active=False``.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# Surprise -> score band table. Tuples are (lower_pct_inclusive, score).
# Bands chosen to mirror the bullish-lean / strong-bullish / neutral /
# strong-bearish gradients used elsewhere in the codebase (insider_flow,
# catalyst). A 0% surprise sits at the 50 neutral baseline; a +10% beat
# lands at the 75 strong-bullish band; a -10% miss lands at the 25
# strong-bearish band.
#
# The lookup is "largest lower-bound <= surprise" — i.e. a +12% beat
# falls into the >=10% bucket and earns the top 85 score.
_SURPRISE_BANDS: tuple[tuple[float, int], ...] = (
    (20.0, 85),     # blowout
    (10.0, 75),     # strong beat
    (5.0, 65),      # solid beat
    (1.0, 55),      # mild beat
    (-1.0, 50),     # in-line
    (-5.0, 40),     # mild miss
    (-10.0, 30),    # solid miss
    (-20.0, 20),    # bad miss
    (-float("inf"), 15),  # disaster
)


def _band_score(surprise_pct: float) -> int:
    """Map a surprise percentage to the canonical PEAD score band."""
    for lower, score in _SURPRISE_BANDS:
        if surprise_pct >= lower:
            return score
    return 50  # unreachable given -inf sentinel, but typed-safe


def _drift_decay(days_since: int, window_days: int) -> float:
    """Bernard & Thomas drift envelope.

    Full weight on days +1..+5 (post-announcement reaction unfolds over
    the first trading week), then linear decay to 0 at day +window_days.
    Returns 0 outside the window so callers can short-circuit.
    """
    if days_since < 1 or days_since > window_days:
        return 0.0
    if days_since <= 5:
        return 1.0
    return max(0.0, 1.0 - (days_since - 5) / max(1, window_days - 5))


def _multi_beat_bonus(past_surprises: list[float]) -> float:
    """Bernard & Thomas (1990) autocorrelation bonus.

    If the trailing 2-3 prints are all beats (>= +1%) or all misses
    (<= -1%), the persistence signal is stronger than a one-off. Returns
    a +/- score-point nudge in the [-4, +4] range. Anything mixed
    returns 0.
    """
    if len(past_surprises) < 2:
        return 0.0
    trailing = past_surprises[:3]
    if all(s >= 1.0 for s in trailing):
        return 2.0 + min(2.0, (len(trailing) - 2))
    if all(s <= -1.0 for s in trailing):
        return -(2.0 + min(2.0, (len(trailing) - 2)))
    return 0.0


def _volatility_scale(
    surprise_pct: float,
    price_history: Optional[pd.DataFrame],
) -> tuple[float, Optional[float]]:
    """Shrink the surprise by the stock's recent daily-return std-dev.

    Quasi-SUE: a +10% beat on a 5%-daily-vol meme stock is much weaker
    than the same +10% on a 1%-daily-vol blue-chip. We divide the
    surprise by max(std, 1.0%) to keep the scaling bounded and clip
    the resulting multiplier to [0.4, 1.5] so volatility never fully
    erases or doubles the signal.

    Returns ``(scaled_surprise, daily_vol_pct)``. When no usable price
    slice is provided, returns the surprise unchanged and vol = None.
    """
    if price_history is None or len(price_history) < 20:
        return surprise_pct, None
    if "Close" not in price_history.columns:
        return surprise_pct, None
    closes = price_history["Close"].astype(float)
    rets = closes.pct_change().dropna()
    if len(rets) < 20:
        return surprise_pct, None
    vol_pct = float(rets.std() * 100.0)
    if not np.isfinite(vol_pct) or vol_pct <= 0:
        return surprise_pct, None
    # Reference vol of 2% daily ~ a typical mid-cap. Higher vol shrinks,
    # lower vol amplifies, both bounded.
    multiplier = float(np.clip(2.0 / max(vol_pct, 1.0), 0.4, 1.5))
    return surprise_pct * multiplier, vol_pct


def analyze(
    ticker: str,
    earnings_history: Optional[pd.DataFrame],
    as_of_date: Optional[pd.Timestamp] = None,
    drift_window_days: int = 60,
    min_surprise_pct: float = 5.0,
    max_bonus: float = 10.0,
    price_history: Optional[pd.DataFrame] = None,
) -> dict:
    """Compute the PEAD signal for a single ticker on a given as-of date.

    Args:
        ticker: stock symbol (for signal text)
        earnings_history: DataFrame from yfinance ``Ticker.get_earnings_dates()``
            (or any equivalent shape with a Surprise(%) / Reported EPS column
            and a DatetimeIndex). None or empty -> neutral output.
        as_of_date: pseudo-current date for backtesting. Defaults to now.
        drift_window_days: PEAD drift envelope length in calendar days. The
            Bernard & Thomas (1989) result is 60 trading days; 60 calendar
            days is a conservative approximation.
        min_surprise_pct: minimum |surprise %| for the additive
            composite_bonus to fire. The score-band output is unaffected
            (a small beat still nudges the score above 50).
        max_bonus: maximum +/- score-point bonus emitted as composite_bonus.
        price_history: optional DataFrame with a Close column for the
            same ticker, covering the run-up to as_of_date. When supplied,
            enables volatility-scaled surprise (quasi-SUE).

    Returns:
        dict with:
          score (0-100): banded PEAD score with drift decay applied. Snaps
            to 50 outside the drift window. Engine does NOT read this
            (PEAD is wired as an additive bonus, not a sub-score); kept for
            diagnostics and for future migration to weighted-average.
          composite_bonus (float): +/- score points the engine ADDS to the
            composite. Magnitude in [-max_bonus, +max_bonus]; gated by
            min_surprise_pct. Preserved for backward compatibility.
          surprise_pct (float | None): most recent in-window earnings
            surprise as a % of consensus (or None when missing).
          days_since_earnings (int | None): calendar days from the most
            recent announcement to as_of_date (None when no in-window
            print exists).
          drift_window_active (bool): True iff the latest announcement
            is in days +1..+drift_window_days.
          indicators (dict): pead_* fields for diagnostics.
          signals (list): standard bullish/bearish signal dicts.
    """
    indicators: dict = {}
    signals: list = []

    def _neutral(reason: str) -> dict:
        return {
            "score": 50,
            "composite_bonus": 0.0,
            "surprise_pct": None,
            "days_since_earnings": None,
            "drift_window_active": False,
            "indicators": indicators,
            "signals": signals,
            "reason": reason,
        }

    if earnings_history is None or getattr(earnings_history, "empty", True):
        return _neutral("no_earnings_history")

    if as_of_date is None:
        as_of_date = pd.Timestamp.now().normalize()
    else:
        as_of_date = pd.Timestamp(as_of_date)
        if as_of_date.tz is not None:
            as_of_date = as_of_date.tz_localize(None)

    # Normalize earnings_history index.
    try:
        eh = earnings_history.copy()
        if isinstance(eh.index, pd.DatetimeIndex) and eh.index.tz is not None:
            eh.index = eh.index.tz_localize(None)
        else:
            eh.index = pd.to_datetime(eh.index)
    except Exception as e:
        logger.debug(f"PEAD {ticker}: bad earnings index: {e}")
        return _neutral("bad_index")

    # All past prints (regardless of window) — needed for multi-beat memory.
    all_past = eh.loc[eh.index < as_of_date].sort_index(ascending=False)
    if all_past.empty:
        return _neutral("no_past_prints")

    # Past earnings inside the drift window.
    window_cutoff = as_of_date - pd.Timedelta(days=drift_window_days)
    in_window = all_past.loc[all_past.index >= window_cutoff]
    if in_window.empty:
        # There IS earnings history, but the latest print is stale.
        # Report the days_since for diagnostics; everything else stays neutral.
        latest_date = all_past.index.max()
        days_since = (as_of_date - latest_date).days
        indicators["pead_days_since_earnings"] = int(days_since)
        out = _neutral("stale_earnings")
        out["days_since_earnings"] = int(days_since)
        return out

    latest_date = in_window.index.max()
    latest_row = in_window.loc[latest_date]
    # yfinance can return duplicate rows at the same timestamp (rare but
    # real); .loc[ts] then yields a DataFrame, which breaks downstream
    # scalar extraction. Collapse to the first row.
    if isinstance(latest_row, pd.DataFrame):
        latest_row = latest_row.iloc[0]
    days_since = (as_of_date - latest_date).days
    indicators["pead_days_since_earnings"] = int(days_since)

    raw_surprise = _extract_surprise_pct(latest_row)
    if raw_surprise is None:
        out = _neutral("no_surprise_data")
        out["days_since_earnings"] = int(days_since)
        out["drift_window_active"] = True
        return out

    # Volatility scaling (optional). Reported surprise stays for diagnostics;
    # the scaled version drives the score.
    scaled_surprise, daily_vol_pct = _volatility_scale(raw_surprise, price_history)
    indicators["pead_surprise_pct"] = round(float(raw_surprise), 2)
    if daily_vol_pct is not None:
        indicators["pead_daily_vol_pct"] = round(daily_vol_pct, 3)
        indicators["pead_surprise_pct_scaled"] = round(float(scaled_surprise), 2)

    # Drift decay.
    decay = _drift_decay(days_since, drift_window_days)
    indicators["pead_drift_decay"] = round(float(decay), 3)
    drift_active = decay > 0.0

    # Multi-beat memory: look at past surprises strictly OLDER than the
    # latest in-window print so we don't double-count the trigger.
    older_rows = all_past.loc[all_past.index < latest_date].head(3)
    past_surprises: list[float] = []
    for _, row in older_rows.iterrows():
        s = _extract_surprise_pct(row)
        if s is not None:
            past_surprises.append(s)
    memory_bonus = _multi_beat_bonus(past_surprises)
    indicators["pead_memory_bonus"] = round(memory_bonus, 2)
    indicators["pead_prior_surprises"] = [round(s, 2) for s in past_surprises]

    # Banded score: anchor band -> apply drift decay back toward 50 ->
    # add memory bonus -> clip.
    band = _band_score(scaled_surprise)
    decayed = 50.0 + (band - 50.0) * decay
    final_score = float(np.clip(decayed + memory_bonus, 0.0, 100.0))
    if not drift_active:
        # Outside the window: score snaps to neutral. Memory bonus only
        # matters when there's an active trigger.
        final_score = 50.0

    # Legacy additive composite_bonus — preserved with the original
    # linear-scaling math so back-compat with the engine's bonus path is
    # byte-identical for in-range inputs.
    bonus = 0.0
    if drift_active and abs(scaled_surprise) >= min_surprise_pct:
        surprise_capped = float(np.clip(scaled_surprise, -50.0, 50.0))
        raw_bonus = (surprise_capped / 50.0) * max_bonus
        bonus = float(raw_bonus * decay)

    if drift_active and (final_score >= 60 or bonus > 1):
        signals.append({
            "type": "bullish",
            "source": "PEAD",
            "detail": (
                f"Positive earnings surprise {raw_surprise:+.1f}% "
                f"{days_since}d ago"
            ),
        })
    elif drift_active and (final_score <= 40 or bonus < -1):
        signals.append({
            "type": "bearish",
            "source": "PEAD",
            "detail": (
                f"Negative earnings surprise {raw_surprise:+.1f}% "
                f"{days_since}d ago"
            ),
        })

    return {
        "score": round(final_score, 2),
        "composite_bonus": round(bonus, 2),
        "surprise_pct": round(float(raw_surprise), 2),
        "days_since_earnings": int(days_since),
        "drift_window_active": bool(drift_active),
        "indicators": indicators,
        "signals": signals,
    }


def _extract_surprise_pct(row) -> Optional[float]:
    """Pull the surprise % from a yfinance earnings_dates row. Schema varies."""

    def _scalar(val):
        """Coerce a Series / array / scalar to a single float-or-None.

        DataFrame.loc[ts].get(col) can return a Series if there are duplicate
        timestamps; iterrows() on the dup-collapsed frame yields Series rows
        where .get returns scalars. Tolerate both.
        """
        if val is None:
            return None
        if isinstance(val, pd.Series):
            val = val.dropna()
            if val.empty:
                return None
            val = val.iloc[0]
        try:
            if pd.isna(val):
                return None
        except (TypeError, ValueError):
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    candidates = [
        "Surprise(%)", "Surprise (%)", "surprisePercent",
        "Earnings Surprise (%)", "earnings_surprise_pct",
    ]
    for key in candidates:
        if hasattr(row, "get"):
            scalar = _scalar(row.get(key))
            if scalar is not None:
                return scalar
    # Fallback: compute from EPS columns if present.
    actual = _scalar(row.get("EPS Estimate")) if hasattr(row, "get") else None
    reported = _scalar(row.get("Reported EPS")) if hasattr(row, "get") else None
    if actual is not None and reported is not None and actual != 0:
        return (reported - actual) / abs(actual) * 100
    return None


def fetch_earnings_history(ticker: str) -> Optional[pd.DataFrame]:
    """Fetch historical earnings dates + surprises via the shared cache.

    Returns a DataFrame indexed by datetime, or None on failure. Routed
    through ``src.scoring.earnings_cache`` so the 24 h parquet cache,
    DatetimeIndex restoration, tz normalization, and yfinance timeout
    wrapping all live in one place.
    """
    from src.scoring.earnings_cache import load_earnings_history

    return load_earnings_history(ticker)
