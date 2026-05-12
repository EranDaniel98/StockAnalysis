"""Relative Strength vs benchmark (SPY).

Stocks outperforming the broad index across multiple windows tend to keep
outperforming — the canonical RS/momentum edge documented by O'Neill (IBD
RS Rating), Minervini, and academic momentum literature (Jegadeesh &
Titman 1993). This analyzer encodes the multi-window IBD weighting
(40/30/20/10 across 12M/6M/3M/1M) and scores the result 0-100 like every
other analyzer in the pipeline.

Inputs:
  - df: stock OHLCV history
  - benchmark_df: same-shape benchmark series (typically SPY)
  - config: project Config; reads ``scoring.relative_strength.windows``
    + ``scoring.relative_strength.weights`` if present, else defaults.

Returns ``None`` when the benchmark is missing or either series is
shorter than the longest lookback — the composite engine handles None
the same way it does for alpha158 (skips the sub-score).
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# IBD-style weighting: longer-term outperformance counts more, but recent
# strength still matters. Sums to 1.0 so the weighted average is a clean
# percentage delta.
DEFAULT_WINDOWS_DAYS: tuple[int, ...] = (252, 126, 63, 21)  # 12M, 6M, 3M, 1M
DEFAULT_WEIGHTS: tuple[float, ...] = (0.40, 0.30, 0.20, 0.10)


def _aligned_returns(
    stock_df: pd.DataFrame, bench_df: pd.DataFrame, window: int
) -> Optional[tuple[float, float]]:
    """Compute (stock_return, bench_return) over the last ``window``
    trading days using the intersection of the two indices.

    Returns None when either series has fewer than ``window`` bars in
    the common range — we can't fairly compare a 3-month-old IPO
    against SPY's 12-month return.
    """
    if stock_df is None or bench_df is None or window < 2:
        return None
    if "Close" not in stock_df.columns or "Close" not in bench_df.columns:
        return None
    common_idx = stock_df.index.intersection(bench_df.index)
    if len(common_idx) < window:
        return None
    stock_aligned = stock_df.loc[common_idx, "Close"].dropna()
    bench_aligned = bench_df.loc[common_idx, "Close"].dropna()
    if len(stock_aligned) < window or len(bench_aligned) < window:
        return None
    s0 = float(stock_aligned.iloc[-window])
    s1 = float(stock_aligned.iloc[-1])
    b0 = float(bench_aligned.iloc[-window])
    b1 = float(bench_aligned.iloc[-1])
    if s0 <= 0 or b0 <= 0:
        return None
    return (s1 / s0 - 1.0), (b1 / b0 - 1.0)


def _score_from_rs(rs: float) -> int:
    """Map weighted relative-strength delta (decimal — 0.10 = 10 pts
    outperformance) to a 0-100 score.

    Bands chosen so the score lands in the same neighborhoods as the
    other technical sub-scores: small outperformance is mildly
    bullish, double-digit outperformance is strongly bullish.
    """
    if rs >= 0.20:
        return 90
    if rs >= 0.10:
        return 80
    if rs >= 0.03:
        return 65
    if rs >= -0.03:
        return 50
    if rs >= -0.10:
        return 35
    if rs >= -0.20:
        return 20
    return 10


def analyze(
    df: Optional[pd.DataFrame],
    benchmark_df: Optional[pd.DataFrame],
    config,
) -> Optional[dict]:
    """Score the stock's relative strength vs the benchmark.

    Returns None when the benchmark is missing or the stock has
    insufficient history; composite scoring then skips this sub-score.
    """
    if df is None or benchmark_df is None:
        return None
    if df.empty or benchmark_df.empty:
        return None

    cfg = config.get("scoring", "relative_strength", default={}) if hasattr(config, "get") else {}
    windows = tuple(cfg.get("windows_days", DEFAULT_WINDOWS_DAYS))
    weights = tuple(cfg.get("weights", DEFAULT_WEIGHTS))
    if len(windows) != len(weights):
        # Mismatched config — fall back to defaults rather than crash so
        # a typo in YAML doesn't take the scan down.
        logger.warning(
            "relative_strength windows/weights length mismatch (%d vs %d); "
            "using defaults.", len(windows), len(weights),
        )
        windows = DEFAULT_WINDOWS_DAYS
        weights = DEFAULT_WEIGHTS

    weight_sum = sum(weights)
    if weight_sum <= 0:
        return None
    weights = tuple(w / weight_sum for w in weights)

    indicators: dict[str, float] = {}
    weighted_rs = 0.0
    used_weight = 0.0

    for window, w in zip(windows, weights):
        pair = _aligned_returns(df, benchmark_df, window)
        if pair is None:
            continue
        stock_ret, bench_ret = pair
        rs = stock_ret - bench_ret
        indicators[f"rs_{window}d"] = round(rs * 100, 2)
        indicators[f"stock_ret_{window}d"] = round(stock_ret * 100, 2)
        indicators[f"bench_ret_{window}d"] = round(bench_ret * 100, 2)
        weighted_rs += rs * w
        used_weight += w

    if used_weight == 0:
        # No window produced a valid pair — typically an IPO with < 21d
        # of history. Composite engine treats None as "skip this sub".
        return None

    # Re-normalize when some windows were skipped so the partial
    # average still sits on a 0..1 weight base.
    weighted_rs /= used_weight
    indicators["weighted_rs"] = round(weighted_rs * 100, 2)
    indicators["coverage"] = round(used_weight, 2)

    score = _score_from_rs(weighted_rs)
    signals: list[dict] = []
    if weighted_rs >= 0.10:
        signals.append({
            "type": "bullish",
            "source": "Relative Strength",
            "detail": f"+{weighted_rs*100:.1f}% vs benchmark (weighted)",
        })
    elif weighted_rs <= -0.10:
        signals.append({
            "type": "bearish",
            "source": "Relative Strength",
            "detail": f"{weighted_rs*100:.1f}% vs benchmark (weighted)",
        })

    return {
        "score": score,
        "signals": signals,
        "indicators": indicators,
        "weighted_rs": weighted_rs,
    }
