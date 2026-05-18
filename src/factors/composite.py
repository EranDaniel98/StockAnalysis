"""Multi-factor composite — equal-weight rank-combine N factor frames.

Why rank-combine rather than z-score-combine
--------------------------------------------
Z-scores blow up under fat-tailed distributions (one extreme momentum
name with raw return +500% drags the z-distribution toward it and
suppresses the signal in the rest of the universe). Ranks are bounded
in [1, N] regardless of distribution and are immune to outliers.
Asness 1994 + the original AQR style-factor papers use rank-blend.

API
---
``combine([df1, df2, df3])`` takes a list of factor frames (each with
columns ``ticker, raw, rank, z_score``) and returns one frame with
``ticker, mean_rank, raw, rank, z_score``. ``raw`` here is the mean
normalized rank so higher = better; the new ``rank`` field is the
final ranking.

Only tickers present in EVERY input frame are kept — partial coverage
would silently give some names an advantage. If you want a permissive
mode (mean over present factors), pass ``min_overlap < len(frames)``.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

_OUT_COLUMNS = ["ticker", "mean_normalized_rank", "raw", "rank", "z_score"]


def _empty_result() -> pd.DataFrame:
    return pd.DataFrame(columns=_OUT_COLUMNS)


def combine(
    frames: list[pd.DataFrame],
    *,
    min_overlap: int | None = None,
    weights: list[float] | None = None,
) -> pd.DataFrame:
    """Rank-combine N factor frames.

    Parameters
    ----------
    frames : list of factor frames with ['ticker', 'rank'] columns.
    min_overlap : minimum number of frames a ticker must appear in.
        Default = len(frames) (strict: ticker must be in every frame).
    weights : optional per-frame weight vector. Same length as
        ``frames``. When provided, the composite is a weighted average
        of the per-frame normalized ranks instead of a simple mean.
        Weights are normalized to sum to 1; zero or negative weights
        skip that frame entirely. Used by the regime-conditional
        weighting variant (see ``src/factors/regime_weights.py``).

    Returns
    -------
    DataFrame with columns ['ticker', 'mean_normalized_rank', 'raw',
    'rank', 'z_score'] sorted by rank ascending (1 = best composite).
    Note: when weights are passed, ``mean_normalized_rank`` is the
    *weighted* mean — the column name is preserved for downstream
    compatibility.
    """
    if not frames:
        return _empty_result()

    if weights is not None:
        if len(weights) != len(frames):
            raise ValueError(
                f"weights length {len(weights)} != frames length {len(frames)}"
            )

    # When weights zero out some frames, the effective frame count for
    # min_overlap purposes drops. ``len(frames)`` is the wrong default
    # in that case — it would demand every ticker be in frames we just
    # told the composite to ignore.
    active_count = (
        sum(1 for w in weights if w > 0) if weights is not None else len(frames)
    )
    threshold = min_overlap if min_overlap is not None else active_count

    # Normalize ranks within each frame to [0, 1]. This handles the
    # case where different frames have different N (e.g., momentum has
    # 480, quality has 450 — without normalization the smaller-N frame
    # dominates).
    normalized: list[pd.DataFrame] = []
    frame_weights: list[float] = []
    for i, f in enumerate(frames):
        w = float(weights[i]) if weights is not None else 1.0
        if w <= 0:
            continue
        if f.empty or "ticker" not in f.columns or "rank" not in f.columns:
            continue
        n = len(f)
        if n == 0:
            continue
        sub = f[["ticker", "rank"]].copy()
        sub[f"nr_{i}"] = (sub["rank"] - 1) / max(1, n - 1)  # 0 = best, 1 = worst
        normalized.append(sub[["ticker", f"nr_{i}"]])
        frame_weights.append(w)

    if not normalized:
        return _empty_result()

    # Outer merge so we can count overlap per ticker.
    merged = normalized[0]
    for sub in normalized[1:]:
        merged = merged.merge(sub, on="ticker", how="outer")

    nr_cols = [c for c in merged.columns if c.startswith("nr_")]
    present = merged[nr_cols].notna().sum(axis=1)
    merged = merged[present >= threshold].copy()
    if merged.empty:
        return _empty_result()

    if weights is None:
        merged["mean_normalized_rank"] = merged[nr_cols].mean(axis=1, skipna=True)
    else:
        # Weighted mean per row, ignoring NaN (a ticker missing from a
        # frame contributes 0 weight for that frame). Re-normalize per
        # row so weights sum to 1 across the frames the ticker is in.
        weight_arr = pd.Series(frame_weights, index=nr_cols)
        weight_sum = weight_arr.sum()
        if weight_sum <= 0:
            return _empty_result()
        # Multiply each column by its weight, sum, divide by per-row
        # weight (the sum over columns where the value is not NaN).
        weighted = merged[nr_cols].mul(weight_arr, axis=1)
        row_weight = (
            merged[nr_cols].notna()
            .mul(weight_arr, axis=1).sum(axis=1)
        )
        merged["mean_normalized_rank"] = (
            weighted.sum(axis=1, min_count=1) / row_weight.replace(0, pd.NA)
        )
    # raw = -mean_normalized_rank so HIGHER raw = better (matches the
    # per-factor convention; downstream code that sorts by raw descending
    # still works).
    merged["raw"] = -merged["mean_normalized_rank"]
    merged["rank"] = merged["raw"].rank(ascending=False, method="min").astype(int)

    mu = merged["raw"].mean()
    sigma = merged["raw"].std(ddof=0)
    if sigma == 0 or pd.isna(sigma):
        merged["z_score"] = 0.0
    else:
        merged["z_score"] = (merged["raw"] - mu) / sigma

    out = merged[_OUT_COLUMNS].sort_values("rank").reset_index(drop=True)
    logger.debug(
        "composite.combine: %d frames -> %d tickers (min_overlap=%d)",
        len(frames), len(out), threshold,
    )
    return out
