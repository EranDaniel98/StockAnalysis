"""Today's composite factor picks.

Generates the top-N names by the m+q+v composite factor for the
current trading day, using:
  - the current PIT S&P 500 universe (Wikipedia)
  - the most recent EDGAR PIT fundamentals (Postgres)
  - current prices (yfinance live or from a frozen snapshot)

Outputs JSON to `data/daily_picks/YYYY-MM-DD.json` and a human-
readable markdown summary to stdout.

Recommended deployment config (per
`reports/factor_strategy_report_2026_05_16.md`):

  uv run python -m scripts.daily_factor_picks \\
      --top-n 24 \\
      --output-dir data/daily_picks/

24 names = top 5% of S&P 500. Rebalance quarterly (every ~63 trading
days) for the live strategy — don't trade these picks daily.

This script is read-only and DOES NOT place orders. Hand the output
to the paper-trading runner or review by eye before any execution.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.factors.composite import combine as combine_factors
from src.factors.momentum import momentum_12_1
from src.factors.pead import pead_factor
from src.factors.quality import quality_factor
from src.factors.value import value_factor

logger = logging.getLogger("daily_factor_picks")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--top-n", type=int, default=24,
                   help="Number of picks (default 24 = top 5%% of ~500).")
    p.add_argument("--snapshot-id", default=None,
                   help="Use a frozen snapshot for prices (deterministic) "
                        "instead of pulling fresh from yfinance.")
    p.add_argument("--as-of", default=None,
                   help="As-of date (YYYY-MM-DD). Default = today.")
    p.add_argument("--output-dir", default="data/daily_picks",
                   help="Where to write the JSON.")
    p.add_argument("--include-pead", action="store_true",
                   help="Include the PEAD factor in the composite. Requires "
                        "an earnings-history fetch (yfinance, slow on a cold "
                        "cache; ~3-5 min for the full S&P 500). Default OFF "
                        "until validated against frozen snapshots.")
    p.add_argument("--earnings-cache-dir", default="data/earnings_history",
                   help="Where to cache per-ticker earnings parquets so "
                        "subsequent --include-pead runs are fast.")
    return p.parse_args()


def _load_universe_and_prices(snapshot_id: str | None, as_of: pd.Timestamp):
    """Return (tickers, prices_dict). From snapshot if given, else fresh."""
    if snapshot_id:
        from src.storage.snapshot import load_snapshot
        snap = load_snapshot(snapshot_id)
        tickers = sorted(snap.price_data.keys())
        return tickers, snap.price_data

    # Fresh-pull path: PIT universe + yfinance prices.
    from src.config_loader import Config
    from src.data.cache import DataCache
    from src.data.fetcher import DataFetcher

    config = Config()
    tickers = config.get_sp500_pit_tickers(as_of)
    if not tickers:
        raise SystemExit("Universe is empty — run scripts/fetch_sp500_membership.py")

    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5,
        ),
    )
    fetcher = DataFetcher(config, cache)
    logger.info("Fetching prices for %d tickers (live)...", len(tickers))
    raw = fetcher.fetch_batch(tickers)
    # Normalize to the same shape the snapshot path produces: tz-naive
    # DatetimeIndex. yfinance live returns UTC-aware indices which
    # break tz-naive comparisons in the factor code.
    normalized: dict[str, pd.DataFrame] = {}
    for t, df in raw.items():
        if df is None or df.empty:
            continue
        d = df.copy()
        if isinstance(d.index, pd.DatetimeIndex) and d.index.tz is not None:
            d.index = d.index.tz_convert("UTC").tz_localize(None)
        normalized[t] = d
    return tickers, normalized


def _load_earnings_histories(
    tickers: list[str],
    cache_dir: Path,
    *,
    max_age_hours: int = 24,
) -> dict[str, pd.DataFrame]:
    """Pull recent earnings + surprise history for each ticker.

    Caches per-ticker parquets under ``cache_dir`` so subsequent runs
    don't re-hammer yfinance. Surprise columns vary by ticker (yfinance
    is patchy); we keep whatever yfinance returns and let the analyzer
    pick the surprise column it can parse.
    """
    import time
    import yfinance as yf

    cache_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    out: dict[str, pd.DataFrame] = {}
    n_fetched = 0
    n_cached = 0
    n_missing = 0

    for t in tickers:
        cache_path = cache_dir / f"{t}.parquet"
        if cache_path.exists():
            age = (now - cache_path.stat().st_mtime) / 3600.0
            if age <= max_age_hours:
                try:
                    df = pd.read_parquet(cache_path)
                    if not df.empty:
                        out[t] = df
                        n_cached += 1
                        continue
                except Exception:
                    pass  # fall through to refetch

        try:
            df = yf.Ticker(t).get_earnings_dates(limit=40)
        except Exception as e:
            logger.debug("earnings fetch failed for %s: %s", t, e)
            n_missing += 1
            continue
        if df is None or df.empty:
            n_missing += 1
            continue
        try:
            # Reset index → parquet round-trip preserves the timestamp.
            df_out = df.reset_index().rename(
                columns={df.index.name or "index": "earnings_ts"}
            )
            df_out.to_parquet(cache_path, index=False)
        except Exception as e:
            logger.debug("earnings cache write failed for %s: %s", t, e)
        out[t] = df
        n_fetched += 1

    logger.info(
        "Earnings histories: %d cached + %d fetched + %d missing (of %d)",
        n_cached, n_fetched, n_missing, len(tickers),
    )
    return out


def _load_fundamentals(tickers: list[str]):
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


def _render_markdown(picks: pd.DataFrame, as_of: pd.Timestamp,
                     total_universe: int) -> str:
    lines = []
    lines.append(f"# Composite Factor Picks — {as_of.date().isoformat()}\n")
    lines.append(f"**Universe:** PIT S&P 500, {total_universe} eligible names")
    lines.append(f"**Strategy:** equal-weight rank-blend of momentum + quality + value")
    lines.append(f"**Selection:** top {len(picks)} by composite rank "
                 f"(~{100*len(picks)/max(1,total_universe):.1f}% of universe)\n")
    has_pead = "pead_rank" in picks.columns
    if has_pead:
        lines.append("| Rank | Ticker | Momentum | Quality | Value | PEAD | Composite z |")
        lines.append("|------|--------|----------|---------|-------|------|-------------|")
    else:
        lines.append("| Rank | Ticker | Momentum | Quality | Value | Composite z |")
        lines.append("|------|--------|----------|---------|-------|-------------|")
    for _, r in picks.iterrows():
        cells = [
            f"{int(r['rank']):>4d}",
            f"{r['ticker']:>6s}",
            f"{r['mom_rank'] if pd.notna(r['mom_rank']) else '-':>8}",
            f"{r['qual_rank'] if pd.notna(r['qual_rank']) else '-':>7}",
            f"{r['val_rank'] if pd.notna(r['val_rank']) else '-':>5}",
        ]
        if has_pead:
            pead_cell = r['pead_rank'] if pd.notna(r['pead_rank']) else '-'
            cells.append(f"{pead_cell:>4}")
        cells.append(f"{r['z_score']:>+10.2f}")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("**Allocation:** equal-weight (1/N each)")
    lines.append("**Hold period:** quarterly rebalance recommended "
                 "(~63 trading days)")
    lines.append("")
    lines.append("*Generated by scripts/daily_factor_picks.py — read-only; "
                 "DOES NOT place orders.*")
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()

    as_of = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp.utcnow().normalize().tz_localize(None)
    logger.info("As-of: %s | top_n: %d", as_of.date(), args.top_n)

    tickers, prices = _load_universe_and_prices(args.snapshot_id, as_of)
    logger.info(
        "Loaded %d tickers with prices (out of %d in PIT universe)",
        len(prices), len(tickers),
    )

    universe = sorted(prices.keys())
    logger.info("Loading EDGAR PIT fundamentals for %d names...", len(universe))
    loader = _load_fundamentals(universe)
    cov = loader.coverage()
    n_covered = sum(1 for c in cov.values() if c > 0)
    logger.info("Fundamentals coverage: %d/%d (%.1f%%)",
                n_covered, len(universe),
                100.0 * n_covered / max(1, len(universe)))

    # Compute factors at as_of.
    mom = momentum_12_1(prices, as_of)
    qual = quality_factor(loader, universe, as_of)
    val = value_factor(loader, prices, universe, as_of)

    factor_frames = [mom, qual, val]
    pead = pd.DataFrame()
    if args.include_pead:
        logger.info("Loading earnings histories for PEAD (--include-pead)...")
        earnings = _load_earnings_histories(
            universe, Path(args.earnings_cache_dir),
        )
        pead = pead_factor(earnings, as_of, prices=prices)
        factor_frames.append(pead)

    logger.info(
        "Factor coverage: momentum=%d, quality=%d, value=%d, pead=%d",
        len(mom), len(qual), len(val), len(pead),
    )

    composite = combine_factors(factor_frames, min_overlap=2)
    if composite.empty:
        logger.error("Composite factor returned no names")
        return 2

    # Pick top-N + attach per-factor ranks for transparency.
    top = composite.head(args.top_n).copy()
    top = top.merge(
        mom[["ticker", "rank"]].rename(columns={"rank": "mom_rank"}),
        on="ticker", how="left",
    )
    top = top.merge(
        qual[["ticker", "rank"]].rename(columns={"rank": "qual_rank"}),
        on="ticker", how="left",
    )
    top = top.merge(
        val[["ticker", "rank"]].rename(columns={"rank": "val_rank"}),
        on="ticker", how="left",
    )
    if not pead.empty:
        top = top.merge(
            pead[["ticker", "rank"]].rename(columns={"rank": "pead_rank"}),
            on="ticker", how="left",
        )
    top = top.sort_values("rank").reset_index(drop=True)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"{as_of.date().isoformat()}.json"
    factors_used = ["momentum", "quality", "value"]
    if args.include_pead:
        factors_used.append("pead")
    payload = {
        "as_of": as_of.date().isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "strategy": "composite_d05_r63",
        "factors": factors_used,
        "universe_size": len(composite),
        "top_n": len(top),
        "picks": top.to_dict(orient="records"),
        "snapshot_id": args.snapshot_id,
    }
    out_json.write_text(json.dumps(payload, indent=2, default=str),
                        encoding="utf-8")

    md = _render_markdown(top, as_of, len(composite))
    print(md)
    out_md = out_dir / f"{as_of.date().isoformat()}.md"
    out_md.write_text(md, encoding="utf-8")
    logger.info("Wrote %s and %s", out_json, out_md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
