"""
Reconcile Alpaca order history with our recommendation log,
then compute a calibration report:

  Does the composite_score actually predict realized returns?
  We bucket closed trades by score and show win rate / avg return per bucket.

If score bucket 70+ has materially higher win rate and avg return than 50-59,
the system has predictive power. If they're flat, the scoring is noise.
"""

import logging
from datetime import datetime, timezone
from collections import defaultdict

from rich.table import Table
from rich.panel import Panel
from rich import box

from src.execution.alpaca import AlpacaClient, AlpacaClientError
from src.execution.paper_db import PaperDB
from src.presentation.cli.cli_output import console

logger = logging.getLogger(__name__)


SCORE_BUCKETS = [
    ("<50",   0,   50),
    ("50-59", 50,  60),
    ("60-69", 60,  70),
    ("70-79", 70,  80),
    ("80+",   80,  101),
]


def run_paper_evaluate(config, args):
    """Entry point for `paper evaluate`."""
    days = getattr(args, "days", None) or 90

    console.print(f"\n[bold cyan]Paper trade calibration[/bold cyan]")
    console.print(f"  Reconciliation window: last {days} days\n")

    try:
        client = AlpacaClient()
    except AlpacaClientError as e:
        console.print(f"[red]Alpaca: {e}[/red]")
        return

    db = PaperDB()
    try:
        new_trades = _reconcile_closed_trades(client, db, days)
        console.print(f"  Reconciled [bold]{new_trades}[/bold] newly-closed trades\n")

        trades = db.get_all_trades()
        counts = db.get_summary_counts()

        _display_summary_panel(counts, trades)

        if not trades:
            console.print(
                "  [yellow]No closed trades yet — let bracket orders fill and exit "
                "before re-running evaluate.[/yellow]\n"
            )
            return

        _display_calibration_table(trades)
        _display_verdict(trades)
    finally:
        db.close()


def _reconcile_closed_trades(client, db, days):
    """
    Walk Alpaca's recent filled orders, pair BUYs to their bracket SELLs by symbol,
    and insert paper_trades rows for closed round-trips.
    """
    closed = client.get_closed_orders_since(days=days)
    fills = [o for o in closed if (o["filled_qty"] or 0) > 0 and o["filled_at"]]

    # First pass: persist fill data for any BUY orders we tracked.
    for o in fills:
        if o["side"] == "buy":
            existing = db.get_order_by_alpaca_id(o["order_id"])
            if existing:
                db.update_order_fill(
                    o["order_id"], o["status"],
                    o["filled_qty"], o["filled_price"], o["filled_at"],
                )

    # Build per-ticker timelines of fills (chronological).
    by_ticker = defaultdict(list)
    for o in fills:
        by_ticker[o["ticker"]].append(o)
    for lst in by_ticker.values():
        lst.sort(key=lambda x: x["filled_at"])

    # Match BUYs (with a tracked recommendation) to their first subsequent SELL.
    new_trade_count = 0
    for ticker, fills_list in by_ticker.items():
        buys = [f for f in fills_list if f["side"] == "buy"]
        sells = [f for f in fills_list if f["side"] == "sell"]
        sell_idx = 0

        for buy in buys:
            tracked = db.get_order_by_alpaca_id(buy["order_id"])
            if not tracked:
                continue  # not one of ours

            # Already closed?
            existing_trades = [
                t for t in db.get_all_trades()
                if t.get("recommendation_id") == tracked["recommendation_id"]
            ]
            if existing_trades:
                continue

            # Find next sell after this buy
            matching_sell = None
            while sell_idx < len(sells):
                if sells[sell_idx]["filled_at"] > buy["filled_at"]:
                    matching_sell = sells[sell_idx]
                    sell_idx += 1
                    break
                sell_idx += 1

            if matching_sell is None:
                continue  # still open

            score = _lookup_score(db, tracked["recommendation_id"])
            db.insert_trade(
                recommendation_id=tracked["recommendation_id"],
                ticker=ticker,
                qty=buy["filled_qty"],
                entry_price=buy["filled_price"],
                exit_price=matching_sell["filled_price"],
                entry_at=buy["filled_at"],
                exit_at=matching_sell["filled_at"],
                exit_reason=_classify_exit(buy, matching_sell, tracked),
                composite_score=score,
            )
            new_trade_count += 1

    return new_trade_count


def _lookup_score(db, recommendation_id):
    if recommendation_id is None:
        return None
    row = db._conn.execute(
        "SELECT composite_score FROM recommendations WHERE id = ?",
        (recommendation_id,),
    ).fetchone()
    return float(row[0]) if row else None


def _classify_exit(buy, sell, tracked):
    """Best-effort label: stop_hit / target_hit / manual."""
    sell_price = sell["filled_price"]
    if sell_price is None:
        return "manual"
    if tracked.get("stop_loss") and sell_price <= tracked["stop_loss"] * 1.01:
        return "stop_hit"
    if tracked.get("take_profit") and sell_price >= tracked["take_profit"] * 0.99:
        return "target_hit"
    return "manual"


# --- Display ----------------------------------------------------------------


def _display_summary_panel(counts, trades):
    wins = sum(1 for t in trades if t["pnl"] > 0)
    losses = sum(1 for t in trades if t["pnl"] < 0)
    total_pnl = sum(t["pnl"] for t in trades)
    win_rate = wins / len(trades) * 100 if trades else 0

    body = (
        f"Recommendations logged: [bold]{counts['recommendations']}[/bold]  "
        f"(submitted: {counts['submitted']})\n"
        f"Orders placed:          [bold]{counts['orders']}[/bold]\n"
        f"Closed trades:          [bold]{counts['closed_trades']}[/bold]\n"
    )
    if trades:
        body += (
            f"Win/Loss:               [green]{wins}W[/green] / [red]{losses}L[/red] "
            f"({win_rate:.1f}% win rate)\n"
            f"Realized P&L:           "
            f"[{'green' if total_pnl >= 0 else 'red'}]"
            f"${total_pnl:+,.2f}[/{'green' if total_pnl >= 0 else 'red'}]"
        )
    console.print(Panel(body, title="Validation Summary", box=box.ROUNDED))
    console.print()


def _display_calibration_table(trades):
    buckets = defaultdict(list)
    for t in trades:
        s = t.get("composite_score")
        if s is None:
            continue
        for label, lo, hi in SCORE_BUCKETS:
            if lo <= s < hi:
                buckets[label].append(t)
                break

    table = Table(box=box.ROUNDED, title="Score Calibration", show_lines=False)
    table.add_column("Score Bucket", style="bold cyan")
    table.add_column("Trades", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("Avg P&L %", justify="right")
    table.add_column("Median P&L %", justify="right")
    table.add_column("Avg Hold (d)", justify="right")
    table.add_column("Total P&L $", justify="right")

    for label, _, _ in SCORE_BUCKETS:
        bucket = buckets[label]
        if not bucket:
            table.add_row(label, "0", "—", "—", "—", "—", "—")
            continue

        n = len(bucket)
        wins = sum(1 for t in bucket if t["pnl"] > 0)
        win_rate = wins / n * 100
        pnl_pcts = sorted(t["pnl_pct"] for t in bucket)
        avg_pct = sum(pnl_pcts) / n
        median_pct = pnl_pcts[n // 2]
        avg_hold = sum((t["hold_days"] or 0) for t in bucket) / n
        total_pnl = sum(t["pnl"] for t in bucket)

        win_color = "green" if win_rate >= 50 else "red"
        pnl_color = "green" if avg_pct > 0 else "red"

        table.add_row(
            label,
            str(n),
            f"[{win_color}]{win_rate:.0f}%[/{win_color}]",
            f"[{pnl_color}]{avg_pct:+.2f}%[/{pnl_color}]",
            f"{median_pct:+.2f}%",
            f"{avg_hold:.1f}",
            f"[{pnl_color}]${total_pnl:+,.2f}[/{pnl_color}]",
        )

    console.print(table)
    console.print()


def _display_verdict(trades):
    """Compare top vs bottom buckets to give a one-line verdict."""
    scored = [t for t in trades if t.get("composite_score") is not None]
    if len(scored) < 5:
        console.print(
            "  [dim]Need at least ~5 closed trades for a meaningful verdict. "
            "Keep running paper trade.[/dim]\n"
        )
        return

    high = [t for t in scored if t["composite_score"] >= 65]
    low = [t for t in scored if t["composite_score"] < 65]

    if not high or not low:
        console.print(
            "  [dim]Need closed trades in both score>=65 AND score<65 buckets to compare.[/dim]\n"
        )
        return

    high_win = sum(1 for t in high if t["pnl"] > 0) / len(high) * 100
    low_win = sum(1 for t in low if t["pnl"] > 0) / len(low) * 100
    high_avg = sum(t["pnl_pct"] for t in high) / len(high)
    low_avg = sum(t["pnl_pct"] for t in low) / len(low)
    win_diff = high_win - low_win
    pct_diff = high_avg - low_avg

    if win_diff > 10 and pct_diff > 1:
        verdict = (
            f"[bold green]Score appears predictive.[/bold green] "
            f"Score>=65 wins {high_win:.0f}% vs {low_win:.0f}% for <65, "
            f"avg return {high_avg:+.2f}% vs {low_avg:+.2f}%."
        )
    elif win_diff < -5 or pct_diff < -1:
        verdict = (
            f"[bold red]Score appears anti-predictive.[/bold red] "
            f"Score>=65 wins {high_win:.0f}% vs {low_win:.0f}%, "
            f"avg {high_avg:+.2f}% vs {low_avg:+.2f}%. Strategy weights need rework."
        )
    else:
        verdict = (
            f"[bold yellow]Inconclusive — score not yet predictive.[/bold yellow] "
            f"Score>=65 wins {high_win:.0f}% vs {low_win:.0f}%, "
            f"avg {high_avg:+.2f}% vs {low_avg:+.2f}%. Need more data."
        )

    console.print(Panel(verdict, title="Verdict", box=box.ROUNDED))
    console.print()
