"""Factor-composite pick pipeline — the single source of truth.

Wraps the universe loader + factor computations + composite rank-blend
into one callable used by every entry point:
- ``scripts/daily_factor_picks.py`` — file-based daily run
- ``src/cli/main.py:cmd_factor_picks`` — CLI surface
- ``src/api/routers/...`` — web/API surface (future)

Why a service-layer module:
- Before this, the daily script and the CLI used different code paths
  that could diverge. The audit named this "the most important
  structural fact in the codebase" — real-money picks came from the
  script, the CLI scan command produced different stocks.
- Now: one function, one set of factor frames, one composite, one
  ranking. Callers pick presentation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class FactorPicksResult:
    """Output of one factor-pick run. Snapshot-stable when ``snapshot_id``
    is set."""

    as_of: pd.Timestamp
    factors_used: list[str]
    universe_size: int
    composite: pd.DataFrame  # all names, columns: ticker, raw, rank, z_score, mean_normalized_rank
    top_n: pd.DataFrame      # top-N picks with per-factor rank columns merged in
    snapshot_id: Optional[str] = None
    strategy: str = "composite_d05_r63"
    coverage: dict[str, int] = field(default_factory=dict)
    sector_cap_skipped: list[dict] = field(default_factory=list)
    # When the caller asked for the long-short variant, ``shorts`` holds
    # the bottom-N picks (worst composite → expected to underperform).
    # Empty otherwise.
    shorts: pd.DataFrame = field(default_factory=pd.DataFrame)


def _select_with_sector_cap(
    composite: pd.DataFrame,
    sectors: dict[str, str],
    top_n: int,
    max_sector_pct: float,
) -> tuple[pd.DataFrame, list[dict]]:
    """Walk the ranked composite picking up to ``top_n`` names with a per-sector cap.

    The cap is expressed as a percentage of ``top_n`` and rounded up so a
    20% cap on 24 picks yields 5 names/sector (not 4). When every remaining
    candidate is in a capped sector we under-fill rather than relax the
    cap — the under-fill is the honest signal that the cap is binding.

    Returns the selected picks DataFrame and a skipped-log of evicted
    higher-ranked names with the reason. ``None`` / missing sectors are
    bucketed as ``"Unknown"`` with their own cap.
    """
    import math
    from collections import defaultdict

    max_per_sector = max(1, math.ceil(top_n * max_sector_pct / 100.0))
    selected: list[dict] = []
    sector_counts: dict[str, int] = defaultdict(int)
    skipped: list[dict] = []
    for _, row in composite.iterrows():
        if len(selected) >= top_n:
            break
        ticker = row["ticker"]
        sector = sectors.get(ticker) or "Unknown"
        if sector_counts[sector] >= max_per_sector:
            skipped.append({
                "ticker": ticker,
                "rank": int(row["rank"]),
                "sector": sector,
                "reason": f"sector_cap:{sector}",
            })
            continue
        record = row.to_dict()
        record["sector"] = sector
        selected.append(record)
        sector_counts[sector] += 1
    if not selected:
        empty = composite.iloc[0:0].copy()
        if "sector" not in empty.columns:
            empty["sector"] = pd.Series(dtype="object")
        return empty, skipped
    return pd.DataFrame(selected), skipped


def _attach_per_factor_ranks(
    top: pd.DataFrame,
    mom: pd.DataFrame,
    qual: pd.DataFrame,
    val: pd.DataFrame,
    pead: pd.DataFrame,
) -> pd.DataFrame:
    """Merge per-factor ranks into the top-N table for the markdown UI."""
    out = top.merge(
        mom[["ticker", "rank"]].rename(columns={"rank": "mom_rank"}),
        on="ticker", how="left",
    )
    out = out.merge(
        qual[["ticker", "rank"]].rename(columns={"rank": "qual_rank"}),
        on="ticker", how="left",
    )
    out = out.merge(
        val[["ticker", "rank"]].rename(columns={"rank": "val_rank"}),
        on="ticker", how="left",
    )
    if not pead.empty:
        out = out.merge(
            pead[["ticker", "rank"]].rename(columns={"rank": "pead_rank"}),
            on="ticker", how="left",
        )
    return out.sort_values("rank").reset_index(drop=True)


def _load_fundamentals_sync(tickers: list[str]):
    """Sync wrapper around the async EDGAR PIT loader."""
    from src.db.repositories.fundamentals import (
        PostgresFundamentalsRepository,
    )
    from src.db.session import get_sessionmaker, run_with_dispose
    from src.scoring.fundamentals_pit_loader import (
        FundamentalsPITLoader,
    )

    async def _go():
        async with get_sessionmaker()() as session:
            repo = PostgresFundamentalsRepository(session)
            return await FundamentalsPITLoader.from_repository(repo, tickers)

    return run_with_dispose(_go())


def run_factor_picks(
    *,
    as_of: pd.Timestamp,
    top_n: int = 24,
    snapshot_id: Optional[str] = None,
    include_pead: bool = False,
    earnings_cache_dir: Path | str = "data/earnings_history",
    min_overlap: int = 2,
    max_sector_pct: float | None = 30.0,
    long_short: bool = False,
    short_n: Optional[int] = None,
) -> FactorPicksResult:
    """Compute today's composite-factor picks.

    Parameters
    ----------
    as_of : as-of date. Factor frames only use data on/before this date.
    top_n : number of picks to return in ``result.top_n``.
    snapshot_id : when set, prices are loaded from the frozen snapshot
        for deterministic reproduction. When None, prices are pulled
        live via yfinance.
    include_pead : when True, add the PEAD factor as a 4th frame. Off by
        default until backtest-validated against snapshots that include
        surprise %.
    earnings_cache_dir : where to cache per-ticker earnings parquets.
    min_overlap : ``composite.combine`` parameter — minimum frames a
        ticker must appear in to qualify.
    max_sector_pct : per-sector cap as a percentage of ``top_n``. The
        2026-05-17 picks ran 46% Financial Services because the naive
        ``head(top_n)`` selector ignored sector. Default 30 matches
        ``config/settings.yaml:risk_management.position_sizing.max_sector_pct``.
        Pass ``None`` to restore the legacy naive top-N behaviour.

    Returns
    -------
    FactorPicksResult — both the full ranked universe and the top-N
    picks-table.
    """
    from src.data.sector_cache import get_sectors
    from src.factors.composite import combine as combine_factors
    from src.factors.momentum import momentum_12_1
    from src.factors.pead import pead_factor
    from src.factors.quality import quality_factor
    from src.factors.value import value_factor
    from src.scoring.earnings_cache import load_earnings_histories
    from src.storage.universe_loader import (
        load_from_snapshot, load_pit_sp500_with_prices,
    )

    if snapshot_id:
        tickers, prices = load_from_snapshot(snapshot_id)
    else:
        tickers, prices = load_pit_sp500_with_prices(as_of)
    logger.info(
        "Loaded %d tickers with prices (out of %d in PIT universe)",
        len(prices), len(tickers),
    )

    universe = sorted(prices.keys())
    logger.info("Loading EDGAR PIT fundamentals for %d names...", len(universe))
    loader = _load_fundamentals_sync(universe)
    coverage = loader.coverage()
    n_covered = sum(1 for c in coverage.values() if c > 0)
    logger.info(
        "Fundamentals coverage: %d/%d (%.1f%%)",
        n_covered, len(universe),
        100.0 * n_covered / max(1, len(universe)),
    )

    mom = momentum_12_1(prices, as_of)
    qual = quality_factor(loader, universe, as_of)
    val = value_factor(loader, prices, universe, as_of)

    factor_frames = [mom, qual, val]
    pead = pd.DataFrame()
    factors_used = ["momentum", "quality", "value"]
    if include_pead:
        logger.info("Loading earnings histories for PEAD (--include-pead)...")
        earnings = load_earnings_histories(universe, earnings_cache_dir)
        pead = pead_factor(earnings, as_of, prices=prices)
        factor_frames.append(pead)
        factors_used.append("pead")

    logger.info(
        "Factor coverage: momentum=%d, quality=%d, value=%d, pead=%d",
        len(mom), len(qual), len(val), len(pead),
    )

    composite = combine_factors(factor_frames, min_overlap=min_overlap)
    if composite.empty:
        logger.error("Composite factor returned no names")
        return FactorPicksResult(
            as_of=as_of, factors_used=factors_used,
            universe_size=0, composite=composite, top_n=composite,
            snapshot_id=snapshot_id,
        )

    # Batch sector lookup via yfinance cache. EDGAR rows carry no sector
    # (the ingest path never populates it), so a tertiary fallback to
    # loader.lookup_sector returns None for every name → cap binds on
    # one "Unknown" bucket. yfinance .info is the same source the OLD
    # analyzer pipeline reads from; we cache to disk to amortize the
    # cost across runs.
    composite_tickers = composite["ticker"].tolist()
    yf_sectors = get_sectors(composite_tickers)
    sectors: dict[str, str] = {}
    for t in composite_tickers:
        sector = yf_sectors.get(t)
        if not sector:
            sector = loader.lookup_sector(t, as_of.to_pydatetime())
        sectors[t] = sector or "Unknown"
    n_classified = sum(1 for s in sectors.values() if s != "Unknown")
    logger.info(
        "Sector classification: %d / %d names (%.1f%%) — yfinance hits %d",
        n_classified, len(sectors),
        100.0 * n_classified / max(1, len(sectors)),
        sum(1 for t in composite_tickers if yf_sectors.get(t)),
    )

    sector_cap_skipped: list[dict] = []
    if max_sector_pct is None or max_sector_pct >= 100:
        top = composite.head(top_n).copy()
        top["sector"] = top["ticker"].map(lambda t: sectors.get(t, "Unknown"))
    else:
        top, sector_cap_skipped = _select_with_sector_cap(
            composite, sectors, top_n=top_n, max_sector_pct=max_sector_pct,
        )
        if len(top) < top_n:
            logger.warning(
                "Sector cap bound at %.0f%%: filled %d of %d picks (%d skipped)",
                max_sector_pct, len(top), top_n, len(sector_cap_skipped),
            )

    top = _attach_per_factor_ranks(top, mom, qual, val, pead)

    # Long-short: pull the BOTTOM names by composite as shorts. Sector
    # cap also applies on the short side — we don't want a sector
    # tilted long AND short at the same time (concentration risk).
    shorts = pd.DataFrame()
    if long_short:
        n_short = short_n if short_n is not None else top_n
        # Sort by descending rank (worst first), then take top n_short.
        bottom = composite.sort_values("rank", ascending=False)
        if max_sector_pct is None or max_sector_pct >= 100:
            shorts = bottom.head(n_short).copy()
            shorts["sector"] = shorts["ticker"].map(
                lambda t: sectors.get(t, "Unknown")
            )
        else:
            shorts, _ = _select_with_sector_cap(
                bottom, sectors, top_n=n_short,
                max_sector_pct=max_sector_pct,
            )
        # Drop any ticker that appears on both sides (shouldn't happen
        # on a 480-name universe with d05 selection but defensive).
        if not shorts.empty and not top.empty:
            shorts = shorts[~shorts["ticker"].isin(set(top["ticker"]))]
        shorts = _attach_per_factor_ranks(shorts, mom, qual, val, pead)

    return FactorPicksResult(
        as_of=as_of,
        factors_used=factors_used,
        universe_size=len(composite),
        composite=composite,
        top_n=top,
        snapshot_id=snapshot_id,
        coverage={"fundamentals_covered": n_covered, "universe": len(universe)},
        sector_cap_skipped=sector_cap_skipped,
        shorts=shorts,
    )
