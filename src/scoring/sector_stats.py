"""Cross-sectional sector statistics for relative-to-sector scoring.

Why this exists: a P/E of 25 means very different things in software (cheap)
vs utilities (expensive). The legacy ``fundamental.analyze`` uses absolute
thresholds (``if pe < 15: score 80``), which systematically over-scores
low-multiple sectors and under-scores high-multiple sectors. Sector-relative
scoring computes a percentile within the ticker's own sector cohort.

This module is pure: in goes ``{ticker: fundamentals_dict}``, out comes
per-sector Q1/median/Q3 boundaries for each numeric metric. The analyzer
consults the table when scoring; small cohorts fall back to absolute
thresholds so a scan over 3 utility tickers doesn't get noisy sector stats.

Lookahead note: like the rest of yfinance-backed fundamentals, the stats
are computed from current-snapshot values. Backtests pay the same
fundamentals-lookahead tax that's already flagged loudly in the engine.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional

import numpy as np

# Metrics we have a defensible per-sector distribution for. Margins
# differ between Software and Utilities almost as much as P/E does, so
# they're also worth scoring relatively, but for the first cut we focus
# on the four valuation metrics that drive the worst absolute-threshold
# distortions.
SECTOR_RELATIVE_METRICS: tuple[str, ...] = (
    "pe_trailing",
    "pe_forward",
    "peg_ratio",
    "pb_ratio",
    "ev_to_ebitda",
)


# Skip sectors with fewer than this many tickers — the percentile is
# meaningless when 'Q1' is computed from 2 data points.
DEFAULT_MIN_COHORT: int = 5


def _coerce(value: object) -> Optional[float]:
    """Accept None, NaN, negative, or zero as "absent" — these would
    poison a quantile (a negative P/E doesn't belong in the cohort)."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v) or v <= 0:
        return None
    return v


def compute_sector_stats(
    fundamentals_by_ticker: Mapping[str, Optional[Mapping[str, object]]],
    *,
    min_cohort: int = DEFAULT_MIN_COHORT,
    metrics: Iterable[str] = SECTOR_RELATIVE_METRICS,
) -> dict[str, dict[str, dict[str, float]]]:
    """Build per-sector quantile boundaries for each metric.

    Args:
        fundamentals_by_ticker: mapping of ticker → its fundamentals
            dict (or None for tickers whose fundamentals fetch failed).
            Tickers without a sector or with no numeric metric values
            contribute nothing.
        min_cohort: minimum number of tickers in a sector before we
            publish stats for it. Sectors smaller than this are dropped
            from the output — the analyzer's fallback will use absolute
            thresholds.
        metrics: which fundamental keys to summarize. Defaults to the
            four valuation metrics this module was designed for.

    Returns:
        ``{sector: {metric: {q1, median, q3, count}}}``. Missing
        sectors or missing metrics simply absent — callers must
        gracefully fall back when a lookup misses.
    """
    metrics = tuple(metrics)
    # Bucket values by sector → metric → [values]
    buckets: dict[str, dict[str, list[float]]] = {}
    for fund in fundamentals_by_ticker.values():
        if not fund:
            continue
        sector = fund.get("sector")
        if not sector or sector == "Unknown":
            continue
        sector_bucket = buckets.setdefault(sector, {m: [] for m in metrics})
        for metric in metrics:
            v = _coerce(fund.get(metric))
            if v is not None:
                sector_bucket[metric].append(v)

    out: dict[str, dict[str, dict[str, float]]] = {}
    for sector, metric_map in buckets.items():
        sector_out: dict[str, dict[str, float]] = {}
        for metric, values in metric_map.items():
            if len(values) < min_cohort:
                continue
            arr = np.asarray(values, dtype=float)
            q1, median, q3 = np.quantile(arr, [0.25, 0.5, 0.75])
            sector_out[metric] = {
                "q1": float(q1),
                "median": float(median),
                "q3": float(q3),
                "count": float(len(values)),
            }
        if sector_out:
            out[sector] = sector_out
    return out


def percentile_bucket(value: float, stats: Mapping[str, float]) -> str:
    """Map a value against (q1, median, q3) to a coarse bucket label.

    "low" / "below_median" / "above_median" / "high" — the analyzer
    then maps these to score bands. Coarse buckets keep the rule
    interpretable; smooth curves are item #6 on the deferred list.

    The lower-is-better orientation is correct for the four metrics
    in SECTOR_RELATIVE_METRICS (lower P/E = cheaper = bullish). If we
    ever extend to higher-is-better metrics like margins, pass an
    ``ascending`` flag through.
    """
    if value <= stats["q1"]:
        return "low"
    if value <= stats["median"]:
        return "below_median"
    if value <= stats["q3"]:
        return "above_median"
    return "high"
