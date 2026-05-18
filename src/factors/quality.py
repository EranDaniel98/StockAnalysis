"""Quality factor — composite of profitability + leverage + cash generation.

Construction
------------
For each ticker, take the most recent EDGAR filing valid on or before
``as_of`` (point-in-time). Compute five sub-components, cross-sectionally
z-score each within the universe at ``as_of``, equal-weight average:

  1. ROE                    (higher better)
  2. operating_margin       (higher better)
  3. profit_margin          (higher better)
  4. FCF / revenue          (higher better — cash-conversion quality)
  5. -debt_to_equity        (LOWER raw is better; sign-flipped for z)

Rationale
---------
Quality factor (Asness/Frazzini/Pedersen 2014 "Quality Minus Junk")
captures the empirical observation that high-quality firms produce
higher risk-adjusted returns over long horizons. Standard sub-
components: profitability, growth, safety, payout. We use a
profitability-and-safety tilt because EDGAR coverage of the
specific growth-and-payout fields is uneven.

Rows with fewer than 3 of 5 sub-components present are dropped —
better to score a smaller universe well than the whole universe
with garbage.
"""

from __future__ import annotations

import logging
from typing import Iterable

import pandas as pd

from src.scoring.fundamentals_pit_loader import FundamentalsPITLoader

logger = logging.getLogger(__name__)


_COMPONENTS_DIRECT = ("roe", "operating_margin", "profit_margin", "fcf_margin")
_COMPONENT_INVERTED = "debt_to_equity"
# Lowered from 3 → 2 on 2026-05-18 after expanding the concept-map for
# bank/utility filers. Some filers (APA, AES) report only 2 of the 5
# components under standard us-gaap tags; requiring 3 dropped them from
# the quality ranking even though they have a credible profitability
# signal (e.g. ROE + debt/equity). Two of five is enough to differentiate
# names cross-sectionally when each is z-scored independently.
_MIN_COMPONENTS_REQUIRED = 2


def quality_factor(
    loader: FundamentalsPITLoader,
    tickers: Iterable[str],
    as_of: pd.Timestamp,
) -> pd.DataFrame:
    """Return the cross-sectional quality ranking at ``as_of``.

    The loader must be pre-populated with snapshots covering ``tickers``
    (call ``FundamentalsPITLoader.from_repository`` once before the
    backtest loop).
    """
    as_of_ts = pd.Timestamp(as_of)
    as_of_dt = as_of_ts.to_pydatetime()
    # PIT loader expects tz-aware datetimes; coerce here.
    if as_of_dt.tzinfo is None:
        import datetime as _dt
        as_of_dt = as_of_dt.replace(tzinfo=_dt.timezone.utc)

    rows: list[dict] = []
    for t in tickers:
        snap = loader.lookup(t, as_of_dt)
        if snap is None:
            continue
        fcf_margin = None
        if (
            snap.free_cash_flow is not None
            and snap.revenue is not None
            and snap.revenue > 0
        ):
            fcf_margin = snap.free_cash_flow / snap.revenue
        rows.append({
            "ticker": t,
            "roe": snap.roe,
            "operating_margin": snap.operating_margin,
            "profit_margin": snap.profit_margin,
            "fcf_margin": fcf_margin,
            "debt_to_equity": snap.debt_to_equity,
        })

    if not rows:
        return pd.DataFrame(columns=["ticker", "raw", "rank", "z_score"])

    df = pd.DataFrame(rows)

    # Cross-sectional z-score each component.
    z_cols: list[str] = []
    for col in _COMPONENTS_DIRECT:
        mu = df[col].mean(skipna=True)
        sigma = df[col].std(ddof=0, skipna=True)
        if pd.isna(sigma) or sigma == 0:
            df[f"{col}_z"] = 0.0
        else:
            df[f"{col}_z"] = (df[col] - mu) / sigma
        z_cols.append(f"{col}_z")

    # Inverted: low debt-to-equity is high quality.
    mu_d = df[_COMPONENT_INVERTED].mean(skipna=True)
    sigma_d = df[_COMPONENT_INVERTED].std(ddof=0, skipna=True)
    if pd.isna(sigma_d) or sigma_d == 0:
        df[f"{_COMPONENT_INVERTED}_z"] = 0.0
    else:
        df[f"{_COMPONENT_INVERTED}_z"] = -((df[_COMPONENT_INVERTED] - mu_d) / sigma_d)
    z_cols.append(f"{_COMPONENT_INVERTED}_z")

    # Require at least 3 of 5 components present (non-NaN raw input).
    raw_cols = list(_COMPONENTS_DIRECT) + [_COMPONENT_INVERTED]
    present = df[raw_cols].notna().sum(axis=1)
    df = df[present >= _MIN_COMPONENTS_REQUIRED].copy()
    if df.empty:
        return pd.DataFrame(columns=["ticker", "raw", "rank", "z_score"])

    # Composite raw = equal-weight mean of present z-scores.
    df["raw"] = df[z_cols].mean(axis=1, skipna=True)
    df["rank"] = df["raw"].rank(ascending=False, method="min").astype(int)
    mu = df["raw"].mean()
    sigma = df["raw"].std(ddof=0)
    if sigma == 0 or pd.isna(sigma):
        df["z_score"] = 0.0
    else:
        df["z_score"] = (df["raw"] - mu) / sigma

    out = df[["ticker", "raw", "rank", "z_score"]].sort_values("rank")
    out = out.reset_index(drop=True)
    logger.debug(
        "quality_factor as_of=%s: %d names ranked (from %d input tickers)",
        as_of_ts.date(), len(out), len(rows),
    )
    return out
