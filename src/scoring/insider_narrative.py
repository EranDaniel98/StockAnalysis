"""Reactive narrative enrichment for insider cluster signals.

When the insider_flow analyzer fires on a (ticker, cluster_end_date), this
module looks up the nearest 8-K filing in ``filings_corpus`` (the pgvector
RAG store from Phase 5.2) and returns a short excerpt — "what was disclosed
around the buy?" — that the UI / scan output can show alongside the cluster
score. Pure retrieval, no LLM call.

Lookahead-safe: only filings with ``filing_date <= cluster_end_date`` are
returned. Future filings are invisible (the insider may have *known* about
them and bought on inside information, but a backtest must not see them).

The reactive enrichment is intentionally separate from the analyzer's
``analyze()`` function — that one stays a pure function over a transaction
list, no DB dependency, so it remains fast in the backtest hot loop and
easy to unit-test. Enrichment is a scan-path concern, not a scoring-path
concern.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Forms we treat as "catalyst-bearing" prose. 8-K is the primary target
# (current-events disclosures: M&A, earnings, departures, lawsuits).
# 10-Q / 10-K are catch-alls when there's no recent 8-K.
DEFAULT_CATALYST_FORMS: tuple[str, ...] = ("8-K", "8-K/A")
FALLBACK_FORMS: tuple[str, ...] = ("10-Q", "10-K", "10-Q/A", "10-K/A")


@dataclass(frozen=True)
class NarrativeContext:
    """The enriched payload attached to an insider-cluster signal."""

    ticker: str
    cluster_end_date: date
    filing_date: date
    accession_no: str
    form: str
    days_to_cluster: int  # positive = filing happened BEFORE the cluster
    excerpt: str  # first ~600 chars of the chunk closest to filing start

    def to_dict(self) -> dict:
        d = asdict(self)
        d["cluster_end_date"] = self.cluster_end_date.isoformat()
        d["filing_date"] = self.filing_date.isoformat()
        return d


async def find_nearest_filing(
    session: AsyncSession,
    *,
    ticker: str,
    cluster_end_date: date,
    lookback_days: int = 14,
    forms: Iterable[str] = DEFAULT_CATALYST_FORMS,
    fallback_forms: Iterable[str] = FALLBACK_FORMS,
    fallback_lookback_days: int = 90,
    excerpt_chars: int = 600,
) -> Optional[NarrativeContext]:
    """Return the most-recent filing on or before ``cluster_end_date``
    for ``ticker``, restricted to ``forms`` within ``lookback_days``.

    Two-tier search:
      1. Look back ``lookback_days`` (default 14) for an 8-K — these are
         event-driven and the most likely catalyst near an insider buy.
      2. If nothing found, widen to ``fallback_lookback_days`` (default
         90) and accept 10-Q / 10-K as a periodic-report fallback.

    Returns the **chunk_index=0** row (the start of the filing — usually
    the cover / item-2.02 / "Entry into a Material Definitive Agreement"
    headline). We don't do a semantic match against the cluster — that
    would require something to match *against*, and the analyzer doesn't
    know what catalyst to expect. The simple recency match is the right
    primitive; the proactive item-2 work layers semantic similarity on
    top.

    Lookahead-safe by construction: ``filing_date <= cluster_end_date``.
    """
    primary = await _query_nearest(
        session,
        ticker=ticker,
        cluster_end_date=cluster_end_date,
        lookback_days=lookback_days,
        forms=tuple(forms),
        excerpt_chars=excerpt_chars,
    )
    if primary is not None:
        return primary

    return await _query_nearest(
        session,
        ticker=ticker,
        cluster_end_date=cluster_end_date,
        lookback_days=fallback_lookback_days,
        forms=tuple(fallback_forms),
        excerpt_chars=excerpt_chars,
    )


async def _query_nearest(
    session: AsyncSession,
    *,
    ticker: str,
    cluster_end_date: date,
    lookback_days: int,
    forms: tuple[str, ...],
    excerpt_chars: int,
) -> Optional[NarrativeContext]:
    """Single-tier query: nearest filing on or before cluster_end_date
    within ``lookback_days``, restricted to ``forms``. Returns None on
    miss."""
    if not forms:
        return None
    cutoff = cluster_end_date - timedelta(days=lookback_days)
    # Form list goes through an ANY(:forms) clause so SQLAlchemy binds a
    # single parameter (an array) rather than expanding into IN (?, ?).
    sql = text(
        """
        SELECT ticker, form, filing_date, accession_no, chunk_text
        FROM filings_corpus
        WHERE ticker = :ticker
          AND form = ANY(:forms)
          AND filing_date <= :cluster_end
          AND filing_date >= :cutoff
          AND chunk_index = 0
        ORDER BY filing_date DESC, accession_no DESC
        LIMIT 1
        """
    )
    result = await session.execute(
        sql,
        {
            "ticker": ticker.upper(),
            "forms": list(forms),
            "cluster_end": cluster_end_date,
            "cutoff": cutoff,
        },
    )
    row = result.first()
    if row is None:
        return None
    excerpt = (row.chunk_text or "")[:excerpt_chars].strip()
    return NarrativeContext(
        ticker=row.ticker,
        cluster_end_date=cluster_end_date,
        filing_date=row.filing_date,
        accession_no=row.accession_no,
        form=row.form,
        days_to_cluster=(cluster_end_date - row.filing_date).days,
        excerpt=excerpt,
    )


async def enrich_many(
    session: AsyncSession,
    candidates: Iterable[tuple[str, date]],
    **kwargs,
) -> dict[str, NarrativeContext]:
    """Batch helper: run ``find_nearest_filing`` for each (ticker,
    cluster_end_date) pair. Sequential rather than parallel — pgvector
    +HNSW lookups are sub-100ms and the candidate set per scan is at
    most a few dozen tickers; parallelization here would only burn
    connection-pool slots."""
    out: dict[str, NarrativeContext] = {}
    for ticker, cluster_end in candidates:
        ctx = await find_nearest_filing(
            session,
            ticker=ticker,
            cluster_end_date=cluster_end,
            **kwargs,
        )
        if ctx is not None:
            out[ticker.upper()] = ctx
    return out


async def compute_insider_flow_results_async(
    tickers: Iterable[str],
    *,
    as_of: date,
    lookback_days: int,
    flow_params: "InsiderFlowParams | None" = None,
    enrich_narrative: bool = False,
) -> dict[str, dict]:
    """Bulk pipeline for the scan path:
      1. load recent open-market buys for ``tickers`` from Postgres,
      2. run ``insider_flow.analyze`` on each ticker,
      3. for every cluster that fires, look up the nearest 8-K (or
         10-Q/10-K fallback) in ``filings_corpus`` and splice the
         narrative excerpt into the analyzer result's ``indicators``
         block under the ``narrative`` key.

    Returns ``{ticker: analyzer_result_dict}`` containing ONLY tickers
    where a cluster fired. Tickers absent from the dict map to "no
    insider_flow sub-score" (composite engine skips the slot — same
    convention as alpha158/PEAD/rel_strength).

    Async because both data loads (Postgres + pgvector lookups) are
    async. The sync analyze_and_score wraps this with asyncio.run.
    """
    from src.db.repositories.insider import InsiderTransactionRepository
    from src.db.session import get_sessionmaker
    from src.scoring.analyzers import insider_flow as _if

    flow_params = flow_params or _if.InsiderFlowParams()
    tickers_list = [t.upper() for t in tickers]
    if not tickers_list:
        return {}

    SL = get_sessionmaker()
    async with SL() as session:
        repo = InsiderTransactionRepository(session)
        tx_by_ticker = await repo.recent_buys_many(
            tickers_list,
            days_back=lookback_days,
            as_of=as_of,
        )
        results: dict[str, dict] = {}
        candidates: list[tuple[str, date]] = []
        for ticker in tickers_list:
            txs = tx_by_ticker.get(ticker, [])
            if not txs:
                continue
            r = _if.analyze(txs, as_of=as_of, params=flow_params)
            if r is None:
                continue
            results[ticker] = r
            # Pull the cluster_end from the indicators block — the
            # analyzer stores cluster_age_days, so back-compute the
            # exact date the cluster closed.
            age_days = int(r["indicators"].get("cluster_age_days", 0))
            cluster_end = as_of - timedelta(days=age_days)
            candidates.append((ticker, cluster_end))

        if enrich_narrative and candidates:
            ctx_by_ticker = await enrich_many(session, candidates)
            for ticker, ctx in ctx_by_ticker.items():
                if ticker in results:
                    results[ticker]["indicators"]["narrative"] = ctx.to_dict()

    return results


def compute_insider_flow_results_sync(
    tickers: Iterable[str],
    *,
    as_of: date,
    lookback_days: int,
    flow_params: "InsiderFlowParams | None" = None,
    enrich_narrative: bool = False,
) -> dict[str, dict]:
    """Sync wrapper for ``compute_insider_flow_results_async``.

    Used by the scan service (synchronous loop) to call into the async
    DB stack via a single ``asyncio.run`` at the top of the scan.
    ``run_with_dispose`` disposes the engine inside this run so the next
    sync caller starts with a fresh asyncpg pool — otherwise the global
    pool stays bound to this now-closed loop and the next call hangs on
    Windows. See ``src/db/session.py:run_with_dispose``."""
    from src.db.session import run_with_dispose

    return run_with_dispose(
        compute_insider_flow_results_async(
            tickers,
            as_of=as_of,
            lookback_days=lookback_days,
            flow_params=flow_params,
            enrich_narrative=enrich_narrative,
        )
    )


async def compute_catalyst_results_async(
    tickers: Iterable[str],
    *,
    as_of: date,
    max_age_days: int = 60,
    min_sim: float = 0.30,
) -> dict[str, dict]:
    """Bulk pipeline for the catalyst analyzer in the scan path:
      1. Load the most-recent ``insider_narrative_snapshots`` row per
         ticker (cluster_end_date <= as_of), within ``max_age_days``.
      2. Run ``catalyst.analyze`` on each one.
      3. Return ``{ticker: result_dict}`` for tickers that fired.

    Missing-snapshot tickers are simply absent from the result (same
    convention as ``compute_insider_flow_results_async``).
    """
    from sqlalchemy import desc, select

    from src.db.models import InsiderNarrativeSnapshot as INS
    from src.db.session import get_sessionmaker
    from src.scoring.analyzers import catalyst as cat
    from src.scoring.analyzers.catalyst import CatalystParams

    tickers_list = [t.upper() for t in tickers]
    if not tickers_list:
        return {}

    cutoff = as_of - timedelta(days=max_age_days)
    params = cat.CatalystParams(max_age_days=max_age_days, min_sim=min_sim)

    SL = get_sessionmaker()
    out: dict[str, dict] = {}
    async with SL() as session:
        # Most-recent snapshot per (ticker) within the age window. Done
        # via per-ticker LIMIT 1 queries — the universe is at most a
        # few dozen tickers per scan, so 36 round-trips is cheaper than
        # a window function for the data sizes we actually see.
        for ticker in tickers_list:
            stmt = (
                select(INS)
                .where(INS.ticker == ticker)
                .where(INS.cluster_end_date <= as_of)
                .where(INS.cluster_end_date >= cutoff)
                .order_by(desc(INS.cluster_end_date))
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                continue
            result = cat.analyze(row, as_of=as_of, params=params)
            if result is not None:
                out[ticker] = result
    return out


def compute_catalyst_results_sync(
    tickers: Iterable[str],
    *,
    as_of: date,
    max_age_days: int = 60,
    min_sim: float = 0.30,
) -> dict[str, dict]:
    """Sync wrapper for ``compute_catalyst_results_async`` — the scan
    service is synchronous and wraps a single ``asyncio.run`` per
    pre-pass. ``run_with_dispose`` disposes the engine inside this run
    so the next sync caller (typically the insider-flow pre-pass right
    after) starts with a fresh asyncpg pool."""
    from src.db.session import run_with_dispose

    return run_with_dispose(
        compute_catalyst_results_async(
            tickers,
            as_of=as_of,
            max_age_days=max_age_days,
            min_sim=min_sim,
        )
    )
