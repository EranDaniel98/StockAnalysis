"""Backtest result display — Rich panels and tables."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()


def display_backtest_results(result: dict, strategy_name: str, universe_label: str) -> None:
    if "error" in result:
        console.print(f"[red]Backtest error: {result['error']}[/red]")
        return

    summary = result["summary"]
    cal = result["calibration"]
    exits = result.get("exit_reasons", {})
    warnings = result.get("warnings", [])
    verdict = result.get("verdict", "")

    console.print()
    console.print(Panel(
        f"[bold cyan]Backtest Complete[/bold cyan]\n"
        f"Strategy: [bold]{strategy_name}[/bold]   Universe: [bold]{universe_label}[/bold]\n"
        f"Window: {summary['start_date']} -> {summary['end_date']}",
        box=box.ROUNDED,
    ))

    # Summary table
    sm = Table(title="Summary", box=box.ROUNDED, show_lines=False)
    sm.add_column("Metric", style="bold")
    sm.add_column("Value", justify="right")
    sm.add_row("Trades", str(summary["n_trades"]))
    sm.add_row("Starting cash", f"${summary['starting_cash']:,.0f}")
    sm.add_row("Ending equity", f"${summary['ending_equity']:,.0f}")
    sm.add_row("Total return", _color_pct(summary["total_return_pct"]))
    sm.add_row("CAGR", _color_pct(summary["cagr_pct"]))
    sm.add_row("Win rate", f"{summary['win_rate_pct']:.1f}%")
    sm.add_row("Avg win / Avg loss", f"{summary['avg_win_pct']:+.2f}% / {summary['avg_loss_pct']:+.2f}%")
    sm.add_row("Expectancy / trade", _color_pct(summary["expectancy_pct"]))
    sm.add_row("Avg hold (days)", f"{summary['avg_hold_days']:.1f}")
    sm.add_row("Sharpe (per-trade)", f"{summary['sharpe_per_trade']:.2f}")
    if summary.get("spy_return_pct") is not None:
        sm.add_row("SPY buy-hold", _color_pct(summary["spy_return_pct"]))
        sm.add_row("Alpha vs SPY (full window)", _color_pct(summary["alpha_vs_spy_pct"]))
    if summary.get("spy_deployment_matched_pct") is not None:
        sm.add_row("SPY (deployment-matched)", _color_pct(summary["spy_deployment_matched_pct"]))
        sm.add_row("Alpha vs SPY (matched)", _color_pct(summary["alpha_vs_spy_matched_pct"]))
    if summary.get("total_costs_paid", 0) > 0:
        sm.add_row(
            "Costs (commission/slippage/reg)",
            f"${summary['total_costs_paid']:,.2f}  "
            f"(${summary['commissions_paid']:.0f} / ${summary['slippage_cost']:.0f} / ${summary['regulatory_fees']:.0f})",
        )
    console.print(sm)

    # Calibration table — the actual answer to "is the score predictive?"
    ct = Table(title="Score-Bucket Calibration", box=box.ROUNDED, show_lines=False)
    ct.add_column("Bucket", style="bold")
    ct.add_column("N", justify="right")
    ct.add_column("Win rate", justify="right")
    ct.add_column("Avg return", justify="right")
    ct.add_column("Median return", justify="right")
    ct.add_column("Avg hold", justify="right")
    ct.add_column("Total P&L", justify="right")
    for row in cal:
        if row["n"] == 0:
            ct.add_row(row["bucket"], "0", "-", "-", "-", "-", "-")
        else:
            ct.add_row(
                row["bucket"],
                str(row["n"]),
                f"{row['win_rate']:.1f}%",
                _color_pct(row["avg_return_pct"]),
                _color_pct(row["median_return_pct"]),
                f"{row['avg_hold_days']:.0f}d",
                f"${row['total_pnl']:,.0f}",
            )
    console.print(ct)

    # Exit reasons
    if exits:
        ex = Table(title="Exit Reasons", box=box.ROUNDED)
        ex.add_column("Reason", style="bold")
        ex.add_column("Count", justify="right")
        for reason, count in sorted(exits.items(), key=lambda x: -x[1]):
            ex.add_row(reason, str(count))
        console.print(ex)

    # Verdict
    console.print(Panel(verdict, title="Verdict", box=box.ROUNDED, style="bold yellow"))

    # Warnings
    for w in warnings:
        console.print(f"[yellow]WARNING: {w}[/yellow]")


def _color_pct(value) -> str:
    if value is None:
        return "-"
    color = "green" if value > 0 else ("red" if value < 0 else "white")
    return f"[{color}]{value:+.2f}%[/{color}]"
