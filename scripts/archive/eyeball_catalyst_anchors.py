"""Day-1 eyeball test for the catalyst anchor library.

Decisions this script informs:
  * Are any anchors so similar to each other they're redundant?
    (Pairwise anchor-vs-anchor cosines - anything > 0.85 is too close.)
  * Does each anchor have a "natural" top-K filing chunk in the corpus
    that a human would also pick? If not, the phrase needs editing.
  * Does the CRM cluster's nearest 8-K hit a sensible anchor?

Usage:
    uv run python -m scripts.eyeball_catalyst_anchors

No DB writes. Pure read-only diagnostic.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date

import numpy as np
from rich.console import Console
from rich.table import Table
from sqlalchemy import text

from src.db.session import dispose_engine, get_sessionmaker
from src.research_agent.rag.embedder import embed_texts
from src.scoring.catalyst_anchors import (
    ANCHORS,
    anchor_keys,
    anchors_by_polarity,
    embed_anchors,
    similarities_to_anchors,
)

logging.basicConfig(level=logging.WARNING)
console = Console()


def _print_pairwise_redundancy() -> None:
    """Phase 1 of the eyeball test: how similar are the anchors to
    each other? Any pair > 0.85 means the phrases are too close and
    we'd be encoding the same axis twice."""
    matrix = embed_anchors()
    n = len(ANCHORS)
    table = Table(title="Pairwise anchor cosine - flag rows > 0.85")
    table.add_column("anchor_a")
    table.add_column("anchor_b")
    table.add_column("cosine", justify="right")
    table.add_column("polarity_match", justify="center")

    flagged = 0
    for i in range(n):
        for j in range(i + 1, n):
            c = float(matrix[i] @ matrix[j])
            same_pol = "Y" if ANCHORS[i].polarity == ANCHORS[j].polarity else "N"
            if c > 0.70:
                flag = "[red]REDUNDANT[/red]" if c > 0.85 else "[yellow]close[/yellow]"
                table.add_row(
                    ANCHORS[i].key, ANCHORS[j].key,
                    f"{c:.3f} {flag}", same_pol,
                )
                flagged += 1
    if flagged == 0:
        console.print(
            "[green]No pair exceeded the 0.70 'close' threshold.[/green] "
            "All 10 anchors point in distinct semantic directions."
        )
    else:
        console.print(table)


async def _print_top_filing_per_anchor(session) -> None:
    """Phase 2: for each anchor, what's the nearest filing chunk in
    the (currently sparse) ``filings_corpus``? Lets us eyeball whether
    the semantic match agrees with human judgment."""
    matrix = embed_anchors()
    table = Table(title="Top-1 chunk per anchor - does the match read right?")
    table.add_column("anchor", style="cyan")
    table.add_column("polarity")
    table.add_column("ticker")
    table.add_column("form")
    table.add_column("filing_date")
    table.add_column("score", justify="right")
    table.add_column("excerpt", max_width=80)

    for i, anc in enumerate(ANCHORS):
        q_vec = matrix[i]
        q_str = "[" + ",".join(f"{x:.6f}" for x in q_vec.tolist()) + "]"
        sql = text(
            """
            SELECT ticker, form, filing_date, accession_no, chunk_index, chunk_text,
                   1 - (embedding <=> CAST(:q AS vector)) AS score
            FROM filings_corpus
            ORDER BY embedding <=> CAST(:q AS vector)
            LIMIT 1
            """
        )
        result = await session.execute(sql, {"q": q_str})
        row = result.first()
        if row is None:
            table.add_row(anc.key, anc.polarity, "-", "-", "-", "-", "(empty corpus)")
            continue
        excerpt = (row.chunk_text or "").strip().replace("\n", " ")[:200]
        table.add_row(
            anc.key, anc.polarity, row.ticker, row.form,
            str(row.filing_date), f"{row.score:.3f}", excerpt,
        )
    console.print(table)


async def _print_crm_cluster_enrichment(session) -> None:
    """Phase 3: the real test - for the actual CRM insider cluster
    we ingested (2026-03-19 cluster, $1M, 2 insiders), pull the
    nearest 8-K chunk and compute its similarity to every anchor.
    Eyeball whether the ranking matches what a human reader of the
    filing would conclude.
    """
    sql = text(
        """
        SELECT chunk_text, embedding::text AS emb_text, filing_date
        FROM filings_corpus
        WHERE ticker = 'CRM' AND form = '8-K'
        ORDER BY filing_date DESC, chunk_index ASC
        LIMIT 1
        """
    )
    result = await session.execute(sql)
    row = result.first()
    if row is None:
        console.print(
            "[red]No CRM 8-K in corpus.[/red] Run "
            "`uv run python -m scripts.ingest_filings --tickers CRM --forms 8-K --per-form 4` first."
        )
        return

    chunk = row.chunk_text or ""
    console.print(
        f"\n[bold]CRM nearest-8K ({row.filing_date}) - first 400 chars[/bold]\n"
        f"  {chunk[:400]!r}\n"
    )

    # Embed the chunk fresh (faster than parsing the stored vector string).
    chunk_vec = embed_texts([chunk])[0]
    sims = similarities_to_anchors(chunk_vec)
    table = Table(title="CRM 8-K chunk similarity to each anchor - top anchor wins")
    table.add_column("anchor", style="cyan")
    table.add_column("polarity")
    table.add_column("cosine", justify="right")
    rows = sorted(sims.items(), key=lambda kv: kv[1], reverse=True)
    for key, score in rows:
        polarity = next(a.polarity for a in ANCHORS if a.key == key)
        style = "green" if score == rows[0][1] else ""
        table.add_row(key, polarity, f"[{style}]{score:.3f}[/{style}]" if style else f"{score:.3f}")
    console.print(table)


async def _main() -> int:
    console.rule("[bold]Day-1 eyeball test for catalyst anchor library[/bold]")
    console.print(
        f"Library size: {len(ANCHORS)} anchors "
        f"({len(anchors_by_polarity('bullish'))} bullish, "
        f"{len(anchors_by_polarity('bearish'))} bearish)\n"
    )
    console.rule("Phase 1 - pairwise redundancy")
    _print_pairwise_redundancy()

    SessionLocal = get_sessionmaker()
    async with SessionLocal() as session:
        console.rule("Phase 2 - top-1 chunk per anchor (sparse corpus, some misses expected)")
        await _print_top_filing_per_anchor(session)

        console.rule("Phase 3 - CRM cluster nearest-8K vs anchors")
        await _print_crm_cluster_enrichment(session)

    await dispose_engine()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
