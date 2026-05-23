"""Ad-hoc per-ticker analysis.

Run the comprehensive analyzer on any one ticker (or a small list).
Useful for:
  - Researching a name that's NOT in today's top picks
  - Sanity-checking a name before adding to a watchlist
  - Investigating why a held position is no longer ranked

Output: prints the same per-stock card the comprehensive_analysis
script produces for each pick, plus a "where does this rank in the
full universe?" header.

Usage
-----

    uv run python -m scripts.analyze_ticker NVDA AAPL TSLA
    uv run python -m scripts.analyze_ticker NVDA --output reports/adhoc_NVDA.md
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

logger = logging.getLogger("analyze_ticker")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("tickers", nargs="+",
                   help="One or more ticker symbols")
    p.add_argument("--as-of", default=None,
                   help="YYYY-MM-DD. Defaults to today.")
    p.add_argument("--equity", type=float, default=41042.0,
                   help="Hypothetical portfolio equity for sizing.")
    p.add_argument("--top-n", type=int, default=24,
                   help="Hypothetical portfolio size for sizing.")
    p.add_argument("--output", default=None,
                   help="Write markdown to this path (else stdout only)")
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()
    tickers = [t.upper() for t in args.tickers]
    as_of = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp.utcnow().tz_localize(None)
    logger.info("Analyzing %s as-of %s", ",".join(tickers), as_of.date())

    # We need the FULL universe to compute correct cross-sectional
    # factor ranks for our subjects. Pull the current PIT S&P 500 + the
    # subjects (in case a subject isn't in S&P 500).
    from src.config_loader import Config
    from src.storage.universe_loader import load_pit_sp500_with_prices

    config = Config()
    universe, prices = load_pit_sp500_with_prices(
        as_of, extra_tickers=tickers, config=config,
    )
    logger.info("Universe: %d names (incl. requested subjects)", len(universe))
    logger.info("Got prices for %d/%d", len(prices), len(universe))

    # Confirm we have prices for the subjects
    missing = [t for t in tickers if t not in prices]
    if missing:
        logger.error("No price data for: %s", missing)
        if not [t for t in tickers if t in prices]:
            return 2

    # EDGAR PIT for all (we need it for the composite computation across universe)
    from src.db.repositories.fundamentals import PostgresFundamentalsRepository
    from src.db.session import get_sessionmaker, run_with_dispose
    from src.factors.fundamentals_pit_loader import FundamentalsPITLoader

    logger.info("Loading EDGAR PIT fundamentals for universe...")

    async def _go():
        async with get_sessionmaker()() as session:
            repo = PostgresFundamentalsRepository(session)
            return await FundamentalsPITLoader.from_repository(repo, list(prices.keys()))

    loader = run_with_dispose(_go())

    # Compute the FULL composite over the universe to get accurate ranks
    from src.factors.composite import combine as combine_factors
    from src.factors.momentum import momentum_12_1
    from src.factors.quality import quality_factor
    from src.factors.value import value_factor

    logger.info("Computing factors over universe...")
    mom = momentum_12_1(prices, as_of)
    qual = quality_factor(loader, list(prices.keys()), as_of)
    val = value_factor(loader, prices, list(prices.keys()), as_of)
    composite = combine_factors([mom, qual, val], min_overlap=2)
    logger.info(
        "Universe ranking: momentum=%d, quality=%d, value=%d, composite=%d",
        len(mom), len(qual), len(val), len(composite),
    )

    # For each subject, build the analysis from its composite ranking
    from src.research.per_stock_analyzer import analyze_ticker, estimate_per_pick_returns
    from src.research.per_stock_markdown import render_one_stock

    # Use backtest trade log if available for return estimates.
    bt_path = Path("data/factors/sweep/comp_d05_r63_2024.json")
    trades = []
    if bt_path.exists():
        import json
        trades = json.loads(bt_path.read_text(encoding="utf-8")).get("trades_sample", [])
    exp_returns = estimate_per_pick_returns(trades)

    # Try to enrich with yfinance .info (analyst tgt, beta, short)
    yf_info_map = {}
    try:
        import yfinance as yf
        for t in tickers:
            if t not in prices:
                continue
            try:
                yf_info_map[t] = yf.Ticker(t).info or {}
            except Exception:  # noqa: BLE001
                yf_info_map[t] = {}
    except ImportError:
        pass

    # Build the report
    parts = []
    parts.append(f"# Ad-hoc Analysis — {as_of.date().isoformat()}")
    parts.append("")
    parts.append(f"*Composite universe size: {len(composite)} | "
                 f"Total universe analyzed: {len(prices)}*")
    parts.append("")

    for t in tickers:
        if t not in prices:
            parts.append(f"### {t}")
            parts.append(f"_No price data available._")
            parts.append("")
            continue

        # Find this ticker's ranks in each factor + composite
        comp_row = composite[composite["ticker"] == t]
        mom_row = mom[mom["ticker"] == t]
        qual_row = qual[qual["ticker"] == t]
        val_row = val[val["ticker"] == t]

        if comp_row.empty:
            parts.append(f"### {t}")
            parts.append(
                f"_Did not qualify for the composite (needs presence in "
                f"≥2 of 3 factor frames; momentum requires 252 trading "
                f"days of history)._"
            )
            parts.append("")
            continue

        comp_rank = int(comp_row["rank"].iloc[0])
        comp_z = float(comp_row["z_score"].iloc[0])
        pct_top = 100.0 * comp_rank / max(1, len(composite))

        # Verdict
        if pct_top <= 5:
            verdict = "STRONG BUY — top 5%, would be selected today"
        elif pct_top <= 10:
            verdict = "BUY-CANDIDATE — top 10%, on the bubble"
        elif pct_top <= 25:
            verdict = "WATCH — top quartile, monitor for rank improvement"
        elif pct_top <= 50:
            verdict = "NEUTRAL — middle of the pack"
        else:
            verdict = "AVOID — bottom half of the composite ranking"

        parts.append(f"## {t} — composite rank #{comp_rank} of {len(composite)} "
                     f"(top {pct_top:.1f}%)")
        parts.append(f"**Verdict:** {verdict}")
        parts.append("")

        # Build the StockAnalysis as if this name were pick #comp_rank
        a = analyze_ticker(
            ticker=t,
            prices=prices[t],
            loader=loader,
            as_of=as_of,
            composite_rank=comp_rank,
            composite_z=comp_z,
            mom_rank=int(mom_row["rank"].iloc[0]) if not mom_row.empty else None,
            qual_rank=int(qual_row["rank"].iloc[0]) if not qual_row.empty else None,
            val_rank=int(val_row["rank"].iloc[0]) if not val_row.empty else None,
            mom_raw=float(mom_row["raw"].iloc[0]) if not mom_row.empty else None,
            equity_usd=args.equity,
            n_positions=args.top_n,
            expected_returns=exp_returns,
            yf_info=yf_info_map.get(t, {}),
        )
        parts.append(render_one_stock(a))
        parts.append("---")
        parts.append("")

    md = "\n".join(parts)
    # cp1252 console can't print unicode like β; force UTF-8 stdout.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    print(md)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(md, encoding="utf-8")
        logger.info("Wrote %s", args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
