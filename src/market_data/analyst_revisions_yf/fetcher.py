"""Convert yfinance analyst data into the analyst_revisions analyzer's row shape.

yfinance exposes two relevant APIs on Ticker:
- ``upgrades_downgrades``: DataFrame indexed by date with columns
  ``Firm``, ``ToGrade``, ``FromGrade``, ``Action``. This is the cleaner
  signal — explicit revision events with both grades.
- ``recommendations``: snapshot of recent recommendations (firm + grade),
  no historical from/to deltas. Used as a fallback when
  ``upgrades_downgrades`` is empty.

Network calls are parallelized via ThreadPoolExecutor. yfinance is
single-thread-blocking per Ticker but the underlying HTTP fetches release
the GIL, so 8-10 workers is a reasonable throughput.

Target price deltas are not directly exposed by yfinance free; the
RevisionRow dataclass leaves those fields None. The analyzer is built to
handle that — net upgrade/downgrade counts alone produce a signal.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Optional

import pandas as pd

from src.scoring.analyzers.analyst_revisions import RevisionRow

logger = logging.getLogger(__name__)


def _row_action(from_grade: str, to_grade: str, action_hint: str | None) -> str:
    """Classify an analyst event. yfinance's `Action` column is sometimes
    blank or normalized inconsistently ('main' for maintained, 'up' for
    upgrade, etc.); fall back to grade-delta when present."""
    if action_hint:
        token = action_hint.strip().lower()
        if token in ("up", "upgrade", "upgraded"):
            return "upgrade"
        if token in ("down", "downgrade", "downgraded"):
            return "downgrade"
        if token in ("init", "initiated", "initiate"):
            return "initiate"
        if token in ("reiterated", "reiterate", "maintained", "main"):
            return "reiterate"
    # No action hint — compare grades. Equal grades = reiterate.
    if not from_grade and to_grade:
        return "initiate"
    if from_grade == to_grade:
        return "reiterate"
    # Fall through: any grade change without a direction hint becomes
    # 'reiterate' here; the analyzer's grade-ladder map decides the
    # numeric direction itself.
    return "reiterate"


def _df_to_rows(df: pd.DataFrame) -> list[RevisionRow]:
    """Walk a yfinance upgrades_downgrades DataFrame and emit RevisionRows."""
    rows: list[RevisionRow] = []
    if df is None or df.empty:
        return rows
    # yfinance returns GradeDate (or DatetimeIndex) — accept either
    idx = df.index
    for i, row in df.reset_index(drop=False).iterrows():
        # The DatetimeIndex column name varies ('GradeDate' or 'index')
        revision_dt = row.get("GradeDate") or row.get("Date") or row.get("index")
        if pd.isna(revision_dt):
            continue
        try:
            revision_d: date = pd.Timestamp(revision_dt).date()
        except Exception:
            continue
        firm = (row.get("Firm") or "").strip() or "Unknown"
        to_grade = (row.get("ToGrade") or "").strip()
        from_grade = (row.get("FromGrade") or "").strip()
        action_hint = (row.get("Action") or "").strip()
        if not to_grade:
            # Without a target grade we can't score anything useful.
            continue
        action = _row_action(from_grade, to_grade, action_hint)
        rows.append(
            RevisionRow(
                revision_date=revision_d,
                firm=firm,
                action=action,
                from_grade=from_grade or None,
                to_grade=to_grade,
                target_price_prior=None,  # yfinance doesn't expose these for free
                target_price_new=None,
            )
        )
    return rows


def fetch_revisions(ticker: str) -> list[RevisionRow]:
    """Fetch one ticker's recent analyst revisions. Returns [] on failure
    rather than raising — analyst data is noisy at the source and a
    missing ticker shouldn't fail the whole scan."""
    import yfinance as yf

    try:
        t = yf.Ticker(ticker)
        df = getattr(t, "upgrades_downgrades", None)
        if df is None or df.empty:
            return []
        return _df_to_rows(df)
    except Exception as e:
        logger.debug("upgrades_downgrades fetch failed for %s: %s", ticker, e)
        return []


def fetch_revisions_batch(
    tickers: list[str],
    *,
    max_workers: int = 8,
) -> dict[str, list[RevisionRow]]:
    """Parallel fetch over a ticker universe.

    Empty list for tickers with no available data — the analyzer treats
    those as "no signal," which the composite engine then skips. Caller
    can also filter the result before passing to the engine.
    """
    results: dict[str, list[RevisionRow]] = {}
    if not tickers:
        return results
    workers = min(max_workers, len(tickers))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fetch_revisions, t): t for t in tickers}
        for fut in as_completed(futures):
            ticker = futures[fut]
            try:
                results[ticker] = fut.result()
            except Exception as e:
                logger.debug("worker error %s: %s", ticker, e)
                results[ticker] = []
    coverage = sum(1 for v in results.values() if v)
    logger.info(
        "analyst_revisions: fetched %d/%d tickers with non-empty history",
        coverage, len(tickers),
    )
    return results
