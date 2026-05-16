"""Per-analyzer Information Coefficient report.

Audit question we are answering:

    Of the seven analyzers folded into the composite score, WHICH actually
    predict forward returns at retail-tradable horizons, and which are
    noise that inflate our backtest by chance?

We do not trust the composite Sharpe in isolation. Even if the headline
Sharpe is real, it may be carried by one analyzer while six others
contribute zero or negative IC and just bulk up the weighted average.

Methodology
-----------

1. Build a (date, ticker, factor) score panel across a chosen window
   using the live scoring engine, with as-of slicing — same code path
   the backtest uses. Walk every weekly rebalance date.
2. Build a wide Close-price matrix on the same window.
3. For each analyzer column independently (technical, fundamental,
   patterns, statistical, trend_detector, alpha158, pead) PLUS the
   composite as control:
     - Pass through alphalens.get_clean_factor_and_forward_returns
     - Compute IC mean, std, IR per horizon (5D, 21D)
     - Compute top-quintile minus bottom-quintile spread per horizon
     - Compute a one-sample t-stat on the IC time series; p-value
       under the null IC=0 via two-tailed Student-t.
4. Bonferroni-correct the per-analyzer p-values across the 7
   comparisons (multiply by 7, cap at 1.0). Alpha158 internally
   aggregates ~25 sub-factors but we score it as one composite
   per the analyzer's public interface, so Bonferroni is across
   analyzers not micro-factors.
5. Verdict per analyzer:
     IC mean > 0.05 and Bonferroni-p < 0.05 → STRONG signal
     IC mean > 0.03 and Bonferroni-p < 0.05 → MODEST signal
     IC mean > 0.01                          → WEAK
     otherwise                                → NOISE

Output: markdown report at the chosen path. Same script also dumps the
raw stats to JSON next to it so downstream tooling can chart over time.

Usage
-----
    uv run python -m scripts.analyzer_ic_report \\
        [--universe russell_1000] \\
        [--start 2022-05-13 --end 2024-05-13] \\
        [--rebalance-weekday 0] \\
        [--quantiles 5] \\
        [--output reports/analyzer_ic_2022_2024.md]
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from src.config_loader import Config


logger = logging.getLogger("analyzer_ic_report")


# Sub-score keys as set by src/scoring/engine.py:calculate_composite_score
# (NOT the analyzer module file names — "pattern" not "patterns", "trend"
# not "trend_detector"). PEAD is a bonus modifier, not a sub-score, so it
# is not testable from the panel; we'd need to surface the raw pead_score
# separately to include it here.
ANALYZER_COLUMNS = (
    "technical",
    "fundamental",
    "statistical",
    "pattern",
    "trend",
    "alpha158",
)

# Composite included as control. Not Bonferroni-counted — it is the
# weighted aggregate of the analyzers, not an independent test.
CONTROL_COLUMN = "composite"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Per-analyzer IC report. Tells us which analyzers "
                    "actually predict forward returns vs which are noise."
    )
    p.add_argument("--universe", default="russell_1000",
                   choices=("russell_1000",))
    p.add_argument("--start", default="2022-05-13",
                   help="ISO date — panel start")
    p.add_argument("--end", default="2024-05-13",
                   help="ISO date — panel end (must satisfy survivorship "
                        "guard for the chosen universe)")
    p.add_argument("--rebalance-weekday", type=int, default=0,
                   choices=range(0, 5),
                   help="0=Mon ... 4=Fri. Default 0 matches backtest engine.")
    p.add_argument("--quantiles", type=int, default=5)
    p.add_argument("--periods", default="5,21",
                   help="Comma-separated forward-return horizons in trading "
                        "days. Default 5,21.")
    p.add_argument("--output",
                   default="reports/analyzer_ic.md")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--strategy", default="minimal_baseline",
                   help="Strategy to score with. Defaults to the control "
                        "strategy so analyzer weights don't bias the panel.")
    p.add_argument("--pit-fundamentals", action="store_true",
                   help="Use EDGAR PIT loader for fundamentals "
                        "(strongly recommended).")
    p.add_argument("--panel-cache",
                   help="If provided, write the score panel to this CSV "
                        "path after building (or read it back instead of "
                        "rebuilding when the file already exists). Lets "
                        "the correlation matrix script reuse the same "
                        "panel without re-scoring the universe.")
    return p.parse_args()


def _bonferroni(p: float, k: int) -> float:
    """Cap-at-1 Bonferroni adjustment across k comparisons."""
    if p is None or not math.isfinite(p):
        return 1.0
    return min(1.0, p * k)


def _ic_t_p(ic_mean: float, ic_std: float, n_obs: int) -> tuple[float, float]:
    """One-sample t-stat + two-tailed p-value for H0: IC mean = 0."""
    if n_obs < 3 or ic_std <= 0 or not math.isfinite(ic_std):
        return (0.0, 1.0)
    se = ic_std / math.sqrt(n_obs)
    t = ic_mean / se if se > 0 else 0.0
    p = 2.0 * (1.0 - scipy_stats.t.cdf(abs(t), df=n_obs - 1))
    return (float(t), float(p))


def _verdict(ic_mean: float, bonferroni_p: float) -> str:
    if not math.isfinite(ic_mean):
        return "NA"
    if ic_mean > 0.05 and bonferroni_p < 0.05:
        return "STRONG"
    if ic_mean > 0.03 and bonferroni_p < 0.05:
        return "MODEST"
    if ic_mean > 0.01:
        return "WEAK"
    return "NOISE"


def _compute_factor_stats(
    panel: pd.DataFrame,
    prices: pd.DataFrame,
    factor_column: str,
    *,
    periods: tuple[int, ...],
    quantiles: int,
) -> dict | None:
    """Run alphalens for one factor column. Returns per-horizon stats or
    None on internal failure (factor undefined for whole panel etc.)."""
    if factor_column not in panel.columns:
        return None
    notnull = panel[factor_column].notna().sum()
    if notnull < 100:
        logger.warning(
            "Skipping factor=%s — only %d non-null observations.",
            factor_column, notnull,
        )
        return None

    from src.research.diagnostic_service import (
        _build_factor_series, _patch_alphalens_freq,
    )
    import alphalens as al

    _patch_alphalens_freq()

    factor = _build_factor_series(panel, factor_column, align_to_index=prices.index)
    if len(factor) < 100:
        return None

    try:
        clean = al.utils.get_clean_factor_and_forward_returns(
            factor=factor, prices=prices, quantiles=quantiles,
            periods=periods, max_loss=0.5,
        )
    except Exception as exc:  # noqa: BLE001
        # Alphalens raises on degenerate inputs (single quantile, etc.)
        # Mark factor as not-evaluable rather than erasing the whole run.
        logger.warning("alphalens failed for factor=%s: %s", factor_column, exc)
        return None

    ic = al.performance.factor_information_coefficient(clean)
    qr_mean, _ = al.performance.mean_return_by_quantile(clean)

    per_horizon: dict[str, dict] = {}
    for p in periods:
        col = f"{p}D"
        if col not in ic.columns:
            continue
        ic_series = ic[col].dropna()
        ic_mean = float(ic_series.mean()) if len(ic_series) else 0.0
        ic_std = float(ic_series.std()) if len(ic_series) > 1 else 0.0
        n_dates = int(len(ic_series))
        ic_ir = (ic_mean / ic_std) if ic_std > 0 else 0.0
        t_stat, p_val = _ic_t_p(ic_mean, ic_std, n_dates)
        if col in qr_mean.columns:
            top = float(qr_mean[col].iloc[-1])
            bot = float(qr_mean[col].iloc[0])
            spread_pct = (top - bot) * 100.0
        else:
            spread_pct = 0.0
        per_horizon[col] = {
            "ic_mean": ic_mean,
            "ic_std": ic_std,
            "ic_ir": ic_ir,
            "n_periods": n_dates,
            "t_stat": t_stat,
            "p_value": p_val,
            "top_minus_bottom_pct": spread_pct,
        }

    return {
        "factor": factor_column,
        "n_observations": int(len(clean)),
        "by_horizon": per_horizon,
    }


def _emit_markdown(
    *,
    output_path: Path,
    window: dict,
    universe: str,
    strategy: str,
    periods: tuple[int, ...],
    quantiles: int,
    per_factor: list[dict],
    bonferroni_k: int,
    ran_at: str,
    panel_rows: int,
) -> None:
    lines: list[str] = [
        f"# Analyzer IC Report — {strategy}",
        "",
        f"Generated {ran_at}.",
        "",
        f"- Window: {window['start']} → {window['end']}",
        f"- Universe: `{universe}`",
        f"- Strategy (for scoring): `{strategy}`",
        f"- Horizons: {', '.join(f'{p}D' for p in periods)} trading days",
        f"- Quantiles: {quantiles}",
        f"- Bonferroni k: {bonferroni_k}",
        f"- Panel rows: {panel_rows:,}",
        "",
        "## Interpretation",
        "",
        "- **IC mean** — Spearman rank correlation between the factor score "
        "and the forward return for that horizon. Cross-sectional retail "
        "factors are loud if > 0.03; > 0.05 is strong.",
        "- **IC IR** — IC mean / IC std across rebalance dates. > 0.5 = "
        "the signal is stable over time, not driven by one window.",
        "- **t-stat / Bonferroni-p** — t-test on the IC time series under "
        "null IC=0. Bonferroni adjusts for the seven analyzer tests; the "
        "composite is shown as control and is not Bonferroni-counted.",
        "- **Top–Bottom %** — top quintile mean forward return minus "
        "bottom quintile, in percent. Useful sanity check that the IC "
        "translates into actually-tradable spread.",
        "",
    ]

    for horizon in (f"{p}D" for p in periods):
        lines.append(f"## Horizon: {horizon}")
        lines.append("")
        lines.append("| Factor | IC mean | IC IR | t-stat | Bonferroni-p | "
                     "Top–Bottom % | Verdict |")
        lines.append("|---|---|---|---|---|---|---|")
        for entry in per_factor:
            stats = entry.get("by_horizon", {}).get(horizon)
            factor = entry["factor"]
            if stats is None:
                lines.append(f"| {factor} | n/a | n/a | n/a | n/a | n/a | NA |")
                continue
            ic_mean = stats["ic_mean"]
            ic_ir = stats["ic_ir"]
            t_stat = stats["t_stat"]
            p_val = stats["p_value"]
            bonf_p = (1.0 if factor == CONTROL_COLUMN
                      else _bonferroni(p_val, bonferroni_k))
            spread = stats["top_minus_bottom_pct"]
            verdict = _verdict(ic_mean, bonf_p) if factor != CONTROL_COLUMN \
                else _verdict(ic_mean, p_val)
            lines.append(
                f"| {factor} | {ic_mean:+.4f} | {ic_ir:+.2f} | "
                f"{t_stat:+.2f} | {bonf_p:.4f} | {spread:+.3f} | {verdict} |"
            )
        lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append("- IC is computed on the raw analyzer sub-score 0-100 "
                 "(not on the strategy-weighted contribution). This is "
                 "what we want — we're measuring whether the analyzer "
                 "carries information, separate from the question of how "
                 "much weight it should get.")
    lines.append("- alpha158 internally aggregates ~25 sub-factors into a "
                 "single 0-100 score. This report tests the aggregate "
                 "only. A separate per-factor breakdown would require "
                 "exposing the raw 25 columns from the analyzer.")
    lines.append("- Verdict thresholds are rough rules of thumb: STRONG "
                 "= IC>0.05 + significant, MODEST = IC>0.03 + significant, "
                 "WEAK = IC>0.01, NOISE = below. Bonferroni guards against "
                 "us declaring an analyzer real just because we tested 7.")
    lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Lazy heavy imports.
    from src.data.cache import DataCache
    from src.data.fetcher import DataFetcher
    from src.data.fundamentals import FundamentalsFetcher
    from src.backtest.engine import fetch_earnings_history
    from src.research.diagnostic_service import (
        build_score_panel, build_price_matrix,
    )

    config = Config()
    strategy = config.get_strategy(args.strategy)
    if strategy is None:
        logger.error("Strategy %s not found in strategies.yaml", args.strategy)
        return 2

    if args.universe == "russell_1000":
        tickers = config.get_russell_1000_tickers()
    else:
        logger.error("Unknown universe %s", args.universe)
        return 2

    if not tickers:
        logger.error(
            "Universe %s has no tickers. Run scripts/fetch_russell_1000.py "
            "first.", args.universe,
        )
        return 2

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    periods = tuple(int(x) for x in args.periods.split(",") if x.strip())

    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5,
        ),
    )
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    panel_cache_path = Path(args.panel_cache) if args.panel_cache else None
    panel: pd.DataFrame | None = None
    if panel_cache_path is not None and panel_cache_path.exists():
        logger.info("Reading cached score panel from %s", panel_cache_path)
        panel = pd.read_csv(panel_cache_path, parse_dates=["date"])
        if panel.empty:
            logger.warning("Cached panel is empty; rebuilding.")
            panel = None
    # Price matrix always needs to be rebuilt — it's small and cheap
    # compared to scoring, and the cached panel doesn't carry it.
    if panel is None:
        logger.info("Fetching %d ticker price histories...", len(tickers))
        price_data = fetcher.fetch_batch(tickers)
        fundamentals = fund_fetcher.fetch_batch(tickers)
        logger.info("Fetching earnings history...")
        earnings_history = fetch_earnings_history(list(price_data.keys()), workers=8)
        logger.info("Building score panel %s -> %s...", start.date(), end.date())
        panel = build_score_panel(
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
        if panel.empty:
            logger.error("Empty score panel; aborting.")
            return 4
        if panel_cache_path is not None:
            panel_cache_path.parent.mkdir(parents=True, exist_ok=True)
            panel.to_csv(panel_cache_path, index=False)
            logger.info("Wrote panel cache to %s", panel_cache_path)
    else:
        # Re-fetch price_data anyway for the price matrix (cache hits).
        logger.info("Fetching ticker price histories (for price matrix)...")
        price_data = fetcher.fetch_batch(tickers)
    logger.info("Score panel rows: %d", len(panel))

    logger.info("Building price matrix...")
    # Forward returns need bars past the panel's last date. Alphalens
    # drops period columns if too many rebalances lack their full
    # forward window — for a 42D horizon we need ~60 trading days =
    # ~90 calendar days of runway. Original 45 days truncated 21D.
    max_period_days = max(periods) if periods else 5
    runway_days = max(45, int(max_period_days * 2 + 14))
    prices = build_price_matrix(
        price_data, start, end + pd.Timedelta(days=runway_days),
    )
    if prices.empty:
        logger.error("Empty price matrix; aborting.")
        return 4

    # Drop columns that are constant across the panel — alphalens will
    # quintile-bucket fine but the IC test is meaningless.
    candidate_columns = list(ANALYZER_COLUMNS) + [CONTROL_COLUMN]
    surviving: list[str] = []
    for col in candidate_columns:
        if col not in panel.columns:
            logger.warning("Factor %s missing from panel — skipping.", col)
            continue
        if panel[col].nunique(dropna=True) < 2:
            logger.warning(
                "Factor %s is constant across panel — skipping.", col,
            )
            continue
        surviving.append(col)
    bonferroni_k = sum(1 for c in surviving if c in ANALYZER_COLUMNS)

    per_factor: list[dict] = []
    for col in surviving:
        logger.info("Computing IC for factor=%s ...", col)
        stats = _compute_factor_stats(
            panel, prices, col, periods=periods, quantiles=args.quantiles,
        )
        if stats is None:
            per_factor.append({"factor": col, "by_horizon": {}})
            continue
        per_factor.append(stats)

    ran_at = datetime.now(timezone.utc).isoformat()

    # Markdown report.
    out_md = Path(args.output)
    _emit_markdown(
        output_path=out_md,
        window={"start": str(start.date()), "end": str(end.date())},
        universe=args.universe,
        strategy=args.strategy,
        periods=periods,
        quantiles=args.quantiles,
        per_factor=per_factor,
        bonferroni_k=bonferroni_k,
        ran_at=ran_at,
        panel_rows=len(panel),
    )

    # JSON twin for downstream tooling.
    out_json = out_md.with_suffix(".json")
    payload = {
        "ran_at": ran_at,
        "universe": args.universe,
        "strategy": args.strategy,
        "window": {"start": str(start.date()), "end": str(end.date())},
        "periods": list(periods),
        "quantiles": args.quantiles,
        "bonferroni_k": bonferroni_k,
        "panel_rows": int(len(panel)),
        "per_factor": per_factor,
    }
    out_json.write_text(json.dumps(payload, indent=2, default=str),
                        encoding="utf-8")

    logger.info("Wrote %s + %s", out_md, out_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
