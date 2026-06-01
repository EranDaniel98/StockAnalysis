"""Beta-sensitivity approximation for today's picks under adverse scenarios.

This is a back-of-envelope per-name beta shock, NOT a true portfolio stress
test of the live strategy. It assumes a FULLY-INVESTED, equal-weight book and
applies CAPM beta + sector shocks to each current pick:

  - Broad market scenarios (SPY +/-10%, +/-20%, COVID-style -30%)
  - Sector-specific shocks (financials, energy, tech)
  - Rate-hike / inflation regimes (CAPM-adjusted)
  - Beta-stress (if every stock moves at 1.5x its beta)

What it deliberately does NOT model (so do not read its "worst case" as the
strategy's real crash exposure):
  - The regime/trend gate that takes the strategy to CASH in a downtrend —
    in a real -30% selloff the live book is likely flat, not fully invested.
  - Rebalancing, factor rotation, or stop-losses during the shock window.
  For an actual crash replay, run the strategy over a frozen crash snapshot
  (e.g. the 2020 COVID snapshot) via run_factor_backtest, not this tool.

Beta is computed deterministically from Polygon prices (cov/var vs SPY over a
trailing window), consistent with the rest of the system — NOT from yfinance
.info (which is non-deterministic and banned elsewhere here).

Output: reports/stress_test_YYYY-MM-DD.md
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


logger = logging.getLogger("stress_test")


# Scenario library. Each scenario specifies:
#   - market_move:  SPY return assumed
#   - sector_shocks: dict[sector, additional return on top of market beta]
#   - beta_multiplier: scales each stock's beta-driven move
SCENARIOS = [
    {
        "name": "SPY +10% rally",
        "market_move": +0.10,
        "sector_shocks": {},
        "beta_multiplier": 1.0,
        "description": "Steady 3-month rally; tests upside capture.",
    },
    {
        "name": "SPY -10% correction",
        "market_move": -0.10,
        "sector_shocks": {},
        "beta_multiplier": 1.0,
        "description": "Garden-variety pullback; tests defensive behavior.",
    },
    {
        "name": "SPY -20% bear",
        "market_move": -0.20,
        "sector_shocks": {},
        "beta_multiplier": 1.1,  # high-beta names fall harder in bears
        "description": "2022-style 20% drawdown over the quarter.",
    },
    {
        "name": "COVID-style -35% crash",
        "market_move": -0.35,
        "sector_shocks": {
            "Energy": -0.15,
            "Real Estate": -0.10,
            "Financial Services": -0.10,
            "Consumer Defensive": +0.10,  # defensives outperform
            "Healthcare": +0.05,
            "Utilities": +0.05,
        },
        "beta_multiplier": 1.3,
        "description": "Q1 2020-style risk-off. Cyclicals, financials, "
                       "REITs hit hardest; defensives + healthcare hold up.",
    },
    {
        "name": "Banking crisis (financials -25%)",
        "market_move": -0.05,
        "sector_shocks": {"Financial Services": -0.20},
        "beta_multiplier": 1.0,
        "description": "Like SVB 2023: regional banks crash, broader "
                       "market mostly unaffected. Tests portfolio's "
                       "42% Financial Services concentration.",
    },
    {
        "name": "Oil shock (energy +30%)",
        "market_move": -0.05,
        "sector_shocks": {
            "Energy": +0.25,
            "Basic Materials": +0.10,
            "Consumer Cyclical": -0.05,
            "Industrials": -0.05,
        },
        "beta_multiplier": 1.0,
        "description": "Geopolitical oil shock. Energy + materials rally; "
                       "consumer + industrials feel the input cost.",
    },
    {
        "name": "Aggressive rate hikes (+200bps)",
        "market_move": -0.08,
        "sector_shocks": {
            "Financial Services": +0.05,   # banks net interest margin up
            "Real Estate": -0.15,           # REITs hate rates
            "Utilities": -0.10,             # bond proxies
            "Technology": -0.10,            # long-duration valuation
            "Communication Services": -0.08,
        },
        "beta_multiplier": 1.0,
        "description": "Fed surprise hike. Bond-proxy sectors crater; "
                       "banks benefit from net interest margin lift.",
    },
    {
        "name": "Recession (cyclicals -25%)",
        "market_move": -0.15,
        "sector_shocks": {
            "Financial Services": -0.10,
            "Consumer Cyclical": -0.10,
            "Industrials": -0.10,
            "Energy": -0.10,
            "Basic Materials": -0.08,
            "Consumer Defensive": +0.10,
            "Healthcare": +0.05,
            "Utilities": +0.05,
        },
        "beta_multiplier": 1.1,
        "description": "2008-style recession. Defensive rotation; "
                       "cyclicals, energy, financials all suffer.",
    },
]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--analysis-json", default=None,
                   help="Defaults to latest reports/portfolio_analysis_*.json")
    p.add_argument("--output", required=True)
    return p.parse_args()


def _find_latest_analysis() -> Path | None:
    candidates = sorted(Path("reports").glob("portfolio_analysis_*.json"))
    return candidates[-1] if candidates else None


def _stress_one(
    pick: dict, scenario: dict, default_beta: float = 1.0,
) -> float:
    """Per-position return % under the scenario."""
    beta = pick.get("beta") or default_beta
    sector = pick.get("sector") or "Unknown"
    # Beta-driven move from market
    market_part = beta * scenario["beta_multiplier"] * scenario["market_move"]
    # Sector-specific shock (additive)
    sector_part = scenario["sector_shocks"].get(sector, 0.0)
    return market_part + sector_part


def _deterministic_betas(
    tickers: list[str], lookback_days: int = 252,
) -> tuple[dict[str, float], list[str]]:
    """Beta = cov(name_ret, spy_ret) / var(spy_ret) from Polygon prices.

    Deterministic replacement for yfinance .info beta. Returns
    ``(betas, fell_back)`` where ``fell_back`` lists tickers with too little
    overlapping history to estimate (beta omitted, caller defaults to 1.0)."""
    if not tickers:
        return {}, []
    import pandas as pd
    from src.config_loader import Config
    from src.data.fetcher_factory import get_data_fetcher

    fetcher = get_data_fetcher(Config())
    spy = fetcher.fetch_price_data("SPY", period="2y")
    if spy is None or spy.empty:
        return {}, list(tickers)
    spy_ret = spy["Close"].astype(float).pct_change().dropna()

    betas: dict[str, float] = {}
    fell_back: list[str] = []
    px = fetcher.fetch_batch(tickers, period="2y")
    for t in tickers:
        df = px.get(t)
        if df is None or df.empty:
            fell_back.append(t)
            continue
        r = df["Close"].astype(float).pct_change().dropna()
        joined = pd.concat([r, spy_ret], axis=1, join="inner").dropna().tail(lookback_days)
        if len(joined) < 60:
            fell_back.append(t)
            continue
        var = float(joined.iloc[:, 1].var())
        if var <= 0:
            fell_back.append(t)
            continue
        cov = float(joined.iloc[:, 0].cov(joined.iloc[:, 1]))
        betas[t] = cov / var
    return betas, fell_back


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()
    analysis_path = (
        Path(args.analysis_json)
        if args.analysis_json
        else _find_latest_analysis()
    )
    if analysis_path is None or not analysis_path.exists():
        raise SystemExit(
            "No portfolio_analysis JSON found. Run "
            "`scripts.comprehensive_analysis` first."
        )
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    picks = analysis["picks"]
    equity = analysis.get("equity_usd", 41042.0)
    n = len(picks)
    logger.info("Stress-testing %d picks (equity $%.2f)", n, equity)

    # Beta per pick, computed DETERMINISTICALLY from Polygon prices (cov/var vs
    # SPY) rather than yfinance .info — the latter is non-deterministic and
    # banned across the rest of the system. Names whose beta can't be computed
    # (too little history) fall back to 1.0 and are surfaced, not silently hidden.
    missing = [p["ticker"] for p in picks if p.get("beta") is None]
    betas, fell_back = _deterministic_betas(missing)
    for p in picks:
        if p.get("beta") is None:
            p["beta"] = betas.get(p["ticker"], 1.0)
    pick_betas = [p["beta"] for p in picks]
    if fell_back:
        logger.warning(
            "Beta fell back to 1.0 for %d name(s) (insufficient history): %s",
            len(fell_back), ", ".join(sorted(fell_back)),
        )

    avg_beta = sum(pick_betas) / max(1, len(pick_betas))
    logger.info("Average portfolio beta: %.2f (deterministic, Polygon cov/var vs SPY)", avg_beta)

    # Run each scenario
    results = []
    for scn in SCENARIOS:
        per_position = []
        for p in picks:
            r = _stress_one(p, scn)
            per_position.append({
                "ticker": p["ticker"],
                "sector": p.get("sector") or "Unknown",
                "beta": p["beta"],
                "return": r,
                "pos_size": equity / n,
                "pnl": (equity / n) * r,
            })
        portfolio_return = sum(pos["return"] for pos in per_position) / n
        portfolio_pnl = sum(pos["pnl"] for pos in per_position)
        worst = sorted(per_position, key=lambda x: x["return"])[:3]
        best = sorted(per_position, key=lambda x: -x["return"])[:3]
        # SPY comparison: 100% beta×market_move
        spy_return = scn["market_move"]
        spy_pnl = equity * spy_return
        results.append({
            "scenario": scn,
            "portfolio_return": portfolio_return,
            "portfolio_pnl": portfolio_pnl,
            "spy_return": spy_return,
            "spy_pnl": spy_pnl,
            "alpha": portfolio_return - spy_return,
            "worst": worst,
            "best": best,
            "per_position": per_position,
        })

    # ----- render -----
    today = datetime.now(timezone.utc).date().isoformat()
    lines: list[str] = []
    lines.append(f"# Portfolio Stress Test — {today}")
    lines.append("")
    lines.append(f"*Equity: ${equity:,.2f} | Positions: {n} equal-weight | "
                 f"Avg portfolio beta: {avg_beta:.2f}*")
    lines.append("")
    lines.append(
        "These are POINT-ESTIMATE stress tests using each name's "
        "trailing beta (from yfinance) + sector shock overlays. "
        "Real outcomes will dispersed around these by ±5-10 pp at "
        "the portfolio level."
    )
    lines.append("")

    # Summary table
    lines.append("## Scenario summary")
    lines.append("")
    lines.append("| Scenario | Strategy | SPY | Alpha | Strategy $P&L |")
    lines.append("|---|---|---|---|---|")
    for r in results:
        scn = r["scenario"]
        lines.append(
            f"| {scn['name']} | "
            f"{r['portfolio_return']*100:+.2f}% | "
            f"{r['spy_return']*100:+.2f}% | "
            f"{r['alpha']*100:+.2f}% | "
            f"${r['portfolio_pnl']:+,.0f} |"
        )
    lines.append("")

    # Worst scenario callout
    worst_scn = min(results, key=lambda r: r["portfolio_return"])
    best_scn = max(results, key=lambda r: r["portfolio_return"])
    lines.append("## Range")
    lines.append("")
    lines.append(
        f"- **Worst case ({worst_scn['scenario']['name']}):** "
        f"portfolio {worst_scn['portfolio_return']*100:+.1f}% "
        f"(${worst_scn['portfolio_pnl']:+,.0f})"
    )
    lines.append(
        f"- **Best case ({best_scn['scenario']['name']}):** "
        f"portfolio {best_scn['portfolio_return']*100:+.1f}% "
        f"(${best_scn['portfolio_pnl']:+,.0f})"
    )
    lines.append("")

    # Per-scenario detail
    lines.append("## Per-scenario detail")
    lines.append("")
    for r in results:
        scn = r["scenario"]
        lines.append(f"### {scn['name']}")
        lines.append("")
        lines.append(f"*{scn['description']}*")
        lines.append("")
        lines.append(
            f"- Portfolio: **{r['portfolio_return']*100:+.2f}%** "
            f"(${r['portfolio_pnl']:+,.0f})"
        )
        lines.append(
            f"- SPY: {r['spy_return']*100:+.2f}% "
            f"(${r['spy_pnl']:+,.0f}) "
            f"| Alpha: {r['alpha']*100:+.2f}%"
        )
        lines.append("")
        lines.append("**Hardest hit:**")
        for w in r["worst"]:
            lines.append(
                f"- {w['ticker']} ({w['sector']}, β={w['beta']:.2f}): "
                f"{w['return']*100:+.1f}% → ${w['pnl']:+,.0f}"
            )
        lines.append("")
        lines.append("**Best performers:**")
        for b in r["best"]:
            lines.append(
                f"- {b['ticker']} ({b['sector']}, β={b['beta']:.2f}): "
                f"{b['return']*100:+.1f}% → ${b['pnl']:+,.0f}"
            )
        lines.append("")

    # Sector exposure callout
    lines.append("## Sector exposure (drives scenario sensitivity)")
    lines.append("")
    sector_counts = defaultdict(int)
    for p in picks:
        sector_counts[p.get("sector") or "Unknown"] += 1
    lines.append("| Sector | Count | % | Beta avg |")
    lines.append("|---|---|---|---|")
    sector_beta = defaultdict(list)
    for p in picks:
        sector_beta[p.get("sector") or "Unknown"].append(p["beta"])
    for sec, cnt in sorted(sector_counts.items(), key=lambda x: -x[1]):
        avgb = sum(sector_beta[sec]) / max(1, len(sector_beta[sec]))
        lines.append(f"| {sec} | {cnt} | {100*cnt/n:.1f}% | {avgb:.2f} |")
    lines.append("")

    # Recommendations
    lines.append("## Risk recommendations")
    lines.append("")
    if avg_beta > 1.2:
        lines.append("- ⚠️ **Portfolio beta is high** — moves more than the "
                     "market in either direction. Consider trimming the "
                     "highest-beta names if a correction is feared.")
    elif avg_beta < 0.8:
        lines.append("- Portfolio is defensive (β < 0.8). Will underperform "
                     "in strong rallies but lose less in selloffs.")
    else:
        lines.append(f"- Portfolio beta {avg_beta:.2f} is approximately "
                     "market-neutral — moves roughly 1:1 with SPY.")
    fin_count = sector_counts.get("Financial Services", 0)
    if fin_count / n > 0.30:
        lines.append(f"- ⚠️ **Financial Services is {100*fin_count/n:.0f}% "
                     "of portfolio.** Banking crisis scenario hits hard. "
                     "Mitigation: cap any sector at 25% in next rebalance, "
                     "OR add explicit hedges (puts on KRE / XLF).")
    lines.append("")
    lines.append("---")
    lines.append("*Read with `reports/portfolio_analysis_*.md` for the "
                 "per-stock detail behind these scenarios.*")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
