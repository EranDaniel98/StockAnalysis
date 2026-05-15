"""Analyzer cross-correlation matrix.

The composite score weights six analyzers (technical, fundamental,
statistical, pattern, trend, alpha158) per the strategy. If two of those
analyzers are >0.7 correlated across the cross-section we are quietly
double-counting that information — the weight one of them "earned" is
really just a duplicate of the other.

This script builds the cross-correlation matrix on the score panel
already produced by build_score_panel. Run as a follow-up after
analyzer_ic_report.py — both share the same panel build path so caches
will be warm.

Output:
  - reports/analyzer_correlation.md   Pearson + Spearman matrices,
                                      flagged high-correlation pairs
  - reports/analyzer_correlation.json JSON twin for downstream tooling
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.config_loader import Config


logger = logging.getLogger("analyzer_correlation")


ANALYZER_COLUMNS = (
    "technical",
    "fundamental",
    "statistical",
    "pattern",
    "trend",
    "alpha158",
)

# > 0.7 absolute pairwise correlation → "redundant" weight inflation. Flag
# in the report so the operator can decide whether to re-balance weights.
REDUNDANCY_THRESHOLD = 0.7


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Per-pair Pearson + Spearman correlation across the "
                    "six analyzer sub-scores."
    )
    p.add_argument("--universe", default="russell_1000",
                   choices=("russell_1000",))
    p.add_argument("--start", default="2022-05-13")
    p.add_argument("--end", default="2024-05-13")
    p.add_argument("--rebalance-weekday", type=int, default=0)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--strategy", default="minimal_baseline")
    p.add_argument("--pit-fundamentals", action="store_true")
    p.add_argument(
        "--from-panel",
        help="Path to a pre-built score panel CSV (date,ticker,technical,"
             "fundamental,statistical,pattern,trend,alpha158,composite). "
             "If provided, skips the panel build phase entirely."
    )
    p.add_argument("--output", default="reports/analyzer_correlation.md")
    return p.parse_args()


def _flag_redundant(matrix: pd.DataFrame, threshold: float) -> list[tuple[str, str, float]]:
    pairs: list[tuple[str, str, float]] = []
    cols = list(matrix.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            v = matrix.at[a, b]
            if not np.isfinite(v):
                continue
            if abs(v) >= threshold:
                pairs.append((a, b, float(v)))
    pairs.sort(key=lambda t: abs(t[2]), reverse=True)
    return pairs


def _emit_markdown(
    *,
    output_path: Path,
    pearson: pd.DataFrame,
    spearman: pd.DataFrame,
    redundant_pearson: list[tuple[str, str, float]],
    redundant_spearman: list[tuple[str, str, float]],
    panel_rows: int,
    window: dict,
    ran_at: str,
) -> None:
    def _fmt(df: pd.DataFrame) -> list[str]:
        cols = list(df.columns)
        rows = ["| | " + " | ".join(cols) + " |",
                "|---|" + "|".join(["---"] * len(cols)) + "|"]
        for r in df.index:
            cells = []
            for c in cols:
                v = df.at[r, c]
                cells.append("n/a" if not np.isfinite(v) else f"{v:+.3f}")
            rows.append(f"| {r} | " + " | ".join(cells) + " |")
        return rows

    lines: list[str] = [
        f"# Analyzer Correlation Matrix",
        "",
        f"Generated {ran_at}.",
        "",
        f"- Window: {window['start']} → {window['end']}",
        f"- Panel rows: {panel_rows:,}",
        f"- Redundancy flag: |corr| ≥ {REDUNDANCY_THRESHOLD}",
        "",
        "## Reading the matrix",
        "",
        "Each cell is the cross-sectional correlation of two analyzer "
        "sub-scores over every (date, ticker) in the panel. Pearson catches "
        "linear duplicates, Spearman catches rank-order duplicates "
        "(more robust when analyzers compress to similar score buckets but "
        "with different magnitudes).",
        "",
        "**Redundancy reading:** if two analyzers carry > 0.7 correlation "
        "they're effectively voting the same way; the strategy's weighted "
        "composite is double-counting that signal. Either drop the weaker "
        "one or merge them.",
        "",
        "## Pearson",
        "",
    ]
    lines.extend(_fmt(pearson))
    lines.append("")
    lines.append("## Spearman")
    lines.append("")
    lines.extend(_fmt(spearman))
    lines.append("")
    lines.append("## Flagged pairs (|corr| ≥ %.2f)" % REDUNDANCY_THRESHOLD)
    lines.append("")
    if not (redundant_pearson or redundant_spearman):
        lines.append("None — every analyzer pair stays below the redundancy "
                     "threshold. Composite weighting is structurally clean.")
    else:
        lines.append("### Pearson")
        if redundant_pearson:
            for a, b, v in redundant_pearson:
                lines.append(f"- **{a} ↔ {b}**: {v:+.3f}")
        else:
            lines.append("- none")
        lines.append("")
        lines.append("### Spearman")
        if redundant_spearman:
            for a, b, v in redundant_spearman:
                lines.append(f"- **{a} ↔ {b}**: {v:+.3f}")
        else:
            lines.append("- none")
    lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _build_panel_from_engine(args) -> pd.DataFrame:
    """Re-runs the same scoring panel build the IC report uses."""
    from src.data.cache import DataCache
    from src.data.fetcher import DataFetcher
    from src.data.fundamentals import FundamentalsFetcher
    from src.backtest.engine import fetch_earnings_history
    from src.research.diagnostic_service import build_score_panel

    config = Config()
    strategy = config.get_strategy(args.strategy)
    if strategy is None:
        logger.error("Strategy %s missing", args.strategy)
        sys.exit(2)
    tickers = config.get_russell_1000_tickers()
    if not tickers:
        logger.error("Russell 1000 universe empty")
        sys.exit(2)

    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5,
        ),
    )
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    logger.info("Fetching %d ticker price histories...", len(tickers))
    price_data = fetcher.fetch_batch(tickers)
    fundamentals = fund_fetcher.fetch_batch(tickers)
    logger.info("Fetching earnings history...")
    earnings_history = fetch_earnings_history(list(price_data.keys()), workers=8)

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    logger.info("Building score panel...")
    return build_score_panel(
        price_data=price_data,
        fundamentals=fundamentals,
        earnings_history=earnings_history,
        config=config,
        strategy=strategy,
        start=start,
        end=end,
        rebalance_weekday=args.rebalance_weekday,
        workers=args.workers,
    )


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.from_panel:
        logger.info("Reading pre-built panel from %s", args.from_panel)
        panel = pd.read_csv(args.from_panel)
    else:
        panel = _build_panel_from_engine(args)

    if panel.empty:
        logger.error("Empty score panel — aborting")
        return 4

    surviving = [c for c in ANALYZER_COLUMNS if c in panel.columns]
    missing = [c for c in ANALYZER_COLUMNS if c not in panel.columns]
    if missing:
        logger.warning("Columns missing from panel: %s", missing)
    if len(surviving) < 2:
        logger.error("Not enough analyzer columns (got %d).", len(surviving))
        return 4

    subset = panel[surviving].copy()
    # Drop constant columns — correlation is undefined.
    nonconst = [c for c in surviving if subset[c].nunique(dropna=True) >= 2]
    dropped = sorted(set(surviving) - set(nonconst))
    if dropped:
        logger.warning("Constant analyzer columns dropped: %s", dropped)
    subset = subset[nonconst]

    pearson = subset.corr(method="pearson")
    spearman = subset.corr(method="spearman")
    redundant_pearson = _flag_redundant(pearson, REDUNDANCY_THRESHOLD)
    redundant_spearman = _flag_redundant(spearman, REDUNDANCY_THRESHOLD)

    ran_at = datetime.now(timezone.utc).isoformat()
    output_md = Path(args.output)
    _emit_markdown(
        output_path=output_md,
        pearson=pearson,
        spearman=spearman,
        redundant_pearson=redundant_pearson,
        redundant_spearman=redundant_spearman,
        panel_rows=len(panel),
        window={"start": args.start, "end": args.end},
        ran_at=ran_at,
    )
    output_md.with_suffix(".json").write_text(
        json.dumps(
            {
                "ran_at": ran_at,
                "window": {"start": args.start, "end": args.end},
                "panel_rows": int(len(panel)),
                "columns": nonconst,
                "dropped_constant": dropped,
                "pearson": pearson.round(4).to_dict(),
                "spearman": spearman.round(4).to_dict(),
                "redundant_pearson": [
                    {"a": a, "b": b, "corr": v}
                    for a, b, v in redundant_pearson
                ],
                "redundant_spearman": [
                    {"a": a, "b": b, "corr": v}
                    for a, b, v in redundant_spearman
                ],
                "redundancy_threshold": REDUNDANCY_THRESHOLD,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    logger.info("Wrote %s + %s", output_md, output_md.with_suffix(".json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
