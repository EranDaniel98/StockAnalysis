"""Realized-volatility factor + low-vol filter.

Two surfaces:

* ``realized_vol_factor`` — annualized 63d realized vol as a tidy
  ranking frame, sorted ascending (1 = lowest vol). Use as a 4th
  factor in the composite (combiner will treat it like any other rank
  frame) when you want low-vol to nudge the blend.
* ``low_vol_filter`` — yes/no filter that returns the subset of a
  ticker list whose realized vol falls in the BOTTOM ``keep_pct`` of
  the universe. Use as a post-composite filter when you want to
  exclude the most-volatile names from the top-decile selection
  WITHOUT letting low-vol drive the ranking.

The two compose: rank with the composite, then filter by vol. That's
the "low-vol quality sleeve" — keep the factor signal that's been
working, drop the names with the most realized turbulence.

Methodology:
* Sigma = stdev of daily log returns over a rolling window, then
  annualized by sqrt(252). Standard definition.
* Window default 63 (3 months) matches the quarterly rebalance cadence
  of the d05_r63 strategy.
* Min observations = 42 (2/3 of window); fewer bars → exclude.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_WINDOW = 63  # trading days, matches d05_r63 rebalance cadence


def _realized_vol(close: pd.Series, *, window: int) -> float | None:
    """Annualized stdev of log returns over ``window``. None on too-thin data."""
    if close is None or close.empty or len(close) < max(20, window // 3):
        return None
    log_rets = np.log(close).diff().dropna()
    if len(log_rets) < window // 3:
        return None
    tail = log_rets.tail(window)
    if len(tail) < window // 3:
        return None
    sigma = float(tail.std(ddof=0))
    if sigma <= 0 or not np.isfinite(sigma):
        return None
    return sigma * np.sqrt(252.0)


def realized_vol_factor(
    prices: dict[str, pd.DataFrame],
    as_of: pd.Timestamp | str,
    *,
    window: int = DEFAULT_WINDOW,
) -> pd.DataFrame:
    """Per-ticker realized vol at ``as_of``, ranked ascending.

    Returns DataFrame with columns ``ticker, raw, rank, z_score``. ``raw``
    is the NEGATIVE annualized vol so higher raw = better (lower vol),
    matching the rest of the factor library's "higher raw is good"
    convention. ``rank`` = 1 for the lowest-vol name.
    """
    as_of_ts = pd.Timestamp(as_of)
    rows: list[dict] = []
    for ticker, df in prices.items():
        if df is None or df.empty or "Close" not in df.columns:
            continue
        cutoff = df[df.index <= as_of_ts]
        if cutoff.empty:
            continue
        vol = _realized_vol(cutoff["Close"], window=window)
        if vol is None:
            continue
        rows.append({"ticker": ticker, "vol": vol})
    if not rows:
        return pd.DataFrame(columns=["ticker", "raw", "rank", "z_score"])

    out = pd.DataFrame(rows)
    out["raw"] = -out["vol"]
    out["rank"] = out["raw"].rank(ascending=False, method="min").astype(int)
    mu = out["raw"].mean()
    sigma = out["raw"].std(ddof=0)
    out["z_score"] = (out["raw"] - mu) / sigma if sigma > 0 else 0.0
    return out[["ticker", "raw", "rank", "z_score"]].sort_values("rank").reset_index(drop=True)


def low_vol_filter(
    prices: dict[str, pd.DataFrame],
    tickers: list[str],
    as_of: pd.Timestamp | str,
    *,
    window: int = DEFAULT_WINDOW,
    keep_pct: float = 0.80,
) -> list[str]:
    """Return the subset of ``tickers`` whose realized vol is in the BOTTOM
    ``keep_pct`` of the FULL ``prices`` universe.

    ``keep_pct=0.80`` excludes the top-20% most-volatile names — the
    "drop the wildest ones" sleeve. Computed against the full universe
    so a sector or factor-skewed sub-list doesn't drag the cutoff.

    Tickers without computable vol (insufficient history) survive the
    filter — better to keep a name with thin data than silently drop
    it. The selector upstream is responsible for downstream filters.
    """
    if not tickers or not prices:
        return list(tickers)
    panel = realized_vol_factor(prices, as_of, window=window)
    if panel.empty:
        return list(tickers)
    # vol is positive; raw = -vol. Higher raw = lower vol = better.
    # Bottom keep_pct of vol = top keep_pct of raw = lowest ranks.
    n_keep = max(1, int(round(len(panel) * keep_pct)))
    eligible = set(panel.head(n_keep)["ticker"].tolist())
    # Tickers without a vol reading aren't in `panel`; pass them through.
    panel_tickers = set(panel["ticker"].tolist())
    return [
        t for t in tickers
        if t in eligible or t not in panel_tickers
    ]


__all__ = [
    "realized_vol_factor",
    "low_vol_filter",
    "DEFAULT_WINDOW",
]
