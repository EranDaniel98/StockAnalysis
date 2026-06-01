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

from src.factors.strategy_id import strategy_name

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
    strategy: str = field(default_factory=strategy_name)
    coverage: dict[str, int] = field(default_factory=dict)
    sector_cap_skipped: list[dict] = field(default_factory=list)
    # When the caller asked for the long-short variant, ``shorts`` holds
    # the bottom-N picks (worst composite → expected to underperform).
    # Empty otherwise.
    shorts: pd.DataFrame = field(default_factory=pd.DataFrame)
    # Per-ticker EDGAR fundamental row counts (loader.coverage()). Lets the
    # per-stock factor-analysis endpoint flag thin-history names (e.g. a recent
    # spin-off with few quarters) whose quality/value ranks are unreliable.
    per_ticker_coverage: dict[str, int] = field(default_factory=dict)


# Known share-class groups -- when two tickers represent the same
# underlying company (differing only in voting rights / index inclusion),
# selecting both is dilution without diversification benefit. The
# pipeline picks the higher-ranked of any group and skips the rest with
# reason='share_class_dup'.
#
# Keep this list short and curated. False positives (treating unrelated
# names as a pair) are worse than false negatives (missing a pair).
# Add a row only after confirming the two tickers are the same legal
# entity, not just same sector/business.
_SHARE_CLASS_GROUPS: list[frozenset[str]] = [
    frozenset({"GOOG", "GOOGL"}),    # Alphabet (C non-voting / A voting)
    frozenset({"BRK.A", "BRK.B"}),   # Berkshire Hathaway
    frozenset({"BF.A", "BF.B"}),     # Brown-Forman
    frozenset({"FOX", "FOXA"}),      # Fox Corp
    frozenset({"LBRDA", "LBRDK"}),   # Liberty Broadband
    frozenset({"LEN", "LEN.B"}),     # Lennar
]


def _share_class_group_for(ticker: str) -> frozenset[str] | None:
    """Return the share-class group containing ``ticker``, or None."""
    for group in _SHARE_CLASS_GROUPS:
        if ticker in group:
            return group
    return None


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

    Also dedups share-class twins via ``_SHARE_CLASS_GROUPS``: the first
    (highest-ranked) member of a group is selected; subsequent members
    are skipped with reason ``share_class_dup``.

    Returns the selected picks DataFrame and a skipped-log of evicted
    higher-ranked names with the reason. ``None`` / missing sectors are
    bucketed as ``"Unknown"`` with their own cap.
    """
    import math
    from collections import defaultdict

    max_per_sector = max(1, math.ceil(top_n * max_sector_pct / 100.0))
    selected: list[dict] = []
    sector_counts: dict[str, int] = defaultdict(int)
    claimed_share_groups: set[frozenset[str]] = set()
    skipped: list[dict] = []
    for _, row in composite.iterrows():
        if len(selected) >= top_n:
            break
        ticker = row["ticker"]
        sector = sectors.get(ticker) or "Unknown"
        group = _share_class_group_for(ticker)
        if group is not None and group in claimed_share_groups:
            twins = ",".join(sorted(t for t in group if t != ticker))
            skipped.append({
                "ticker": ticker,
                "rank": int(row["rank"]),
                "sector": sector,
                "reason": f"share_class_dup:{twins}",
            })
            continue
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
        if group is not None:
            claimed_share_groups.add(group)
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
    from src.factors.fundamentals_pit_loader import (
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
    hysteresis_bonus: float = 0.0,
    previous_longs: Optional[list[str]] = None,
    previous_shorts: Optional[list[str]] = None,
    sector_neutral_quality: bool = True,
    min_z: float | None = None,
    require_pead: bool = False,
    min_history_days: int | None = None,
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
    hysteresis_bonus : stickiness for previously-held names, expressed
        as a fraction of ``top_n``. 0.0 disables. 0.75 (the
        backtest-validated default) reduces a held name's rank by
        0.75 × top_n slots before selection, so a 24-name portfolio
        keeps any held name still in the top-42. Validated 2026-05-18
        against the d05_r63 + PEAD config: cross-window α +8.81% vs
        baseline +4.50%, stress-window DD -8.24% vs -15.41%.
    previous_longs, previous_shorts : tickers held coming into this
        rebalance. Required when ``hysteresis_bonus > 0``; ignored
        otherwise. Pass the previous run's ``picks`` / ``shorts`` ticker
        lists.

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
    from src.factors.earnings_cache import load_earnings_histories
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

    # Minimum-history filter -- excludes recent IPOs / spin-offs whose
    # factor signals would be computed on partial history. SNDK 2025
    # WDC-spin-off case (project_ai_sanity_check 2026-05-19): 315 days
    # of pre-as_of history is enough to pass the momentum_12_1 252-day
    # floor BUT the fundamentals/quality/value frames silently rely on
    # quarterly EDGAR rows, of which a spin-off has very few. Set this
    # to 504 (2 years) at the daily-picks layer to keep the universe
    # clean. Backtests starting near a snapshot's left edge may need
    # to pass None to disable.
    if min_history_days is not None and min_history_days > 0:
        before = len(prices)
        kept: dict[str, pd.DataFrame] = {}
        excluded: list[tuple[str, int]] = []
        for t, p in prices.items():
            n_pre = int((p.index <= as_of).sum()) if p is not None else 0
            if n_pre >= min_history_days:
                kept[t] = p
            else:
                excluded.append((t, n_pre))
        prices = kept
        logger.info(
            "Min-history filter (%d days pre-as_of): kept %d / %d names; "
            "dropped %d (first 5: %s)",
            min_history_days, len(prices), before, len(excluded),
            [f"{t}({n}d)" for t, n in excluded[:5]],
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

    # Sectors: pulled once for the universe up front. yfinance cache
    # serves repeat reads; only first run pays the network. Needed by
    # sector-neutral quality (computed before the composite blend) AND
    # by the sector cap selector (post-composite).
    universe_sectors = get_sectors(universe) if sector_neutral_quality else {}

    mom = momentum_12_1(prices, as_of)
    qual = quality_factor(loader, universe, as_of)
    if sector_neutral_quality and not qual.empty:
        from src.factors.sector_neutralize import sector_neutralize
        qual = sector_neutralize(qual, universe_sectors)
        logger.info(
            "Sector-neutralized quality: ranks computed WITHIN sector"
        )
    val = value_factor(loader, prices, universe, as_of)

    factor_frames = [mom, qual, val]
    pead = pd.DataFrame()
    pead_display = pd.DataFrame()
    factors_used = ["momentum", "quality", "value"]
    if sector_neutral_quality:
        factors_used.append("sector_neutral")
    if include_pead:
        logger.info("Loading earnings histories for PEAD (--include-pead)...")
        earnings = load_earnings_histories(universe, earnings_cache_dir)
        pead = pead_factor(earnings, as_of, prices=prices)
        # Composite uses the strict PEAD frame (drift-active names only).
        # Display ranks use a fill_universe variant so picks without an
        # active drift window get a neutral PEAD rank rather than NaN —
        # keeps the briefing dashboard's coverage bar at 24/24 without
        # polluting composite selection.
        pead_display = pead_factor(
            earnings, as_of, prices=prices, fill_universe=True,
        )
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

    # Hysteresis: re-order the composite so held names get a bonus.
    # The bonus reduces churn (lower cost drag) and prevents whipsaws
    # in noisy regimes. Backtest 2026-05-18 picked 0.75 as the sweet
    # spot: improves stress-window α by +7.17pp without giving up the
    # bull-window α. The bonus does NOT change ``rank`` on the
    # composite (kept for downstream display) — only the selection
    # order via ``_eff_rank``.
    selection_frame = composite
    if hysteresis_bonus > 0:
        held_longs = set(previous_longs or [])
        held_shorts = set(previous_shorts or [])
        if held_longs or held_shorts:
            bonus_slots = max(1, int(round(hysteresis_bonus * top_n)))
            adjusted = composite.copy()

            def _adjust(row):
                r = int(row["rank"])
                t = row["ticker"]
                if t in held_longs:
                    return max(1, r - bonus_slots)
                if t in held_shorts:
                    return r + bonus_slots
                return r

            adjusted["_eff_rank"] = adjusted.apply(_adjust, axis=1)
            selection_frame = (
                adjusted.sort_values("_eff_rank").reset_index(drop=True)
            )
            logger.info(
                "Hysteresis bonus=%.2f (%d slots) applied to %d longs / "
                "%d shorts",
                hysteresis_bonus, bonus_slots,
                len(held_longs), len(held_shorts),
            )

    # Batch sector lookup via yfinance cache. EDGAR rows carry no sector
    # (the ingest path never populates it), so a tertiary fallback to
    # loader.lookup_sector returns None for every name → cap binds on
    # one "Unknown" bucket. yfinance .info is the same source the OLD
    # analyzer pipeline reads from; we cache to disk to amortize the
    # cost across runs.
    composite_tickers = composite["ticker"].tolist()
    # Reuse the universe-wide map fetched earlier when available;
    # otherwise pull just the composite tickers.
    yf_sectors = universe_sectors or get_sectors(composite_tickers)
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

    # Pre-selection filters (opt-in). Applied to selection_frame BEFORE
    # sector cap so the cap operates on the post-filter universe.
    pre_filter_n = len(selection_frame)
    if min_z is not None:
        selection_frame = selection_frame[selection_frame["z_score"] >= min_z]
        logger.info(
            "min_z=%.2f kept %d / %d names",
            min_z, len(selection_frame), pre_filter_n,
        )
    if require_pead and not pead.empty:
        pead_tickers = set(pead["ticker"])
        before = len(selection_frame)
        selection_frame = selection_frame[selection_frame["ticker"].isin(pead_tickers)]
        logger.info(
            "require_pead kept %d / %d names",
            len(selection_frame), before,
        )

    sector_cap_skipped: list[dict] = []
    if max_sector_pct is None or max_sector_pct >= 100:
        top = selection_frame.head(top_n).copy()
        top["sector"] = top["ticker"].map(lambda t: sectors.get(t, "Unknown"))
    else:
        top, sector_cap_skipped = _select_with_sector_cap(
            selection_frame, sectors, top_n=top_n, max_sector_pct=max_sector_pct,
        )
        if len(top) < top_n:
            logger.warning(
                "Sector cap bound at %.0f%%: filled %d of %d picks (%d skipped)",
                max_sector_pct, len(top), top_n, len(sector_cap_skipped),
            )

    top = _attach_per_factor_ranks(top, mom, qual, val, pead_display)

    # Long-short: pull the BOTTOM names by composite as shorts. Sector
    # cap also applies on the short side — we don't want a sector
    # tilted long AND short at the same time (concentration risk).
    shorts = pd.DataFrame()
    if long_short:
        n_short = short_n if short_n is not None else top_n
        # Sort by descending effective rank (worst first). When hysteresis
        # is active, _eff_rank already had held shorts pushed DOWN (higher
        # rank), so sorting descending puts them at the top of the short
        # pool — they stay shorts. Without hysteresis, _eff_rank doesn't
        # exist; fall back to "rank".
        sort_col = "_eff_rank" if "_eff_rank" in selection_frame.columns else "rank"
        bottom = selection_frame.sort_values(sort_col, ascending=False)
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
        shorts = _attach_per_factor_ranks(shorts, mom, qual, val, pead_display)

    # Attach per-factor ranks to the FULL composite (not just the picks) so any
    # ticker's breakdown is available for the per-stock factor-analysis view.
    composite = _attach_per_factor_ranks(composite, mom, qual, val, pead_display)

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
        per_ticker_coverage=dict(coverage),
    )
