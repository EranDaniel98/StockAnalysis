"""Mirage factor — Sloan accruals gated and amplified by post-earnings attention.

    Mirage = -Z(accrual) * |Z_PEAD| * Decay

Thesis (co-designed Opus<->Gemini, 2026-05-28): the accrual anomaly (low
earnings quality -> lower future returns) is concentrated in the post-earnings
attention window, where headline-EPS traders anchor on the beat/miss while the
cash-flow truth in the 10-Q is slow to be repriced. The interaction is a
*product*, so a linear ``Z_accrual + Z_PEAD`` model averages it to near-zero —
that non-linearity is the whole point (see ``reports/codesign_nonlinear_2026-05-28.md``).

- ``accrual``  : PIT Sloan accruals from ``AccrualsPITLoader`` (NI-CFO)/avg-assets;
                 high = low quality. Z-scored within GICS sector, winsorized.
- ``|Z_PEAD|`` : magnitude of the 3-day abnormal return around the most recent
                 earnings date (attention shock), z-scored cross-sectionally.
                 PRE-event 60d vol is the scaler so the event's own move can't
                 inflate the denominator.
- ``Decay``    : max(0, 1 - days_since_earnings / decay_days). Zero outside the
                 window -> the name simply isn't scored by Mirage.

Returns the standard ``ticker, raw, rank, z_score`` frame, reading only data
<= ``as_of`` (the abnormal-return window must also have closed by ``as_of``).
"""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Mapping

import pandas as pd

from src.factors.accruals_pit import AccrualsPITLoader

logger = logging.getLogger(__name__)

# Sector strings that mark financials — accruals are semantically broken for
# banks/insurers (no operating-cash-flow concept in the Sloan sense).
_FINANCIAL_SECTORS = {"Financial Services", "Financials", "Financial"}


def _close_series(px: pd.DataFrame) -> pd.Series | None:
    """Normalize a per-ticker price frame to a date-indexed close series."""
    if px is None or px.empty:
        return None
    df = px
    if not isinstance(df.index, pd.DatetimeIndex):
        date_col = next((c for c in ("date", "Date") if c in df.columns), None)
        if date_col is None:
            return None
        df = df.set_index(pd.DatetimeIndex(pd.to_datetime(df[date_col])))
    col = next((c for c in ("Close", "close", "adj_close", "Adj Close") if c in df.columns), None)
    if col is None:
        return None
    return df[col].sort_index()


def _abnormal_3d(close: pd.Series, t_e: pd.Timestamp, as_of: pd.Timestamp) -> float | None:
    """3-day return around earnings ``t_e``, scaled by pre-event 60d daily vol.

    Returns None when the 3-day window hasn't closed by ``as_of`` (would be
    lookahead) or there isn't enough pre-event history to estimate vol.
    """
    idx = close.index
    pos = int(idx.searchsorted(t_e))  # first bar on/after the announce
    if pos < 21 or pos + 2 >= len(idx):
        return None
    if idx[pos + 2] > as_of:
        return None  # window not yet complete at as_of -> lookahead guard
    ret = close.iloc[pos + 2] / close.iloc[pos - 1] - 1.0
    pre = close.iloc[max(0, pos - 61):pos].pct_change().std()
    if pre is None or pd.isna(pre) or pre <= 0:
        return None
    return float(ret / (pre * (3 ** 0.5)))


def _zscore(s: pd.Series, *, winsor: float) -> pd.Series:
    mu = s.mean()
    sigma = s.std(ddof=0)
    if sigma == 0 or pd.isna(sigma):
        return pd.Series(0.0, index=s.index)
    return ((s - mu) / sigma).clip(-winsor, winsor)


def _sector_zscore(df: pd.DataFrame, col: str, sector_col: str, *, winsor: float) -> pd.Series:
    """Z-score ``col`` within each sector; singleton/degenerate sectors -> 0."""
    def _z(g: pd.Series) -> pd.Series:
        sigma = g.std(ddof=0)
        if sigma == 0 or pd.isna(sigma) or len(g) < 3:
            return pd.Series(0.0, index=g.index)
        return ((g - g.mean()) / sigma).clip(-winsor, winsor)

    return df.groupby(sector_col)[col].transform(_z)


def mirage_components(
    accruals: AccrualsPITLoader,
    earnings_histories: Mapping[str, pd.DataFrame | None],
    prices: Mapping[str, pd.DataFrame],
    as_of: pd.Timestamp,
    *,
    sector_of: Mapping[str, str] | None = None,
    decay_days: int = 45,
    min_price: float = 5.0,
    winsor: float = 3.0,
) -> pd.DataFrame:
    """Per-name Mirage ingredients at ``as_of``.

    Returns a frame with ``ticker, z_accrual, z_pead_abs, decay, accrual, abret,
    sector`` for every eligible name (fresh earnings within ``decay_days`` + a
    usable PIT accrual + price >= ``min_price``, financials excluded). Exposed
    so the validation harness can form the product (Mirage) AND the additive
    baseline from the SAME cross-section — the gate-#2 interaction test.
    """
    as_of_ts = pd.Timestamp(as_of)
    as_of_dt = as_of_ts.to_pydatetime()
    if as_of_dt.tzinfo is None:
        as_of_dt = as_of_dt.replace(tzinfo=_dt.timezone.utc)
    sector_of = sector_of or {}

    rows: list[dict] = []
    for t in accruals.tickers:
        rec = accruals.lookup(t, as_of_dt)
        if rec is None:
            continue
        sector = sector_of.get(t, "Unknown")
        if sector in _FINANCIAL_SECTORS:
            continue
        eh = earnings_histories.get(t)
        if eh is None or len(eh) == 0:
            continue
        dates = pd.DatetimeIndex(eh.index)
        past = dates[dates <= as_of_ts]
        if len(past) == 0:
            continue
        t_e = past.max()
        days_since = (as_of_ts - t_e).days
        if days_since < 0 or days_since > decay_days:
            continue
        close = _close_series(prices.get(t))
        if close is None or len(close) == 0 or float(close.iloc[-1]) < min_price:
            continue
        abret = _abnormal_3d(close, t_e, as_of_ts)
        if abret is None:
            continue
        rows.append({
            "ticker": t,
            "accrual": rec.accrual,
            "abret": abret,
            "decay": max(0.0, 1.0 - days_since / decay_days),
            "sector": sector,
        })

    if not rows:
        return pd.DataFrame(columns=["ticker", "z_accrual", "z_pead_abs", "decay", "accrual", "abret", "sector"])

    df = pd.DataFrame(rows)
    if sector_of and df["sector"].nunique() > 1:
        df["z_accrual"] = _sector_zscore(df, "accrual", "sector", winsor=winsor)
    else:
        df["z_accrual"] = _zscore(df["accrual"], winsor=winsor)
    df["z_pead_abs"] = _zscore(df["abret"], winsor=winsor).abs()
    return df


def mirage_factor(
    accruals: AccrualsPITLoader,
    earnings_histories: Mapping[str, pd.DataFrame | None],
    prices: Mapping[str, pd.DataFrame],
    as_of: pd.Timestamp,
    *,
    sector_of: Mapping[str, str] | None = None,
    decay_days: int = 45,
    min_price: float = 5.0,
    winsor: float = 3.0,
) -> pd.DataFrame:
    """Cross-sectional Mirage ranking at ``as_of`` — ``Mirage = -Z(accrual) *
    |Z_PEAD| * Decay``. Standard ``ticker, raw, rank, z_score`` frame."""
    comp = mirage_components(
        accruals, earnings_histories, prices, as_of,
        sector_of=sector_of, decay_days=decay_days, min_price=min_price, winsor=winsor,
    )
    cols = ["ticker", "raw", "rank", "z_score"]
    if comp.empty:
        return pd.DataFrame(columns=cols)

    comp["raw"] = (-comp["z_accrual"]) * comp["z_pead_abs"] * comp["decay"]
    comp["rank"] = comp["raw"].rank(ascending=False, method="min").astype(int)
    sigma = comp["raw"].std(ddof=0)
    comp["z_score"] = 0.0 if (sigma == 0 or pd.isna(sigma)) else (comp["raw"] - comp["raw"].mean()) / sigma

    out = comp[cols].sort_values("rank").reset_index(drop=True)
    logger.debug("mirage_factor as_of=%s: %d names scored", pd.Timestamp(as_of).date(), len(out))
    return out
