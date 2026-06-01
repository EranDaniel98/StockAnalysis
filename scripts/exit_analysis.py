"""Exit-analysis report for current Alpaca PAPER positions.

For every position currently held that is NOT in today's top-N
factor picks, produce a clear, opinionated SELL recommendation:

  - Current position value + unrealized P&L
  - Why the position is being closed (no longer in top-N composite)
  - Where the name now ranks (out of 480) so we can quantify the drift
  - Suggested exit method (market vs limit) and price
  - Tax-loss-harvest note (if loss > 5%)
  - Earnings-blackout warning (don't sell into a near-term report)

Also flags any held names that ARE in today's picks (so they should
be KEPT or RIGHT-SIZED to the equal-weight target).

Output: reports/exit_plan_YYYY-MM-DD.md
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

logger = logging.getLogger("exit_analysis")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--picks-date", default=None)
    p.add_argument("--picks-dir", default="data/daily_picks")
    p.add_argument("--output", required=True)
    return p.parse_args()


def _load_picks(picks_dir: str, date_str: str | None) -> dict:
    if date_str is None:
        date_str = datetime.now(timezone.utc).date().isoformat()
    path = Path(picks_dir) / f"{date_str}.json"
    if not path.exists():
        raise SystemExit(f"No picks file at {path}.")
    return json.loads(path.read_text(encoding="utf-8"))


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


def _fetch_earnings(tickers: list[str]) -> dict[str, int]:
    """Days until next earnings per ticker. Empty for tickers without dates."""
    from src.factors.earnings_cache import load_next_earnings_dates

    today = pd.Timestamp.utcnow().tz_localize(None)
    next_dates = load_next_earnings_dates(tickers, as_of=today)
    return {t: max(0, (d - today).days) for t, d in next_dates.items()}


def _composite_rank_for(ticker: str, universe_ranks: list[dict]) -> int | None:
    """Where does the ticker rank in the FULL composite (not just top-N)?"""
    for r in universe_ranks:
        if r["ticker"] == ticker:
            return int(r["rank"])
    return None


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()
    payload = _load_picks(args.picks_dir, args.picks_date)
    picks = payload["picks"]
    pick_set = {p["ticker"] for p in picks}
    as_of = payload["as_of"]

    # Connect to Alpaca PAPER to get current positions.
    from src.config_loader import Config
    from src.execution.alpaca import AlpacaClient
    from src.execution.safety_gates import TradingSafetyGate
    client = AlpacaClient(safety_gate=TradingSafetyGate.from_config(Config()))
    acct = client.get_account()
    equity = float(acct.get("equity", 0.0) or 0.0)
    positions = client.get_positions()
    logger.info("Paper account: equity=$%.2f, %d positions",
                equity, len(positions))

    # Bucket positions: those in today's picks (KEEP/RESIZE) vs not (EXIT).
    keep = [p for p in positions if p["ticker"] in pick_set]
    exit_list = [p for p in positions if p["ticker"] not in pick_set]
    logger.info("KEEP/RESIZE: %d | EXIT: %d", len(keep), len(exit_list))

    # Refresh quotes (Alpaca's current_price is a mark; cross-check with yf).
    exit_tickers = [p["ticker"] for p in exit_list]
    fresh = _fetch_quotes(exit_tickers)
    logger.info("Refreshed quotes for %d/%d exit tickers",
                len(fresh), len(exit_tickers))

    # Earnings windows for exit names (so we don't sell into a beat).
    logger.info("Checking earnings calendars for exit names...")
    days_to_earn = _fetch_earnings(exit_tickers)

    # ---- render ----
    lines: list[str] = []
    lines.append(f"# Paper Account Exit Plan — {as_of}")
    lines.append("")
    lines.append(f"**Account:** Alpaca PAPER | "
                 f"**Equity:** ${equity:,.2f} | "
                 f"**Positions:** {len(positions)}")
    lines.append("")
    lines.append(f"Today's strategy (`{payload.get('strategy', 'composite')}`) selected {len(picks)} "
                 f"names. The account holds {len(positions)} positions — "
                 f"{len(keep)} overlap with the new target set, "
                 f"{len(exit_list)} do not and should be CLOSED.")
    lines.append("")

    # KEEP section
    lines.append("## ✅ Keep / Resize")
    lines.append("")
    if keep:
        target_per_pos = equity * 0.98 / max(1, len(picks))
        lines.append("Names already in today's top-24. Right-size each to "
                     f"~${target_per_pos:,.2f} (equal-weight target).")
        lines.append("")
        lines.append("| Ticker | Shares | Price | Mkt Value | P&L | Action |")
        lines.append("|---|---|---|---|---|---|")
        for p in keep:
            shares = int(float(p["shares"]))
            px = float(p.get("current_price") or 0.0)
            mv = float(p.get("market_value") or 0.0)
            pl = float(p.get("unrealized_pnl") or 0.0)
            pl_pct = float(p.get("unrealized_pnl_pct") or 0.0)
            target_shares = int(target_per_pos // px) if px > 0 else 0
            delta = target_shares - shares
            if delta > 0:
                action = f"BUY {delta} more"
            elif delta < 0:
                action = f"TRIM {-delta} shares"
            else:
                action = "HOLD as-is"
            lines.append(
                f"| {p['ticker']} | {shares} | ${px:,.2f} | ${mv:,.2f} | "
                f"${pl:+,.2f} ({pl_pct:+.1f}%) | **{action}** |"
            )
    else:
        lines.append("_(none — every current position is being exited)_")
    lines.append("")

    # EXIT section
    lines.append("## 🟥 Exit (close completely)")
    lines.append("")
    lines.append(f"{len(exit_list)} positions to liquidate. These names are "
                 "no longer in the top-5% composite ranking — the factor "
                 "evidence that justified the position is gone. Hold "
                 "duration is ended.")
    lines.append("")

    lines.append("| # | Ticker | Shares | Cost | Now | Mkt Value | P&L | Days→Earn | Action |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    total_proceeds = 0.0
    total_pl = 0.0
    blackout_exits = []
    loss_exits = []
    for i, p in enumerate(exit_list, 1):
        t = p["ticker"]
        shares = int(float(p["shares"]))
        cost = float(p.get("avg_price") or 0.0)
        px = float(fresh.get(t) or p.get("current_price") or 0.0)
        mv = shares * px
        pl = (px - cost) * shares
        pl_pct = ((px / cost) - 1) * 100 if cost > 0 else 0.0
        total_proceeds += mv
        total_pl += pl
        d2e = days_to_earn.get(t)
        d2e_str = f"{d2e}d" if d2e is not None else "—"
        # Action: usually market sell. Edge cases:
        # - earnings in <5 days → consider waiting (we lose factor edge
        #   but earnings can flip the price)
        # - >5% loss → mention tax-loss-harvest
        if d2e is not None and d2e <= 5:
            action = f"⚠️ EARN-BLACKOUT, wait {d2e+1}d then market sell"
            blackout_exits.append(t)
        else:
            action = "MARKET SELL"
        if pl_pct < -5:
            action += " (tax-loss)"
            loss_exits.append((t, pl_pct))
        lines.append(
            f"| {i} | {t} | {shares} | ${cost:,.2f} | ${px:,.2f} | "
            f"${mv:,.2f} | ${pl:+,.2f} ({pl_pct:+.1f}%) | {d2e_str} | "
            f"**{action}** |"
        )
    lines.append("")
    lines.append(f"**Exit summary:** liquidating ${total_proceeds:,.2f} of stock, "
                 f"realizing P&L of ${total_pl:+,.2f}.")
    if loss_exits:
        loss_str = ", ".join(f"{t}({pct:.1f}%)" for t, pct in loss_exits)
        lines.append(f"Tax-loss harvest candidates: {loss_str}")
    if blackout_exits:
        lines.append(f"⚠️ Delay these for post-earnings: {', '.join(blackout_exits)}")
    lines.append("")

    # Execution order
    lines.append("## Execution sequence")
    lines.append("")
    lines.append("1. **SELLs first** (clear ~${:.0f} cash):".format(total_proceeds))
    lines.append("   - All EXIT names except earnings-blackout candidates")
    lines.append("   - Submit as market orders at next open")
    lines.append("2. **TRIMs** for any KEEP names that are overweight")
    lines.append("3. **BUYs** for new picks not yet held:")
    lines.append("   - 24 names from today's picks file minus the {} already held".format(len(keep)))
    lines.append("   - Equal-weight market orders at next open")
    lines.append("4. **Delayed actions** post-earnings for blackout names")
    lines.append("")

    # Capacity check
    needed = (equity * 0.98) - sum(
        float(p.get("market_value") or 0.0) for p in keep
    )
    lines.append("## Capacity check")
    lines.append("")
    lines.append(
        f"- Equity available for new positions after sells + keeps: "
        f"~${needed:,.2f}"
    )
    lines.append(
        f"- New positions needed: {len(picks) - len(keep)}"
    )
    if len(picks) - len(keep) > 0:
        lines.append(
            f"- Per new position: ~${needed/(len(picks) - len(keep)):,.2f}"
        )
    lines.append("")
    lines.append(
        f"Refer to `reports/portfolio_analysis_{as_of.replace('-', '_')}.md` "
        "for the per-stock entry plan on the new buys."
    )
    lines.append("")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
