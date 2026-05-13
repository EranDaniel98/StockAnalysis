"""Sector-ETF flow analyzer.

Money flowing into a sector ETF tends to lead the price action of its
member stocks by roughly 2-4 weeks. The canonical evidence is Boyer
(2011) on style-level co-movement and Wurgler's "index inclusion
premium" line of work, plus Ben-David / Franzoni / Moussawi on
ETF-driven price pressure. We proxy "flow" with the joint signature
of recent sector-ETF price action and relative volume — true creation/
redemption data isn't on the free tier, but the price+volume combo
captures the same demand pulse.

Pure function over the SECTOR ETF's OHLCV bars:

  ``analyze(sector_etf_df, *, as_of, params=None) -> dict | None``

Caller is responsible for resolving ticker -> sector -> ETF symbol via
``SECTOR_TO_ETF`` and passing the right slice. Keeping the lookup out of
the analyzer leaves it deterministic, easy to unit-test with synthetic
series, and trivially swappable for any future flow proxy (e.g. real
fund flows from issuer filings).

Returns ``None`` when there isn't enough ETF history to compute the
3-month momentum leg — same convention as the rest of the pipeline,
the composite engine then skips this sub-score rather than forcing 50.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


# GICS-style sector names yfinance reports map onto the SPDR Select
# Sector ETF family. We accept both "Financial Services" (yfinance's
# usual label) and "Financials" (the GICS canonical name) — same ETF.
SECTOR_TO_ETF: dict[str, str] = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Financials": "XLF",
    "Energy": "XLE",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Industrials": "XLI",
    "Communication Services": "XLC",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
}


@dataclass(frozen=True)
class SectorFlowsParams:
    """Tunable knobs. Defaults track the 2-4 week lead-lag horizon
    documented in the ETF-flow literature.

    * 20 trading days ~ one calendar month — the short flow proxy.
    * 60 trading days ~ one calendar quarter — the volume baseline.
    * 63 trading days ~ 3 months — the slower momentum confirmation.

    The bullish thresholds (>+5% / volume ratio >1.3) and bearish
    threshold (<-5%, crash <-10%) follow the same band-shape we use
    for the other technical sub-scores so the composite weights don't
    have to special-case this one.
    """

    short_window: int = 20
    long_window: int = 60
    momentum_window: int = 63
    bullish_return: float = 0.05
    mild_bullish_return: float = 0.02
    bearish_return: float = -0.05
    crash_return: float = -0.10
    volume_surge_ratio: float = 1.3
    min_history_bars: int = 63


def _as_naive_ts(ts: pd.Timestamp) -> pd.Timestamp:
    """Normalize tz-aware vs tz-naive timestamps the same way the rest
    of the codebase does — drop tz so comparison against a naive
    DatetimeIndex (the common case for daily bars) doesn't raise."""
    ts = pd.Timestamp(ts)
    if ts.tz is not None:
        ts = ts.tz_localize(None)
    return ts


def _slice_before(df: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Keep only rows strictly before ``as_of``. Same convention as the
    other as-of analyzers — the bar dated ``as_of`` itself is excluded
    because in practice we score Sunday-for-Monday and that day's bar
    isn't yet in the history when we run."""
    if not isinstance(df.index, pd.DatetimeIndex):
        return df
    idx = df.index
    if idx.tz is not None:
        idx = idx.tz_localize(None)
        df = df.copy()
        df.index = idx
    return df.loc[df.index < as_of]


def _score_from_flow(
    ret_20d: float,
    vol_ratio: float,
    momentum_3m: float,
    params: SectorFlowsParams,
) -> int:
    """Map (short return, volume ratio, momentum) to a 0-100 score.

    Bands:
      * Strong inflow (ret > +5% AND vol_ratio > 1.3): 75-85.
        Higher within band when 3M momentum confirms.
      * Mild inflow (ret > +2%): 60-65, lifted to 65 on volume surge.
      * Sideways (-2% .. +2%): 50.
      * Outflow (ret < -5%): 30-35.
      * Crash + volume surge (ret < -10%, vol_ratio > 1.3): 15-20 —
        capitulation tape; sometimes a buy-the-dip setup, but we
        lean bearish for safety as the literature on selling-pressure
        events (Coval & Stafford 2007) shows continuation more often
        than reversal.
    """
    surge = vol_ratio > params.volume_surge_ratio

    if ret_20d < params.crash_return and surge:
        return 15 if momentum_3m < 0 else 20

    if ret_20d > params.bullish_return and surge:
        return 85 if momentum_3m > 0 else 75

    if ret_20d > params.mild_bullish_return:
        return 65 if surge else 60

    if ret_20d < params.bearish_return:
        return 30 if momentum_3m < 0 else 35

    return 50


def analyze(
    sector_etf_df: Optional[pd.DataFrame],
    *,
    as_of: pd.Timestamp,
    params: SectorFlowsParams | None = None,
    etf_symbol: Optional[str] = None,
) -> Optional[dict]:
    """Score the sector ETF's recent flow pattern on a 0-100 scale.

    The caller resolves ticker -> sector -> ETF and passes the ETF
    slice — this keeps the analyzer pure, deterministic, and trivial
    to unit-test with synthetic series. The optional ``etf_symbol`` is
    passed through into the result for downstream display (the
    analyzer doesn't need it to compute the score).

    Returns None when the ETF has fewer than ``min_history_bars`` rows
    before ``as_of``; composite engine treats None as "skip this
    sub-score" the same way it does for alpha158 / RS / insider_flow.
    """
    params = params or SectorFlowsParams()

    if sector_etf_df is None or sector_etf_df.empty:
        return None
    if "Close" not in sector_etf_df.columns:
        return None

    as_of_ts = _as_naive_ts(as_of)
    hist = _slice_before(sector_etf_df, as_of_ts)
    if len(hist) < params.min_history_bars:
        return None

    closes = hist["Close"].astype(float)
    if closes.iloc[-params.short_window] <= 0 or closes.iloc[-params.momentum_window] <= 0:
        return None

    ret_20d = float(closes.iloc[-1] / closes.iloc[-params.short_window] - 1.0)
    momentum_3m = float(closes.iloc[-1] / closes.iloc[-params.momentum_window] - 1.0)

    # Volume ratio: short window's avg volume vs long window's avg.
    # Missing Volume column is tolerated (some Parquet rebuilds drop it)
    # — fall back to a neutral 1.0 so the score logic still works.
    if "Volume" in hist.columns and len(hist) >= params.long_window:
        vol = hist["Volume"].astype(float)
        short_avg = float(vol.iloc[-params.short_window:].mean())
        long_avg = float(vol.iloc[-params.long_window:].mean())
        vol_ratio = short_avg / long_avg if long_avg > 0 else 1.0
    else:
        vol_ratio = 1.0

    if not np.isfinite(ret_20d) or not np.isfinite(momentum_3m) or not np.isfinite(vol_ratio):
        return None

    score = _score_from_flow(ret_20d, vol_ratio, momentum_3m, params)

    signals: list[dict] = []
    if score >= 70:
        signals.append({
            "type": "bullish",
            "source": "SectorFlows",
            "detail": (
                f"ETF up {ret_20d * 100:.1f}% (20d), "
                f"volume {vol_ratio:.2f}x baseline"
            ),
        })
    elif score <= 35:
        signals.append({
            "type": "bearish",
            "source": "SectorFlows",
            "detail": (
                f"ETF down {ret_20d * 100:.1f}% (20d), "
                f"volume {vol_ratio:.2f}x baseline"
            ),
        })

    return {
        "score": int(score),
        "signals": signals,
        "sector_etf": etf_symbol,
        "flow_indicator": round(ret_20d, 4),
        "indicators": {
            "etf_return_20d": round(ret_20d * 100, 2),
            "etf_volume_ratio_20d": round(vol_ratio, 3),
            "etf_momentum_3m": round(momentum_3m * 100, 2),
        },
    }
