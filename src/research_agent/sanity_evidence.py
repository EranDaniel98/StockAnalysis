"""Evidence-gathering for pre-trade sanity checks.

Pulls the bits ``SanityCheckInputs`` needs out of the local database so
the LLM has something to chew on. MVP scope (2026-05-17):

* recent_filings_summary — last 30 days of EDGAR 8-K notifications from
  ``filing_notifications``. The monitor writes these in the background;
  if it hasn't been running for the ticker we hand back the standard
  "(none in the last 30 days)" placeholder, same as a real lookup that
  returned empty.
* recent_news_summary — left empty until a vetted news source is wired.
  Don't pretend to have data we don't.
* price_anomaly_summary — left None for the same reason.

Future work: news from a real provider, price-anomaly detection off the
parquet store. Today's check still works — the LLM has the composite
score + action + filings, which is enough to flag obvious M&A / takeover
cases. False OKs are the acceptable failure mode; the composite already
passed the validity gates.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import FilingNotification
from src.research_agent.sanity_check import SanityCheckInputs


async def build_sanity_inputs(
    *,
    db: AsyncSession,
    ticker: str,
    composite_score: float,
    action: str,
    filings_window_days: int = 30,
) -> SanityCheckInputs:
    """Assemble ``SanityCheckInputs`` for one ticker from local DB rows.

    Caller passes ``composite_score`` and ``action`` from the BuySignal
    being checked — those drive the LLM's framing (it's anchored on
    "the systematic system says BUY at X, sanity-check it").
    """
    filings_summary = await _summarize_recent_filings(
        db, ticker=ticker, window_days=filings_window_days
    )
    return SanityCheckInputs(
        ticker=ticker,
        recent_filings_summary=filings_summary,
        recent_news_summary="",
        price_anomaly_summary=None,
        composite_score=composite_score,
        action=action,
    )


async def _summarize_recent_filings(
    db: AsyncSession, *, ticker: str, window_days: int
) -> str:
    """Build the prompt-ready filings summary for ``ticker``.

    Returns an empty string when the monitor has no rows in the window
    — the sanity_check renderer substitutes the
    "(none in the last 30 days)" placeholder so an empty result reads
    the same to the LLM as a real lookup that found nothing.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    stmt = (
        select(FilingNotification)
        .where(FilingNotification.ticker == ticker)
        .where(FilingNotification.detected_at >= cutoff)
        .order_by(desc(FilingNotification.detected_at))
        .limit(10)
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return ""

    lines: list[str] = []
    for row in rows:
        date_str = row.filing_date.isoformat() if row.filing_date else "?"
        headline = (row.summary or "").strip().splitlines()[0:1]
        headline_text = headline[0] if headline else "(no summary cached)"
        lines.append(f"- {date_str} {row.form}: {headline_text}")
    return "\n".join(lines)


__all__ = ["build_sanity_inputs"]
