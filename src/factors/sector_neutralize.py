"""Sector-neutralize a factor frame by replacing universe-wide rank
with within-sector rank.

Motivation
----------

The 2026-05-18 factor ablation (reports/factor_ablation_2022_2024.md)
found that quality, standalone, lost -23.85% alpha on 2022-2024 — but
removing it from the composite made things worse. The diagnosis:
quality picks DEFENSIVE SECTORS (staples, utilities) cross-sectionally,
and during a value/cyclical rotation those sectors get hammered. The
fix is to rank quality WITHIN sector — pick the best staples vs the
worse staples, the best cyclicals vs the worse cyclicals — instead of
ranking all 480 names against each other (where staples dominate the
top of the quality list by construction).

Implementation
--------------

Given a factor frame ``(ticker, raw, rank, z_score)`` and a
``sectors`` dict mapping ``ticker -> sector_string``:

1. Group by sector.
2. Within each sector, compute percentile rank from ``raw`` (lower
   percentile = better — using ``ascending=False`` so high raw wins).
3. The new universe-wide ``rank`` is built from the within-sector
   percentile so all "best in sector" names tie at rank 1.
4. New z-score is the negative of the within-sector percentile,
   demeaned: roughly z=+1 for "top sigma in its sector".

The output is interchangeable with the input frame and slots directly
into ``composite.combine`` — which then blends sector-neutralized
quality with cross-sectional momentum and value.

Why percentile and not within-sector z-score
--------------------------------------------

Z-scoring inside a sector gives sectors with high within-sector
variance more leverage in the composite (one outlier dominates).
Percentile rank is bounded [0, 1] regardless of distribution — same
philosophy that drove ``composite.combine`` to use ranks over
z-scores for cross-frame blending.
"""

from __future__ import annotations

import logging
from typing import Mapping

import pandas as pd

logger = logging.getLogger(__name__)

_REQUIRED_COLS = {"ticker", "raw", "rank", "z_score"}


def sector_neutralize(
    frame: pd.DataFrame,
    sectors: Mapping[str, str],
    *,
    unknown_bucket: str = "Unknown",
    min_sector_size: int = 3,
) -> pd.DataFrame:
    """Sector-neutralize a factor frame.

    Parameters
    ----------
    frame : factor frame with columns ``ticker, raw, rank, z_score``.
        Higher ``raw`` is better; this is the convention every factor
        in ``src/factors/`` uses.
    sectors : mapping ``ticker -> sector_string``. Names not in the
        mapping fall into ``unknown_bucket``.
    unknown_bucket : bucket name for tickers without sector data.
        Default ``"Unknown"`` matches the sector cap selector.
    min_sector_size : sectors with fewer names than this don't get
        ranked within (they fall back to their original raw-based rank
        within the unknown bucket). Avoids meaningless 1-of-1 percentile
        ranks. Default 3.

    Returns
    -------
    DataFrame with the same shape and columns as ``frame``. ``rank``
    and ``z_score`` are replaced; ``raw`` is preserved so downstream
    consumers can still see the underlying score.
    """
    if frame is None or frame.empty:
        return frame
    missing = _REQUIRED_COLS - set(frame.columns)
    if missing:
        raise ValueError(
            f"sector_neutralize: frame missing columns {sorted(missing)}"
        )

    out = frame.copy()
    out["_sector"] = out["ticker"].map(
        lambda t: sectors.get(t) or unknown_bucket
    )

    # Sectors with too few members go into the unknown bucket — a
    # single-name sector would otherwise get percentile 1.0 (the BEST)
    # by default, which gives that name an undeserved boost.
    counts = out["_sector"].value_counts()
    small_sectors = set(counts[counts < min_sector_size].index)
    if small_sectors:
        logger.debug(
            "sector_neutralize: collapsing %d small sectors (<%d names) "
            "into %s",
            len(small_sectors), min_sector_size, unknown_bucket,
        )
        out.loc[out["_sector"].isin(small_sectors), "_sector"] = unknown_bucket

    # Within-sector percentile rank. ``ascending=False`` so high raw
    # gets low percentile. ``method="min"`` so ties get the same rank.
    out["_sector_pct"] = out.groupby("_sector")["raw"].rank(
        ascending=False, method="min", pct=True,
    )

    # Universe-wide rank by within-sector percentile (lower pct = better).
    out["rank"] = (
        out["_sector_pct"]
        .rank(ascending=True, method="min")
        .astype(int)
    )

    # New z-score: how far above (or below) the median of its sector is
    # this name? Computed as the negative deviation of the within-sector
    # percentile from 0.5, scaled by the dataset-wide stdev of that
    # deviation. Positive = above sector-median quality.
    centered = out["_sector_pct"] - 0.5
    sigma = float(centered.std(ddof=0))
    if sigma > 0:
        out["z_score"] = -centered / sigma  # negate so high = good
    else:
        out["z_score"] = 0.0

    return (
        out[["ticker", "raw", "rank", "z_score"]]
        .sort_values("rank")
        .reset_index(drop=True)
    )


__all__ = ["sector_neutralize"]
