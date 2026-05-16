"""Post-Earnings Announcement Drift factor.

Bernard & Thomas (1989, 1990) — top-decile SUE (standardized unexpected
earnings) firms earn ~6% abnormal return in the 60 trading days
following announcement; bottom-decile firms underperform by ~5%. The
drift is attributed to analyst underreaction and slow information
diffusion, and it has survived every major out-of-sample re-test
(Chordia & Shivakumar 2006; Garfinkel et al. 2024).

What this module does
---------------------
Wraps ``src.scoring.analyzers.pead.analyze`` (which already encodes
the SUE banding, drift decay, multi-beat memory bonus, and
volatility-scaling) into the factor framework's standard output
``DataFrame[ticker, raw, rank, z_score]``.

Coverage model — important
--------------------------
Unlike momentum / quality / value (which exist for every ticker with
prices/fundamentals), PEAD only fires for firms with a recent in-
window earnings print. Roughly 60-70% of an S&P-500 universe will
have a usable PEAD signal at any given as-of date (quarterly earnings
cycle × 60-day window ÷ 90-day quarter).

We DROP tickers without an active drift window rather than scoring
them 50. With ``composite.combine(min_overlap=2)``, this means:

  - A ticker with momentum + quality + value but no PEAD → still
    qualifies (3 ≥ 2 overlap), unaffected by PEAD.
  - A ticker with PEAD + 1 other factor → qualifies, weighted in.
  - A ticker with ONLY PEAD → drops out (1 < 2 overlap).

This is the right model: missing PEAD should be neutral, not
bearish. Penalizing names without earnings prints would silently
favor newly-IPO'd / spun-off companies that haven't reported yet.

raw convention
--------------
``raw = score - 50``. Score is 0-100 with 50 = neutral. So:
  - +35 raw = blowout beat × full drift (top of band)
  - +5 raw = mild beat with most decay used up
  - -25 raw = solid miss × full drift
  - 0 raw = in-line print (won't fire min_surprise_pct gate)

Higher raw = better (consistent with momentum / quality / value
frames).
"""

from __future__ import annotations

import logging
from typing import Mapping, Optional

import numpy as np
import pandas as pd

from src.scoring.analyzers.pead import analyze as analyze_one

logger = logging.getLogger(__name__)


def pead_factor(
    earnings_histories: Mapping[str, Optional[pd.DataFrame]],
    as_of: pd.Timestamp | str,
    *,
    prices: Optional[Mapping[str, pd.DataFrame]] = None,
    drift_window_days: int = 60,
    min_surprise_pct: float = 5.0,
) -> pd.DataFrame:
    """Compute the cross-sectional PEAD factor at ``as_of``.

    Parameters
    ----------
    earnings_histories : mapping ticker -> earnings DataFrame in the
        yfinance ``get_earnings_dates()`` shape (DatetimeIndex,
        Surprise(%) / Reported EPS columns). Missing tickers or None
        values are silently skipped.
    as_of : the as-of date. Only earnings rows strictly before this
        date are considered (point-in-time safe).
    prices : optional mapping ticker -> OHLCV DataFrame. When supplied,
        enables the volatility-scaling step in the analyzer (shrinks
        the surprise for noisy names).
    drift_window_days : Bernard & Thomas drift envelope (60 calendar
        days; ~42 trading days). Passed through to the analyzer.
    min_surprise_pct : minimum |surprise %| for the additive
        composite_bonus to fire in the analyzer. Doesn't gate the
        score-band output, only the auxiliary bonus.

    Returns
    -------
    DataFrame with columns ``ticker, raw, rank, z_score`` sorted by
    rank ascending (rank 1 = strongest PEAD signal). Only tickers
    with ``drift_window_active=True`` are included; the rest are
    dropped so they neither help nor hurt the composite.
    """
    as_of_ts = pd.Timestamp(as_of)
    if as_of_ts.tz is not None:
        as_of_ts = as_of_ts.tz_localize(None)

    rows: list[dict] = []
    for ticker, hist in earnings_histories.items():
        if hist is None or hist.empty:
            continue
        price_slice = None
        if prices is not None:
            p = prices.get(ticker)
            if p is not None and not p.empty:
                # Pass only the run-up to as_of so the analyzer's
                # volatility-scale step is point-in-time safe.
                price_slice = p[p.index <= as_of_ts]
        result = analyze_one(
            ticker=ticker,
            earnings_history=hist,
            as_of_date=as_of_ts,
            drift_window_days=drift_window_days,
            min_surprise_pct=min_surprise_pct,
            price_history=price_slice,
        )
        if not result.get("drift_window_active"):
            # No active drift window → no PEAD signal for this ticker.
            # Drop rather than emit a 50-baseline row (see module
            # docstring on coverage).
            continue
        score = result.get("score", 50.0)
        rows.append({
            "ticker": ticker,
            "raw": float(score) - 50.0,
            "surprise_pct": result.get("surprise_pct"),
            "days_since_earnings": result.get("days_since_earnings"),
        })

    if not rows:
        logger.debug("pead_factor as_of=%s: no in-window earnings prints",
                     as_of_ts.date())
        return pd.DataFrame(
            columns=["ticker", "raw", "rank", "z_score"],
        )

    out = pd.DataFrame(rows)
    # Rank 1 = strongest signal (highest raw = best beat × decay).
    out["rank"] = out["raw"].rank(ascending=False, method="min").astype(int)
    mu = float(out["raw"].mean())
    sigma = float(out["raw"].std(ddof=0))
    if sigma > 0 and np.isfinite(sigma):
        out["z_score"] = (out["raw"] - mu) / sigma
    else:
        out["z_score"] = 0.0
    out = out.sort_values("rank").reset_index(drop=True)
    logger.debug(
        "pead_factor as_of=%s: %d in-window names, mean raw=%.2f, sigma=%.2f",
        as_of_ts.date(), len(out), mu, sigma,
    )
    return out[["ticker", "raw", "rank", "z_score"]]
