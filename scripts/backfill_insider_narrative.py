"""Backfill the insider_narrative_snapshots table from historical
insider clusters + the existing filings_corpus.

For each ticker in --universe (or --tickers), this script:
  1. Loads all open-market buys (code='P', acquired) from
     insider_transactions.
  2. Walks every distinct cluster_end_date the insider_flow analyzer
     ever produces (dedup'd by (ticker, cluster_end_date)).
  3. For each cluster, finds the nearest filing in filings_corpus
     (8-K within 14d, fallback 10-Q/K within 90d) with
     filing_date <= cluster_end_date — lookahead-safe.
  4. Embeds the filing's chunks freshly via sentence-transformers,
     computes max cosine vs each anchor in
     src/scoring/catalyst_anchors.
  5. Upserts an insider_narrative_snapshots row keyed on
     (ticker, cluster_end_date). Idempotent — re-running updates
     existing rows in place.

Usage:
    uv run python -m scripts.backfill_insider_narrative --universe themes
    uv run python -m scripts.backfill_insider_narrative --tickers CRM,SNOW
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Optional

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.config_loader import Config
from src.db.models import InsiderNarrativeSnapshot
from src.db.repositories.insider import InsiderTransactionRepository
from src.db.session import dispose_engine, get_sessionmaker
from src.research_agent.rag.embedder import EMBEDDING_MODEL, embed_texts
from src.scoring.analyzers import insider_flow as if_module
from src.scoring.catalyst_anchors import ANCHORS, anchor_keys
from src.scoring.insider_narrative import (
    DEFAULT_CATALYST_FORMS,
    FALLBACK_FORMS,
)
from src.scoring.insider_narrative_features import (
    NarrativeFeatures,
    compute_features,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_insider_narrative")


@dataclass(frozen=True)
class Cluster:
    """One distinct cluster snapshot we'll insert one row for."""

    ticker: str
    cluster_end_date: date
    insider_count: int
    senior_count: int
    cluster_value_usd: Decimal


@dataclass(frozen=True)
class FilingMatch:
    """Nearest filing found for a cluster. ``chunks`` is the full set
    of chunk_text rows ordered by chunk_index — we'll embed them all
    for the max-similarity aggregation."""

    form: str
    filing_date: date
    accession_no: str
    chunks: tuple[str, ...]


def _resolve_universe(cfg: Config, universe: str, tickers_arg: str | None) -> list[str]:
    if tickers_arg:
        return [t.strip().upper() for t in tickers_arg.split(",") if t.strip()]
    if universe == "watchlist":
        return cfg.get_watchlist()
    if universe == "themes":
        return cfg.get_theme_tickers()
    if universe == "portfolio":
        from src.portfolio import Portfolio

        return Portfolio(cfg).get_tickers()
    raise ValueError(f"unknown universe: {universe}")


async def _find_clusters(
    repo: InsiderTransactionRepository,
    ticker: str,
    *,
    flow_params: if_module.InsiderFlowParams,
    history_days: int = 1825,  # 5 years
) -> list[Cluster]:
    """Walk every P-code buy for ``ticker`` and snapshot every distinct
    cluster the analyzer produces."""
    end = date.today()
    start = end - timedelta(days=history_days)
    buys = await repo.open_market_buys(ticker, start=start, end=end)
    # Dedup'd by (ticker, cluster_end_date) — multiple buys in the same
    # cluster will all resolve to the same cluster_end and we only want
    # one snapshot.
    seen: dict[date, Cluster] = {}
    # For each buy date we encounter, run analyzer over the full known
    # transaction history as_of=that_date. The analyzer dedup'd internally
    # to "the strongest cluster in the rolling window."
    candidate_dates = sorted({b.transaction_date for b in buys})
    for as_of in candidate_dates:
        result = if_module.analyze(buys, as_of=as_of, params=flow_params)
        if result is None:
            continue
        age = int(result["indicators"]["cluster_age_days"])
        cluster_end = as_of - timedelta(days=age)
        if cluster_end in seen:
            continue
        seen[cluster_end] = Cluster(
            ticker=ticker.upper(),
            cluster_end_date=cluster_end,
            insider_count=int(result["indicators"]["insider_count"]),
            senior_count=int(result["indicators"]["senior_count"]),
            cluster_value_usd=Decimal(str(result["indicators"]["total_value_usd"])),
        )
    return list(seen.values())


async def _find_filing(
    session: AsyncSession,
    *,
    ticker: str,
    cluster_end: date,
    lookback_days: int = 14,
    fallback_lookback_days: int = 90,
) -> Optional[FilingMatch]:
    """Two-tier filing search: 8-K within lookback_days, else 10-Q/K
    within fallback_lookback_days. Returns the chosen filing along
    with all its chunks (ordered) so the caller can embed once. Same
    lookahead-safety semantics as ``insider_narrative.find_nearest_filing``."""
    chosen = await _query_one(
        session,
        ticker=ticker,
        cluster_end=cluster_end,
        lookback_days=lookback_days,
        forms=DEFAULT_CATALYST_FORMS,
    )
    if chosen is not None:
        return chosen
    return await _query_one(
        session,
        ticker=ticker,
        cluster_end=cluster_end,
        lookback_days=fallback_lookback_days,
        forms=FALLBACK_FORMS,
    )


async def _query_one(
    session: AsyncSession,
    *,
    ticker: str,
    cluster_end: date,
    lookback_days: int,
    forms: tuple[str, ...],
) -> Optional[FilingMatch]:
    """Pick the most-recent (filing_date, accession_no) tuple for
    ``ticker`` whose form is in ``forms`` and filing_date is in
    [cluster_end - lookback_days, cluster_end], then pull all its
    chunks. Returns None if no qualifying filing exists."""
    if not forms:
        return None
    cutoff = cluster_end - timedelta(days=lookback_days)
    head_sql = text(
        """
        SELECT form, filing_date, accession_no
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
    row = (
        await session.execute(
            head_sql,
            {
                "ticker": ticker.upper(),
                "forms": list(forms),
                "cluster_end": cluster_end,
                "cutoff": cutoff,
            },
        )
    ).first()
    if row is None:
        return None
    # Pull all chunks of the chosen filing for the max-similarity
    # aggregation. Ordered by chunk_index for reproducibility (max is
    # invariant to order but logs read better in original sequence).
    chunks_rows = (
        await session.execute(
            text(
                """
                SELECT chunk_text
                FROM filings_corpus
                WHERE accession_no = :accn
                ORDER BY chunk_index ASC
                """
            ),
            {"accn": row.accession_no},
        )
    ).all()
    chunks = tuple(r.chunk_text or "" for r in chunks_rows)
    return FilingMatch(
        form=row.form,
        filing_date=row.filing_date,
        accession_no=row.accession_no,
        chunks=chunks,
    )


def _features_for_filing(filing: Optional[FilingMatch]) -> NarrativeFeatures:
    """Embed all chunks (if any) and compute max-similarity features."""
    if filing is None or not filing.chunks:
        return compute_features(np.zeros((0, 384), dtype=np.float32))
    chunk_vecs = embed_texts(list(filing.chunks))
    return compute_features(chunk_vecs)


async def _upsert_snapshot(
    session: AsyncSession,
    cluster: Cluster,
    filing: Optional[FilingMatch],
    features: NarrativeFeatures,
) -> None:
    """Insert (or update on conflict) one row in
    insider_narrative_snapshots. Keyed on the natural uniqueness
    (ticker, cluster_end_date) — re-running the backfill is idempotent
    and any anchor-library tweaks update prior rows on next run."""
    has_8k = filing is not None and filing.form in ("8-K", "8-K/A")
    days_to_filing: Optional[int] = (
        (cluster.cluster_end_date - filing.filing_date).days
        if filing is not None
        else None
    )

    row: dict = {
        "ticker": cluster.ticker,
        "cluster_end_date": cluster.cluster_end_date,
        "insider_count": cluster.insider_count,
        "senior_count": cluster.senior_count,
        "cluster_value_usd": cluster.cluster_value_usd,
        "has_recent_8k": has_8k,
        "nearest_filing_form": filing.form if filing else None,
        "nearest_filing_date": filing.filing_date if filing else None,
        "nearest_filing_accession": filing.accession_no if filing else None,
        "days_to_filing": days_to_filing,
        "top_bullish_anchor": features.top_bullish_anchor,
        "top_bearish_anchor": features.top_bearish_anchor,
        "top_bullish_sim": features.top_bullish_sim,
        "top_bearish_sim": features.top_bearish_sim,
        "narrative_skew": features.narrative_skew,
        "embedding_model": EMBEDDING_MODEL,
    }
    # Map per-anchor similarities into their column names.
    for k in anchor_keys():
        row[f"sim_{k}"] = features.similarities.get(k)

    stmt = pg_insert(InsiderNarrativeSnapshot).values(**row)
    # ON CONFLICT (ticker, cluster_end_date) DO UPDATE — re-run safety.
    update_cols = {
        c: stmt.excluded[c]
        for c in row.keys()
        if c not in ("ticker", "cluster_end_date")
    }
    stmt = stmt.on_conflict_do_update(
        constraint="uq_narrative_snap_natural",
        set_=update_cols,
    )
    await session.execute(stmt)


async def _backfill_ticker(
    session: AsyncSession,
    ticker: str,
    flow_params: if_module.InsiderFlowParams,
) -> tuple[int, int, int]:
    """Process one ticker. Returns (clusters_found, with_filing,
    with_8k)."""
    repo = InsiderTransactionRepository(session)
    clusters = await _find_clusters(repo, ticker, flow_params=flow_params)
    if not clusters:
        return (0, 0, 0)
    with_filing = 0
    with_8k = 0
    for cluster in clusters:
        filing = await _find_filing(
            session,
            ticker=ticker,
            cluster_end=cluster.cluster_end_date,
        )
        features = _features_for_filing(filing)
        await _upsert_snapshot(session, cluster, filing, features)
        if filing is not None:
            with_filing += 1
            if filing.form in ("8-K", "8-K/A"):
                with_8k += 1
    await session.commit()
    return (len(clusters), with_filing, with_8k)


async def _run(args: argparse.Namespace) -> int:
    cfg = Config()
    tickers = _resolve_universe(cfg, args.universe, args.tickers)
    if not tickers:
        logger.error("empty universe; nothing to backfill")
        return 2

    flow_cfg = cfg.get_insider_flow()
    flow_params = if_module.InsiderFlowParams(
        window_days=int(flow_cfg.get("window_days", 30)),
        min_cluster_insiders=int(flow_cfg.get("min_cluster_insiders", 2)),
    )

    SessionLocal = get_sessionmaker()
    totals = {"clusters": 0, "with_filing": 0, "with_8k": 0, "tickers_with_clusters": 0}
    try:
        async with SessionLocal() as session:
            for i, ticker in enumerate(tickers, 1):
                try:
                    c, wf, w8 = await _backfill_ticker(session, ticker, flow_params)
                except Exception as e:
                    logger.error("  [%s] failed: %s", ticker, e)
                    continue
                if c == 0:
                    logger.info("  [%d/%d] %s: no clusters", i, len(tickers), ticker)
                    continue
                totals["clusters"] += c
                totals["with_filing"] += wf
                totals["with_8k"] += w8
                totals["tickers_with_clusters"] += 1
                logger.info(
                    "  [%d/%d] %s: %d clusters, %d w/ filing (%d 8-K)",
                    i, len(tickers), ticker, c, wf, w8,
                )
    finally:
        await dispose_engine()

    logger.info(
        "done: %d clusters across %d tickers; %d w/ filing; %d w/ recent 8-K",
        totals["clusters"], totals["tickers_with_clusters"],
        totals["with_filing"], totals["with_8k"],
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="themes",
                    choices=["watchlist", "themes", "portfolio"])
    ap.add_argument("--tickers", default=None,
                    help="Comma-separated override for --universe.")
    args = ap.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
