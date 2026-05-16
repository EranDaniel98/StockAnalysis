"""One-page morning briefing.

Consolidates today's picks, current paper positions, expected
portfolio P&L, and the key actions into a tight executive summary.
This is the document you read FIRST every morning; the deeper
comprehensive_analysis.md is for when you need the per-stock detail.

Reads:
  - data/daily_picks/YYYY-MM-DD.json (today's composite picks)
  - reports/portfolio_analysis_YYYY-MM-DD.json (the rich analysis)
  - reports/exit_plan_YYYY-MM-DD.md (parsed for action counts)
  - Alpaca paper account (live equity + positions)

Writes:
  - reports/morning_briefing_YYYY-MM-DD.md
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("morning_briefing")


def _money(v: float | None) -> str:
    if v is None:
        return "—"
    return f"${v:,.2f}"


def _pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:+.2f}%"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--picks-date", default=None)
    p.add_argument("--picks-dir", default="data/daily_picks")
    p.add_argument("--analysis-json",
                   default=None,
                   help="Path to portfolio_analysis_YYYY-MM-DD.json")
    p.add_argument("--output", required=True)
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()
    date_str = args.picks_date or datetime.now(timezone.utc).date().isoformat()

    picks_json = Path(args.picks_dir) / f"{date_str}.json"
    if not picks_json.exists():
        raise SystemExit(f"Missing picks file: {picks_json}")
    picks = json.loads(picks_json.read_text(encoding="utf-8"))

    # Analysis JSON: caller may pass path explicitly, else try both
    # underscored and hyphenated date formats (we've used both).
    analysis = None
    if args.analysis_json:
        ap = Path(args.analysis_json)
        if ap.exists():
            analysis = json.loads(ap.read_text(encoding="utf-8"))
    else:
        for date_variant in (date_str.replace("-", "_"), date_str):
            ap = Path(f"reports/portfolio_analysis_{date_variant}.json")
            if ap.exists():
                analysis = json.loads(ap.read_text(encoding="utf-8"))
                break

    # Get Alpaca account state
    from src.config_loader import Config
    from src.execution.alpaca import AlpacaClient
    from src.execution.safety_gates import TradingSafetyGate
    try:
        client = AlpacaClient(safety_gate=TradingSafetyGate.from_config(Config()))
        acct = client.get_account()
        equity = float(acct.get("equity", 0.0) or 0.0)
        cash = float(acct.get("cash", 0.0) or 0.0)
        positions = client.get_positions()
    except Exception as e:  # noqa: BLE001
        logger.warning("Alpaca unavailable: %s", e)
        equity, cash, positions = 0.0, 0.0, []

    pick_set = {p["ticker"] for p in picks["picks"]}
    pos_set = {p["ticker"] for p in positions}
    keep = pos_set & pick_set
    exit_names = pos_set - pick_set
    new_buys = pick_set - pos_set

    # Unrealized P&L on current holdings
    total_pl = sum(float(p.get("unrealized_pnl") or 0.0) for p in positions)
    pl_pct = (total_pl / equity * 100) if equity > 0 else 0.0

    # Sector breakdown from analysis JSON if available
    sector_counts = Counter()
    if analysis:
        for p in analysis["picks"]:
            sector_counts[p.get("sector") or "Unknown"] += 1
    largest_sector = sector_counts.most_common(1)[0] if sector_counts else (None, 0)

    # Expected portfolio P&L over the quarter
    expected_p25 = expected_p50 = expected_p75 = None
    if analysis:
        n = analysis["n_positions"]
        med = analysis["expected_per_pick_pct"]["median"]
        p75 = analysis["expected_per_pick_pct"]["p75"]
        p25 = analysis["expected_per_pick_pct"]["p25"]
        # Portfolio expected return = sum-of-positions (equal weight) * per-pick
        expected_p50 = equity * (med / 100.0)
        expected_p75 = equity * (p75 / 100.0)
        expected_p25 = equity * (p25 / 100.0)

    # Earnings calendar collisions
    upcoming_earnings = []
    blackout_earnings = []
    if analysis:
        for p in analysis["picks"]:
            d2e = p.get("days_to_earnings")
            if d2e is not None and d2e <= 5:
                blackout_earnings.append((p["ticker"], d2e))
            elif d2e is not None and d2e <= 14:
                upcoming_earnings.append((p["ticker"], d2e))

    # Top 5 picks (by composite rank)
    top5 = picks["picks"][:5]

    # Render
    lines: list[str] = []
    lines.append(f"# Morning Briefing — {date_str}")
    lines.append("")
    lines.append(f"*Strategy:* `composite_d05_r63` (top 5% factor blend, quarterly rebalance)")
    lines.append("")

    # ---- ACCOUNT ----
    lines.append("## Account snapshot")
    lines.append("")
    lines.append(f"- Paper equity: **{_money(equity)}** | "
                 f"cash: {_money(cash)} | "
                 f"positions: {len(positions)}")
    lines.append(f"- Unrealized P&L: {_money(total_pl)} ({pl_pct:+.2f}%)")
    if analysis:
        lines.append(f"- Per-position target size: "
                     f"{_money(equity * 0.98 / max(1, len(picks['picks'])))} "
                     f"({100/max(1,len(picks['picks'])):.1f}% of equity)")
    lines.append("")

    # ---- ACTION TABLE ----
    lines.append("## Today's actions")
    lines.append("")
    lines.append("| Action | Count | Notional |")
    lines.append("|---|---|---|")
    keep_val = sum(float(p.get("market_value") or 0.0)
                   for p in positions if p["ticker"] in keep)
    exit_val = sum(float(p.get("market_value") or 0.0)
                   for p in positions if p["ticker"] in exit_names)
    new_buy_val = equity * 0.98 - keep_val
    if new_buy_val < 0:
        new_buy_val = 0
    lines.append(f"| 🟢 NEW BUYS | {len(new_buys)} | ~{_money(new_buy_val)} (post-sells) |")
    lines.append(f"| 🟡 KEEP / RESIZE | {len(keep)} | {_money(keep_val)} (mtm) |")
    lines.append(f"| 🔴 EXIT | {len(exit_names)} | {_money(exit_val)} (mtm) |")
    lines.append("")
    if exit_names:
        lines.append("**EXIT list:** " + ", ".join(sorted(exit_names)))
    if new_buys:
        lines.append("**NEW BUY list:** " + ", ".join(sorted(new_buys)))
    if keep:
        lines.append("**KEEP:** " + ", ".join(sorted(keep)))
    lines.append("")

    # ---- TOP 5 PICKS ----
    lines.append("## Top 5 picks (strongest composite z)")
    lines.append("")
    lines.append("| Rank | Ticker | z-score | Why |")
    lines.append("|---|---|---|---|")
    for p in top5:
        signals = []
        if p.get("mom_rank") and p["mom_rank"] <= 50:
            signals.append("MOM")
        if p.get("qual_rank") and p["qual_rank"] <= 50:
            signals.append("QUAL")
        if p.get("val_rank") and p["val_rank"] <= 50:
            signals.append("VAL")
        why = "+".join(signals) if signals else "blended"
        lines.append(f"| #{p['rank']} | **{p['ticker']}** | "
                     f"{p['z_score']:+.2f} | {why} |")
    lines.append("")

    # ---- SECTOR + RISK ----
    if sector_counts:
        n = sum(sector_counts.values())
        sec_str = " | ".join(
            f"{s} {c} ({100*c/n:.0f}%)"
            for s, c in sector_counts.most_common(4)
        )
        lines.append(f"## Sector exposure")
        lines.append("")
        lines.append(f"- {sec_str}")
        if largest_sector[1] / max(1, n) > 0.30:
            lines.append(f"- ⚠️ **{largest_sector[0]} concentration > 30%** — "
                         "single-sector drawdown will hit harder than SPY")
        lines.append("")

    # ---- RISKS ----
    if blackout_earnings or upcoming_earnings:
        lines.append("## Earnings calendar overlap")
        lines.append("")
        if blackout_earnings:
            bs = ", ".join(f"{t}({d}d)" for t, d in blackout_earnings)
            lines.append(f"- ⚠️ **Blackout (≤5d):** {bs} — delay entry until after report")
        if upcoming_earnings:
            us = ", ".join(f"{t}({d}d)" for t, d in upcoming_earnings)
            lines.append(f"- Within 2 weeks: {us}")
        lines.append("")

    # ---- EXPECTED P&L ----
    if expected_p50 is not None:
        lines.append("## Expected portfolio P&L (63 trading days, from backtest)")
        lines.append("")
        lines.append(f"- **Base case (median):** {_money(expected_p50)} "
                     f"({analysis['expected_per_pick_pct']['median']:+.1f}%)")
        lines.append(f"- Bull case (p75): {_money(expected_p75)} "
                     f"({analysis['expected_per_pick_pct']['p75']:+.1f}%)")
        lines.append(f"- Bear case (p25): {_money(expected_p25)} "
                     f"({analysis['expected_per_pick_pct']['p25']:+.1f}%)")
        lines.append("")
        lines.append("**Honest caveat:** these are backtest per-pick distributions on a "
                     "63-day hold, scaled to the equity. Real-world drift is real. "
                     "Backtest 3-window avg alpha vs SPY: **+1.88%/yr**.")
        lines.append("")

    # ---- DEEPER LINKS ----
    lines.append("## Drill-down")
    lines.append("")
    lines.append(f"- **Per-stock plans:** `reports/portfolio_analysis_{date_str.replace('-', '_')}.md`")
    lines.append(f"- **Exit plan:** `reports/exit_plan_{date_str.replace('-', '_')}.md`")
    lines.append(f"- **Raw picks JSON:** `data/daily_picks/{date_str}.json`")
    lines.append(f"- **Strategy verdict:** `reports/factor_strategy_report_2026_05_16.md`")
    lines.append(f"- **User guide:** `FACTOR_STRATEGY.md`")
    lines.append("")

    # ---- WORKFLOW ----
    lines.append("## Workflow today")
    lines.append("")
    lines.append("1. Review this briefing")
    lines.append(f"2. Read per-stock plans for new buys ({len(new_buys)} names)")
    if exit_names:
        lines.append(f"3. Check exit plan for the {len(exit_names)} sells — note "
                     "any earnings-blackout delays")
    lines.append("4. Adjust `config/settings.yaml` safety gates if needed "
                 "(`max_open_positions`, `max_order_value_usd`)")
    lines.append("5. Dry-run paper trade: "
                 "`uv run python -m scripts.paper_trade_factor_picks "
                 f"--picks-date {date_str}`")
    lines.append("6. Execute (after sanity-checking the plan):"
                 " `... --execute`")
    lines.append("")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
