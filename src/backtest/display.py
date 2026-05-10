"""Backtest result display — Rich panels and tables for IS/OOS split + cost grid + CIs."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()


def display_backtest_results(result: dict, strategy_name: str, universe_label: str) -> None:
    if "error" in result:
        console.print(f"[red]Backtest error: {result['error']}[/red]")
        return

    full = result["full"]
    isample = result["in_sample"]
    oos = result["out_of_sample"]
    sensitivity = result.get("cost_sensitivity")
    bootstrap = result.get("bootstrap")
    boot_label = result.get("bootstrap_label", "OOS")
    verdict_oos = result.get("verdict_oos", "")
    warnings = result.get("warnings", [])

    full_summary = full["summary"]
    is_summary = isample["summary"]
    oos_summary = oos["summary"]
    full_eq = full["equity_stats"]
    is_eq = isample["equity_stats"]
    oos_eq = oos["equity_stats"]

    console.print()
    console.print(Panel(
        f"[bold cyan]Backtest Complete[/bold cyan]\n"
        f"Strategy: [bold]{strategy_name}[/bold]   Universe: [bold]{universe_label}[/bold]\n"
        f"Window: {full_summary['start_date']} -> {full_summary['end_date']}    "
        f"OOS split at: {result.get('split_date', '?')}",
        box=box.ROUNDED,
    ))

    # Three-column summary: Full | In-Sample | OOS
    sm = Table(title="Returns by Section", box=box.ROUNDED)
    sm.add_column("Metric", style="bold")
    sm.add_column("Full", justify="right")
    sm.add_column("In-Sample (70%)", justify="right")
    sm.add_column("Out-of-Sample (30%)", justify="right", style="bold yellow")
    sm.add_row("Trades", str(full_summary["n_trades"]), str(is_summary["n_trades"]), str(oos_summary["n_trades"]))
    sm.add_row(
        "Total return",
        _color_pct(full_summary["total_return_pct"]),
        _color_pct(is_summary["total_return_pct"]),
        _color_pct(oos_summary["total_return_pct"]),
    )
    sm.add_row(
        "CAGR",
        _color_pct(full_summary["cagr_pct"]),
        _color_pct(is_summary["cagr_pct"]),
        _color_pct(oos_summary["cagr_pct"]),
    )
    sm.add_row(
        "Win rate",
        f"{full_summary['win_rate_pct']:.1f}%",
        f"{is_summary['win_rate_pct']:.1f}%",
        f"{oos_summary['win_rate_pct']:.1f}%",
    )
    sm.add_row(
        "Expectancy / trade",
        _color_pct(full_summary["expectancy_pct"]),
        _color_pct(is_summary["expectancy_pct"]),
        _color_pct(oos_summary["expectancy_pct"]),
    )
    if full_summary.get("spy_return_pct") is not None:
        sm.add_row(
            "Alpha vs SPY (matched)",
            _color_pct(full_summary.get("alpha_vs_spy_matched_pct")),
            _color_pct(is_summary.get("alpha_vs_spy_matched_pct")),
            _color_pct(oos_summary.get("alpha_vs_spy_matched_pct")),
        )
    console.print(sm)

    # Risk metrics from the equity curve
    rm = Table(title="Risk-Adjusted Metrics (from weekly equity curve)", box=box.ROUNDED)
    rm.add_column("Metric", style="bold")
    rm.add_column("Full", justify="right")
    rm.add_column("In-Sample", justify="right")
    rm.add_column("Out-of-Sample", justify="right", style="bold yellow")
    rm.add_row(
        "Annualized Sharpe",
        f"{full_eq['ann_sharpe']:.2f}",
        f"{is_eq['ann_sharpe']:.2f}",
        f"{oos_eq['ann_sharpe']:.2f}",
    )
    rm.add_row(
        "Annualized Sortino",
        f"{full_eq['ann_sortino']:.2f}",
        f"{is_eq['ann_sortino']:.2f}",
        f"{oos_eq['ann_sortino']:.2f}",
    )
    rm.add_row(
        "Calmar (CAGR / |MaxDD|)",
        f"{full_eq['calmar']:.2f}",
        f"{is_eq['calmar']:.2f}",
        f"{oos_eq['calmar']:.2f}",
    )
    rm.add_row(
        "Max drawdown",
        _color_pct(full_eq["max_drawdown_pct"]),
        _color_pct(is_eq["max_drawdown_pct"]),
        _color_pct(oos_eq["max_drawdown_pct"]),
    )
    rm.add_row(
        "Time underwater",
        f"{full_eq['time_in_dd_pct']:.0f}%",
        f"{is_eq['time_in_dd_pct']:.0f}%",
        f"{oos_eq['time_in_dd_pct']:.0f}%",
    )
    rm.add_row(
        "Annualized volatility",
        f"{full_eq['ann_volatility_pct']:.1f}%",
        f"{is_eq['ann_volatility_pct']:.1f}%",
        f"{oos_eq['ann_volatility_pct']:.1f}%",
    )
    console.print(rm)

    # Costs paid (full window only)
    if full_summary.get("total_costs_paid", 0) > 0:
        console.print(
            f"\n[dim]Costs paid (full window): "
            f"${full_summary['total_costs_paid']:,.2f}  "
            f"(commission ${full_summary['commissions_paid']:.0f} / "
            f"slippage ${full_summary['slippage_cost']:.0f} / "
            f"regulatory ${full_summary['regulatory_fees']:.0f})[/dim]"
        )

    # OOS Calibration — the only one that matters for verdict
    ct = Table(
        title="OOS Score-Bucket Calibration (verdict basis)",
        box=box.ROUNDED,
    )
    ct.add_column("Bucket", style="bold")
    ct.add_column("N", justify="right")
    ct.add_column("Win rate", justify="right")
    ct.add_column("Avg return", justify="right")
    ct.add_column("Median return", justify="right")
    ct.add_column("Avg hold", justify="right")
    ct.add_column("Total P&L", justify="right")
    for row in oos["calibration"]:
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

    # Cost sensitivity grid
    if sensitivity:
        cs = Table(title="Cost Sensitivity (slippage bps each side, full window)", box=box.ROUNDED)
        cs.add_column("Slippage", style="bold", justify="right")
        cs.add_column("Total P&L", justify="right")
        cs.add_column("Total return", justify="right")
        for row in sensitivity["levels"]:
            cs.add_row(
                f"{row['bps_each_side']} bps",
                f"${row['total_pnl']:,.0f}",
                _color_pct(row["total_return_pct"]),
            )
        console.print(cs)
        breakeven = sensitivity.get("breakeven_bps")
        if breakeven is not None:
            color = "red" if breakeven < 10 else ("yellow" if breakeven < 25 else "green")
            console.print(
                f"  [{color}]Breakeven slippage: {breakeven} bps each side[/{color}]   "
                f"[dim](edge survives up to this cost level)[/dim]"
            )
        else:
            console.print(
                "  [dim]Breakeven not in tested range — strategy was already negative at 0 bps "
                "or still positive at 50 bps.[/dim]"
            )

    # Bootstrap CIs
    if bootstrap and bootstrap.get("n_resamples", 0) > 0:
        bc = Table(title=f"Bootstrap 95% CIs ({boot_label}, n={bootstrap['n_resamples']})", box=box.ROUNDED)
        bc.add_column("Metric", style="bold")
        bc.add_column("CI low", justify="right")
        bc.add_column("CI high", justify="right")
        if bootstrap.get("total_return_ci_pct"):
            lo, hi = bootstrap["total_return_ci_pct"]
            bc.add_row("Total return", _color_pct(lo), _color_pct(hi))
        if bootstrap.get("win_rate_ci_pct"):
            lo, hi = bootstrap["win_rate_ci_pct"]
            bc.add_row("Win rate", f"{lo:.1f}%", f"{hi:.1f}%")
        if bootstrap.get("expectancy_ci_pct"):
            lo, hi = bootstrap["expectancy_ci_pct"]
            bc.add_row("Expectancy / trade", _color_pct(lo), _color_pct(hi))
        console.print(bc)
    elif bootstrap and bootstrap.get("note"):
        console.print(f"  [dim]Bootstrap: {bootstrap['note']}[/dim]")

    # Exit reasons
    exits = result.get("exit_reasons", {})
    if exits:
        ex = Table(title="Exit Reasons (full window)", box=box.ROUNDED)
        ex.add_column("Reason", style="bold")
        ex.add_column("Count", justify="right")
        for reason, count in sorted(exits.items(), key=lambda x: -x[1]):
            ex.add_row(reason, str(count))
        console.print(ex)

    # Excursion analytics (Tier 4.3)
    excursion = result.get("excursion")
    if excursion and excursion.get("avg_mfe_pct") != 0:
        ex = Table(title="Trade Excursion Diagnostics (full window)", box=box.ROUNDED)
        ex.add_column("Metric", style="bold")
        ex.add_column("Value", justify="right")
        ex.add_row("Avg MFE (max favorable excursion)", _color_pct(excursion["avg_mfe_pct"]))
        ex.add_row("Avg MAE (max adverse excursion)", _color_pct(excursion["avg_mae_pct"]))
        ex.add_row("MFE capture (% retained as P&L)", f"{excursion['mfe_capture_pct']:.0f}%")
        ex.add_row("Avg R-multiple", f"{excursion['avg_r_multiple']:+.2f}R")
        ex.add_row("Avg R on losing trades (stop proximity)", f"{excursion['stop_proximity_pct']:+.2f}R")
        console.print(ex)

        # R-multiple distribution
        rdist = excursion.get("r_distribution", {})
        if rdist and any(v > 0 for v in rdist.values()):
            rd = Table(title="R-Multiple Distribution", box=box.ROUNDED)
            rd.add_column("Bucket", style="bold")
            rd.add_column("Count", justify="right")
            for label, count in rdist.items():
                rd.add_row(label, str(count))
            console.print(rd)

    # Regime split (Tier 4.2)
    regimes = result.get("regimes")
    if regimes:
        rg = Table(title="Performance by Regime (at trade entry)", box=box.ROUNDED)
        rg.add_column("Regime", style="bold")
        rg.add_column("N", justify="right")
        rg.add_column("Win rate", justify="right")
        rg.add_column("Avg return", justify="right")
        rg.add_column("Total P&L", justify="right")
        regime_order = [
            ("SPY > 200-SMA (bull)", regimes.get("spy_bull")),
            ("SPY < 200-SMA (bear)", regimes.get("spy_bear")),
            ("VIX < 15 (low)", regimes.get("vix_low")),
            ("VIX 15-25 (normal)", regimes.get("vix_normal")),
            ("VIX > 25 (high)", regimes.get("vix_high")),
        ]
        for label, data in regime_order:
            if not data or data["n"] == 0:
                rg.add_row(label, "0", "-", "-", "-")
                continue
            rg.add_row(
                label,
                str(data["n"]),
                f"{data['win_rate_pct']:.1f}%",
                _color_pct(data["avg_return_pct"]),
                f"${data['total_pnl']:,.0f}",
            )
        console.print(rg)

    # Monthly return heatmap (Tier 4.1)
    monthly = result.get("monthly_returns") or {}
    if monthly:
        mh = Table(title="Monthly Returns (% from equity curve)", box=box.ROUNDED)
        mh.add_column("Year", style="bold")
        for m in range(1, 13):
            mh.add_column(_short_month(m), justify="right")
        for year in sorted(monthly.keys()):
            row = [str(year)]
            months = monthly[year]
            for m in range(1, 13):
                if m in months:
                    row.append(_color_pct(months[m]))
                else:
                    row.append("-")
            mh.add_row(*row)
        console.print(mh)

    # Verdict — uses OOS data only
    console.print(Panel(
        verdict_oos,
        title="Verdict (OOS, statistically grounded)",
        box=box.ROUNDED,
        style="bold yellow",
    ))

    for w in warnings:
        console.print(f"[yellow]WARNING: {w}[/yellow]")


_SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _short_month(m: int) -> str:
    return _SHORT_MONTHS[m - 1] if 1 <= m <= 12 else str(m)


def display_strategy_comparison(rows: list[dict], universe_label: str) -> None:
    """Display side-by-side comparison of all strategies (4.4)."""
    console.print()
    console.print(Panel(
        f"[bold cyan]Strategy Comparison[/bold cyan]   Universe: [bold]{universe_label}[/bold]",
        box=box.ROUNDED,
    ))
    tbl = Table(title="Headline Metrics by Strategy", box=box.ROUNDED, show_lines=True)
    tbl.add_column("Strategy", style="bold cyan")
    tbl.add_column("Trades", justify="right")
    tbl.add_column("Total return", justify="right")
    tbl.add_column("OOS return", justify="right", style="bold yellow")
    tbl.add_column("Sharpe", justify="right")
    tbl.add_column("OOS Sharpe", justify="right", style="bold yellow")
    tbl.add_column("Max DD", justify="right")
    tbl.add_column("Win rate", justify="right")
    tbl.add_column("Alpha vs SPY (matched)", justify="right")

    for row in rows:
        if "error" in row:
            tbl.add_row(row["strategy"], "—", f"[red]blocked[/red]", "", "", "", "", "", "")
            continue
        r = row["result"]
        full = r["full"]["summary"]
        oos = r["out_of_sample"]["summary"]
        full_eq = r["full"]["equity_stats"]
        oos_eq = r["out_of_sample"]["equity_stats"]
        tbl.add_row(
            row["strategy"],
            str(full["n_trades"]),
            _color_pct(full["total_return_pct"]),
            _color_pct(oos["total_return_pct"]),
            f"{full_eq['ann_sharpe']:+.2f}",
            f"{oos_eq['ann_sharpe']:+.2f}",
            _color_pct(full_eq["max_drawdown_pct"]),
            f"{full['win_rate_pct']:.1f}%",
            _color_pct(full.get("alpha_vs_spy_matched_pct")),
        )
    console.print(tbl)
    console.print(
        "  [dim]Tip: rank by OOS Sharpe — that column tells you which strategy "
        "actually generalized.[/dim]\n"
    )


def _color_pct(value) -> str:
    if value is None:
        return "-"
    color = "green" if value > 0 else ("red" if value < 0 else "white")
    return f"[{color}]{value:+.2f}%[/{color}]"
