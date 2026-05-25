"""Sync-friendly batch gate for the LLM sanity check.

The web UI calls the async ``check_buy_signal_auto`` directly inside an
async route. Batch / cron pipelines (``scripts/paper_trade_factor_picks``,
``scripts/daily_factor_picks``) are sync — they need a one-call helper
that gates a list of (ticker, score, action) entries, drops the
REJECTed ones, and surfaces CAUTIONs without halting execution.

This is the bridge. It owns:

* assembling :class:`SanityCheckInputs` from local DB rows
* running :func:`check_buy_signal_auto` concurrently across the batch
* applying the asymmetric trust rule (REJECT removes; CAUTION warns)
* returning a structured per-ticker verdict map plus the post-filter list

Asymmetric trust is the same invariant enforced everywhere else: the
LLM can only DOWNGRADE BUYs, never UPGRADE. Callers MUST treat the
``filtered`` list as authoritative — passing the raw input list past
the gate defeats the whole point.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Iterable, Optional

from src.api.schemas.sanity import SanityCheck
from src.research_agent.sanity_check import (
    SanityCheckInputs,
    check_buy_signal_auto,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SanityGateOutcome:
    """Outcome of gating one ticker."""

    ticker: str
    verdict: str  # "OK" | "CAUTION" | "REJECT" | "SKIP"
    check: Optional[SanityCheck]
    reason: str


@dataclass(frozen=True)
class SanityGateResult:
    """Aggregate outcome of gating a batch."""

    kept: list[str]
    rejected: list[str]
    cautioned: list[str]
    outcomes: dict[str, SanityGateOutcome]


async def _check_one(
    *,
    ticker: str,
    composite_score: float,
    action: str,
    filings_summary: str = "",
    news_summary: str = "",
    price_anomaly: Optional[str] = None,
    mode: str = "auto",
) -> SanityGateOutcome:
    """Run the gate for a single ticker; never raises."""
    inputs = SanityCheckInputs(
        ticker=ticker,
        recent_filings_summary=filings_summary,
        recent_news_summary=news_summary,
        price_anomaly_summary=price_anomaly,
        composite_score=composite_score,
        action=action,
    )
    try:
        check = await check_buy_signal_auto(inputs, mode=mode)
    except Exception as exc:  # noqa: BLE001
        # Defensive: a failed gate is not a green light. Treat it as
        # CAUTION rather than OK so the operator sees the problem.
        logger.exception(
            "Sanity gate failed for %s; defaulting to SKIP", ticker
        )
        return SanityGateOutcome(
            ticker=ticker,
            verdict="SKIP",
            check=None,
            reason=f"gate_error: {exc}",
        )
    return SanityGateOutcome(
        ticker=ticker,
        verdict=check.verdict,
        check=check,
        reason=check.reason,
    )


async def _gather_with_evidence(
    *,
    tickers: Iterable[tuple[str, float, str]],
    mode: str,
    db_session_factory=None,
) -> list[SanityGateOutcome]:
    """Dispatch the batch concurrently. ``db_session_factory`` is optional
    — when provided, evidence (filings) is pulled from Postgres; when
    omitted the gate runs on score+action only (still valid, just less
    informed)."""
    coros = []
    for ticker, score, action in tickers:
        filings_summary = ""
        if db_session_factory is not None:
            filings_summary = await _safe_filings_summary(
                db_session_factory, ticker
            )
        coros.append(
            _check_one(
                ticker=ticker,
                composite_score=score,
                action=action,
                filings_summary=filings_summary,
                mode=mode,
            )
        )
    return await asyncio.gather(*coros)


async def _safe_filings_summary(db_session_factory, ticker: str) -> str:
    """Async-safe wrapper around ``_summarize_recent_filings``. Returns
    empty on any failure so the gate still runs without filings context."""
    from src.research_agent.sanity_evidence import _summarize_recent_filings

    try:
        async with db_session_factory() as session:
            return await _summarize_recent_filings(
                session, ticker=ticker, window_days=30
            )
    except Exception:  # noqa: BLE001
        logger.debug("Filings lookup failed for %s; running gate without it",
                     ticker, exc_info=True)
        return ""


def gate_picks_sync(
    *,
    picks: list[dict],
    mode: str = "auto",
    score_key: str = "z_score",
    action: str = "BUY",
    include_filings: bool = True,
) -> SanityGateResult:
    """Sync entry point for batch scripts.

    ``picks`` is a list of dicts each carrying at minimum ``ticker`` plus a
    numeric score field (``z_score`` for factor picks, ``composite_score``
    for the old composite). REJECT removes the ticker from ``kept``;
    CAUTION keeps it but surfaces in ``cautioned``. SKIP (gate error) is
    treated as REJECT — when in doubt, don't trade.

    The mock path runs offline; the live path requires ANTHROPIC_API_KEY.
    On no key + auto mode the auto dispatcher falls back to mock — see
    ``check_buy_signal_auto``.
    """
    if not picks:
        return SanityGateResult(kept=[], rejected=[], cautioned=[], outcomes={})

    tuples: list[tuple[str, float, str]] = []
    for p in picks:
        ticker = p.get("ticker")
        if not ticker:
            continue
        score = float(p.get(score_key) or p.get("composite_score") or 0.0)
        tuples.append((ticker, score, action))

    if not tuples:
        return SanityGateResult(kept=[], rejected=[], cautioned=[], outcomes={})

    db_session_factory = None
    if include_filings:
        try:
            from src.db.session import get_sessionmaker
            db_session_factory = get_sessionmaker()
        except Exception:  # noqa: BLE001
            logger.warning(
                "DB session factory unavailable; gate runs without filings"
            )

    outcomes = asyncio.run(
        _gather_with_evidence(
            tickers=tuples, mode=mode, db_session_factory=db_session_factory
        )
    )
    return _build_result(outcomes)


def _build_result(outcomes: list[SanityGateOutcome]) -> SanityGateResult:
    kept: list[str] = []
    rejected: list[str] = []
    cautioned: list[str] = []
    by_ticker: dict[str, SanityGateOutcome] = {}
    for o in outcomes:
        by_ticker[o.ticker] = o
        if o.verdict == "OK":
            kept.append(o.ticker)
        elif o.verdict == "CAUTION":
            kept.append(o.ticker)
            cautioned.append(o.ticker)
        else:  # REJECT or SKIP — both drop the ticker
            rejected.append(o.ticker)
    return SanityGateResult(
        kept=kept,
        rejected=rejected,
        cautioned=cautioned,
        outcomes=by_ticker,
    )


def is_available() -> bool:
    """Quick check that the gate can run live (env key present)."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


__all__ = [
    "SanityGateOutcome",
    "SanityGateResult",
    "gate_picks_sync",
    "is_available",
]
