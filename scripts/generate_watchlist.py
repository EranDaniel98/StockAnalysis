"""Generate a watchlist of names ranked 25-100 (just outside top-24).

These are the names most likely to enter the strategy at the next
quarterly rebalance. Use to:
  - Anticipate changes to the portfolio
  - Spot names whose factor profile is improving (rank rising)
  - Find candidates if a current position drops out of top-24
    mid-cycle

Output: reports/watchlist_YYYY-MM-DD.md
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("generate_watchlist")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", default=None)
    p.add_argument("--start-rank", type=int, default=25,
                   help="Start of the watch range (exclusive of top-N).")
    p.add_argument("--end-rank", type=int, default=100,
                   help="End of the watch range.")
    p.add_argument("--output", required=True)
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()
    as_of = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp.utcnow().tz_localize(None)

    # Load universe + prices + EDGAR + factors (same as daily_factor_picks)
    from src.config_loader import Config
    from src.data.cache import DataCache
    from src.data.fetcher import DataFetcher

    config = Config()
    universe = config.get_sp500_pit_tickers(as_of)
    logger.info("Universe: %d tickers", len(universe))

    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5,
        ),
    )
    fetcher = DataFetcher(config, cache)
    logger.info("Fetching prices...")
    raw = fetcher.fetch_batch(universe)
    prices: dict[str, pd.DataFrame] = {}
    for t, df in raw.items():
        if df is None or df.empty:
            continue
        d = df.copy()
        if isinstance(d.index, pd.DatetimeIndex) and d.index.tz is not None:
            d.index = d.index.tz_convert("UTC").tz_localize(None)
        prices[t] = d
    logger.info("Got prices for %d/%d", len(prices), len(universe))

    # EDGAR PIT
    from src.db.repositories.fundamentals import PostgresFundamentalsRepository
    from src.db.session import get_sessionmaker, run_with_dispose
    from src.factors.fundamentals_pit_loader import FundamentalsPITLoader

    logger.info("Loading EDGAR fundamentals...")

    async def _go():
        async with get_sessionmaker()() as session:
            repo = PostgresFundamentalsRepository(session)
            return await FundamentalsPITLoader.from_repository(
                repo, list(prices.keys()),
            )

    loader = run_with_dispose(_go())

    from src.factors.composite import combine as combine_factors
    from src.factors.momentum import momentum_12_1
    from src.factors.quality import quality_factor
    from src.factors.value import value_factor

    mom = momentum_12_1(prices, as_of)
    qual = quality_factor(loader, list(prices.keys()), as_of)
    val = value_factor(loader, prices, list(prices.keys()), as_of)
    composite = combine_factors([mom, qual, val], min_overlap=2)
    logger.info("Composite ranking: %d names", len(composite))

    watch = composite[(composite["rank"] >= args.start_rank) &
                      (composite["rank"] <= args.end_rank)].copy()
    watch = watch.merge(
        mom[["ticker", "rank"]].rename(columns={"rank": "mom_rank"}),
        on="ticker", how="left",
    )
    watch = watch.merge(
        qual[["ticker", "rank"]].rename(columns={"rank": "qual_rank"}),
        on="ticker", how="left",
    )
    watch = watch.merge(
        val[["ticker", "rank"]].rename(columns={"rank": "val_rank"}),
        on="ticker", how="left",
    )

    lines: list[str] = []
    lines.append(f"# Watchlist — {as_of.date().isoformat()}")
    lines.append("")
    lines.append(f"*Composite ranks {args.start_rank}–{args.end_rank} of "
                 f"{len(composite)} — names just outside the top-5%.*")
    lines.append("")
    lines.append("Use this to: anticipate next-quarter rebalance, spot "
                 "improving names, find replacements if a held position "
                 "drops mid-cycle.")
    lines.append("")
    lines.append("| Rank | Ticker | z-score | Mom | Qual | Val | Strongest |")
    lines.append("|---|---|---|---|---|---|---|")
    for _, r in watch.iterrows():
        # Identify dominant factor (lowest rank = strongest)
        per_factor = []
        if pd.notna(r["mom_rank"]):
            per_factor.append(("MOM", int(r["mom_rank"])))
        if pd.notna(r["qual_rank"]):
            per_factor.append(("QUAL", int(r["qual_rank"])))
        if pd.notna(r["val_rank"]):
            per_factor.append(("VAL", int(r["val_rank"])))
        per_factor.sort(key=lambda x: x[1])
        strongest = per_factor[0][0] if per_factor else "—"

        lines.append(
            f"| {int(r['rank'])} | **{r['ticker']}** | "
            f"{float(r['z_score']):+.2f} | "
            f"{int(r['mom_rank']) if pd.notna(r['mom_rank']) else '-'} | "
            f"{int(r['qual_rank']) if pd.notna(r['qual_rank']) else '-'} | "
            f"{int(r['val_rank']) if pd.notna(r['val_rank']) else '-'} | "
            f"{strongest} |"
        )
    lines.append("")
    lines.append(f"Total names in range: **{len(watch)}**")
    lines.append("")
    lines.append("**How to interpret:**")
    lines.append("- Names with low MOM rank (high momentum) are most likely to "
                 "enter the top-24 if any current pick fades.")
    lines.append("- Names with low VAL rank (cheap on earnings yield) are "
                 "deep-value candidates if the market rotates from growth.")
    lines.append("- Cross-factor scoring (low ranks in 2+ factors) is the "
                 "best signal — those names are 'on the bubble' for next "
                 "quarter's rebalance.")
    lines.append("")
    lines.append(f"For a per-stock plan on any of these, run:")
    lines.append(f"```bash")
    lines.append(f"uv run python -m scripts.analyze_ticker <TICKER>")
    lines.append(f"```")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
