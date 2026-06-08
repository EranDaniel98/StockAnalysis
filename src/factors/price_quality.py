"""Drop tickers whose price series carries a corporate-action stitching artifact.

Polygon serves one ticker's WHOLE history across ticker reuse / renames /
splits / delistings. When a fetch window spans the event, two unrelated price
regimes (or a $0 + a stray tick) get stitched into one series, producing a
physically-impossible single-day move or a multi-month internal gap. The
momentum factor then reads that as astronomical 12-1 momentum and ranks the
artifact #1 — so the book buys it. (Root cause: project_price_artifact_hunt;
e.g. META = Meta Materials penny stock until Meta Platforms took the ticker
from FB 2022-06, +1395% stitched jump.)

Guard, applied PER as_of (so a ticker re-enters once the event rolls out of the
lookback window — drop-on-hit, not a permanent ban):
  - any close-to-close move > MAX_DAILY_MOVE within the lookback, or
  - a > MAX_GAP_DAYS internal calendar gap in the windowed series.
"""

from __future__ import annotations

import pandas as pd

# Defaults (used if config/settings.yaml::price_artifact_guard is absent). A
# real S&P large-cap close-to-close move essentially never exceeds MAX_DAILY_MOVE
# (buyout pops/crashes top out ~40-50%); markets never close ~MAX_GAP_DAYS days.
MAX_DAILY_MOVE = 0.80
MAX_GAP_DAYS = 45
LOOKBACK_ROWS = 280  # ~13 months, the 12-1 momentum window

_CFG: tuple[float, int, int] | None = None


def _thresholds() -> tuple[float, int, int]:
    """(max_daily_move, max_gap_days, lookback_rows) from config; cached.
    Falls back to the module defaults if config is unreadable."""
    global _CFG
    if _CFG is None:
        try:
            from src.config_loader import Config
            g = Config().get("price_artifact_guard", default=None) or {}
        except Exception:  # noqa: BLE001
            g = {}
        _CFG = (
            float(g.get("max_daily_move", MAX_DAILY_MOVE)),
            int(g.get("max_gap_days", MAX_GAP_DAYS)),
            int(g.get("lookback_rows", LOOKBACK_ROWS)),
        )
    return _CFG


def has_price_artifact(
    df: pd.DataFrame | None, as_of: pd.Timestamp, lookback_rows: int = LOOKBACK_ROWS,
) -> bool:
    """True if the series (<= as_of, last ``lookback_rows`` rows) is stitched."""
    if df is None or df.empty or "Close" not in df.columns:
        return False
    elig = df[df.index <= as_of]
    if len(elig) < 5:
        return False
    window = elig.iloc[-lookback_rows:]
    close = window["Close"]
    close = close[close > 0]
    if len(close) < 5:
        return False
    if close.pct_change().abs().max() > MAX_DAILY_MOVE:
        return True
    gaps = window.index.to_series().diff().dt.days
    return bool(gaps.max() is not None and gaps.max() > MAX_GAP_DAYS)


def drop_price_artifacts(
    prices: dict[str, pd.DataFrame], as_of: pd.Timestamp,
    *, lookback_rows: int = LOOKBACK_ROWS,
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Return (clean_prices, dropped_tickers) for a single as_of."""
    dropped = sorted(
        t for t, df in prices.items()
        if has_price_artifact(df, as_of, lookback_rows)
    )
    if not dropped:
        return prices, []
    drop_set = set(dropped)
    return {t: df for t, df in prices.items() if t not in drop_set}, dropped
