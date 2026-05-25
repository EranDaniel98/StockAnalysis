"""Position monitor — checks current paper positions vs entry-time levels.

Reads the most recent execution log (from paper_trade_factor_picks)
to know what the entry price + stop + target were for each position,
then compares against current quotes. Flags:

  - 🚨 STOP HIT — current ≤ stop_loss (you should be out)
  - 🟢 TARGET HIT — current ≥ target (consider taking profit early)
  - ⚠️ NEAR STOP — within 2% of stop loss
  - ⚠️ NEAR TARGET — within 2% of target
  - HOLDING — in the middle, do nothing

If no execution log exists, falls back to inferring entry from
Alpaca's avg_entry_price (less precise — Alpaca's average doesn't
remember the recommendation context).

Output: reports/position_monitor_YYYY-MM-DD.md + stdout summary
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("position_monitor")

# Same defaults as the comprehensive analyzer's trading plan.
ATR_STOP_MULTIPLE = 2.5
MIN_STOP_PCT = 0.05
MAX_STOP_PCT = 0.12
PER_PICK_TARGET_PCT = 8.0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--analysis-json", default=None,
                   help="reports/portfolio_analysis_YYYY_MM_DD.json — "
                        "the strategy's recommended levels.")
    p.add_argument("--output", default=None,
                   help="Markdown output path.")
    return p.parse_args()


def _find_latest_analysis() -> Path | None:
    """The most recent reports/portfolio_analysis_*.json."""
    candidates = sorted(Path("reports").glob("portfolio_analysis_*.json"))
    return candidates[-1] if candidates else None


def _fetch_quotes(tickers: list[str]) -> dict[str, float]:
    if not tickers:
        return {}
    from src.config_loader import Config
    from src.data.cache import DataCache
    from src.data.fetcher_factory import get_data_fetcher

    config = Config()
    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5,
        ),
    )
    fetcher = get_data_fetcher(config, cache)
    raw = fetcher.fetch_batch(tickers)
    out: dict[str, float] = {}
    for t, df in raw.items():
        if df is None or df.empty or "Close" not in df.columns:
            continue
        s = df["Close"].dropna()
        if s.empty:
            continue
        out[t] = float(s.iloc[-1])
    return out


def _classify(
    current: float, entry: float, stop: float, target: float,
) -> tuple[str, str]:
    """Returns (status, color_emoji)."""
    if current <= stop:
        return "STOP HIT", "🚨"
    if current >= target:
        return "TARGET HIT", "🟢"
    if current <= stop * 1.02:
        return "NEAR STOP", "⚠️"
    if current >= target * 0.98:
        return "NEAR TARGET", "⚠️"
    return "HOLDING", "✓"


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
            "No analysis JSON found. Run "
            "`scripts.comprehensive_analysis` first."
        )
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    plan_by_ticker = {p["ticker"]: p for p in analysis["picks"]}
    logger.info("Loaded recommended levels from %s (%d picks)",
                analysis_path.name, len(plan_by_ticker))

    # Connect to Alpaca PAPER
    from src.config_loader import Config
    from src.execution.alpaca import AlpacaClient
    from src.execution.safety_gates import TradingSafetyGate
    client = AlpacaClient(safety_gate=TradingSafetyGate.from_config(Config()))
    positions = client.get_positions()
    if not positions:
        logger.warning("No paper positions held.")
        return 0
    pos_tickers = [p["ticker"] for p in positions]
    logger.info("Paper account holds %d positions", len(positions))

    # Refresh quotes for everything we hold (Alpaca's mark is also OK).
    fresh = _fetch_quotes(pos_tickers)

    rows: list[dict] = []
    for p in positions:
        t = p["ticker"]
        current = float(fresh.get(t) or p.get("current_price") or 0.0)
        avg_entry = float(p.get("avg_price") or 0.0)
        shares = int(float(p["shares"]))
        market_value = shares * current
        pl = (current - avg_entry) * shares
        pl_pct = (current / avg_entry - 1) * 100 if avg_entry > 0 else 0.0

        # Get strategy-recommended stop + target
        plan = plan_by_ticker.get(t)
        if plan:
            stop = float(plan.get("stop_loss") or 0)
            target = float(plan.get("target") or 0)
            entry_rec = float(plan.get("entry_price") or current)
            source = "strategy"
        else:
            # Fallback: derive stop/target from average entry, fixed pct
            stop = avg_entry * (1 - 0.08)
            target = avg_entry * (1 + PER_PICK_TARGET_PCT / 100)
            entry_rec = avg_entry
            source = "fallback_8pct"

        status, emoji = _classify(current, avg_entry, stop, target)
        rows.append({
            "ticker": t,
            "shares": shares,
            "avg_entry": avg_entry,
            "current": current,
            "market_value": market_value,
            "pl": pl,
            "pl_pct": pl_pct,
            "stop": stop,
            "target": target,
            "status": status,
            "emoji": emoji,
            "in_strategy": t in plan_by_ticker,
            "source": source,
        })

    rows.sort(key=lambda r: (r["status"] != "STOP HIT",
                              r["status"] != "TARGET HIT",
                              -r["pl_pct"]))

    # Counts
    n_stop = sum(1 for r in rows if r["status"] == "STOP HIT")
    n_target = sum(1 for r in rows if r["status"] == "TARGET HIT")
    n_near_stop = sum(1 for r in rows if r["status"] == "NEAR STOP")
    n_near_target = sum(1 for r in rows if r["status"] == "NEAR TARGET")
    n_holding = sum(1 for r in rows if r["status"] == "HOLDING")
    n_off_strategy = sum(1 for r in rows if not r["in_strategy"])

    lines: list[str] = []
    today = datetime.now(timezone.utc).date().isoformat()
    lines.append(f"# Position Monitor — {today}")
    lines.append("")
    lines.append(f"*Recommended levels source: `{analysis_path.name}`*")
    lines.append("")
    lines.append(f"**Summary:** {len(rows)} positions monitored.")
    if n_stop:
        lines.append(f"- 🚨 **{n_stop} STOPPED OUT** — should already be closed")
    if n_target:
        lines.append(f"- 🟢 **{n_target} HIT TARGET** — consider profit-take")
    if n_near_stop:
        lines.append(f"- ⚠️ {n_near_stop} within 2% of stop loss")
    if n_near_target:
        lines.append(f"- ⚠️ {n_near_target} within 2% of target")
    if n_holding:
        lines.append(f"- ✓ {n_holding} holding in the middle")
    if n_off_strategy:
        lines.append(f"- 📋 {n_off_strategy} positions NOT in current strategy "
                     "picks (entry recs unavailable; using fallback 8% bands)")
    lines.append("")

    lines.append("## Per-position status")
    lines.append("")
    lines.append("| Status | Ticker | Sh | Entry | Now | Stop | Target | P&L | Notes |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        notes = []
        if not r["in_strategy"]:
            notes.append("not in strategy")
        if r["source"] == "fallback_8pct":
            notes.append("fallback stop/target")
        notes_str = "; ".join(notes) or "—"
        lines.append(
            f"| {r['emoji']} **{r['status']}** | {r['ticker']} | {r['shares']} | "
            f"${r['avg_entry']:.2f} | ${r['current']:.2f} | "
            f"${r['stop']:.2f} | ${r['target']:.2f} | "
            f"${r['pl']:+,.2f} ({r['pl_pct']:+.1f}%) | {notes_str} |"
        )
    lines.append("")

    if n_stop or n_target:
        lines.append("## Recommended actions")
        lines.append("")
        for r in rows:
            if r["status"] == "STOP HIT":
                lines.append(
                    f"- **SELL {r['ticker']}** ({r['shares']} sh @ "
                    f"~${r['current']:.2f}) — stopped out at "
                    f"${r['stop']:.2f}, current ${r['current']:.2f}. "
                    f"Realized P&L ${r['pl']:+,.2f}."
                )
            elif r["status"] == "TARGET HIT":
                lines.append(
                    f"- **CONSIDER SELL {r['ticker']}** ({r['shares']} sh "
                    f"@ ~${r['current']:.2f}) — hit target ${r['target']:.2f}. "
                    f"Profit-take ${r['pl']:+,.2f}, OR hold until quarterly "
                    f"rebalance for further upside."
                )
        lines.append("")
    else:
        lines.append("## Recommended actions")
        lines.append("")
        lines.append(
            "**No urgent action.** All positions are between stop and target."
        )
        lines.append("")

    md = "\n".join(lines)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    print(md)

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = Path(f"reports/position_monitor_{today.replace('-', '_')}.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    logger.info("Wrote %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
