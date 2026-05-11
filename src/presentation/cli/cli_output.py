"""
CLI output module using Rich for beautiful terminal display.
Tables, panels, and formatted reports.
"""

import logging
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich import box

logger = logging.getLogger(__name__)

console = Console()

# Box style mapping
BOX_STYLES = {
    "rounded": box.ROUNDED,
    "simple": box.SIMPLE,
    "grid": box.SQUARE,
    "heavy": box.HEAVY,
    "double": box.DOUBLE,
}


def display_scan_results(recommendations, config, strategy_name=None):
    """Display the full scan results with rankings."""
    top_n = config.get("display", "top_n_results", default=20)
    show_detail = config.get("display", "show_detailed_analysis", default=True)
    table_style = config.get("display", "table_style", default="rounded")
    box_style = BOX_STYLES.get(table_style, box.ROUNDED)

    # Header
    console.print()
    header = f"Stock Scanner Results"
    if strategy_name:
        header += f" - Strategy: {strategy_name}"
    console.print(Panel(header, style="bold cyan", box=box_style))

    # Summary table
    table = Table(
        title="Top Stocks by Composite Score",
        box=box_style,
        show_lines=True,
        title_style="bold",
    )

    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Ticker", style="bold cyan", width=8)
    table.add_column("Name", width=25, no_wrap=True)
    table.add_column("Action", width=12, justify="center")
    table.add_column("Score", width=7, justify="center")
    table.add_column("Tech", width=6, justify="center")
    table.add_column("Fund", width=6, justify="center")
    table.add_column("Stat", width=6, justify="center")
    table.add_column("Trend", width=6, justify="center")
    table.add_column("Sector", width=20, no_wrap=True)
    table.add_column("Price", width=10, justify="right")
    table.add_column("Stop Loss", width=10, justify="right")
    table.add_column("Target", width=10, justify="right")
    table.add_column("R:R", width=5, justify="center")

    for i, rec in enumerate(recommendations[:top_n], 1):
        action = rec["action"]
        action_styled = _style_action(action)
        score = rec["composite_score"]
        score_styled = _style_score(score)

        sub = rec.get("sub_scores", {})
        risk = rec.get("risk_management", {})
        sl = risk.get("stop_loss", {})
        tp = risk.get("take_profit", {})
        current = risk.get("current_price", "N/A")
        rr = risk.get("risk_reward_ratio", "N/A")

        table.add_row(
            str(i),
            rec["ticker"],
            rec.get("name", "")[:25],
            action_styled,
            score_styled,
            _style_subscore(sub.get("technical", 50)),
            _style_subscore(sub.get("fundamental", 50)),
            _style_subscore(sub.get("statistical", 50)),
            _style_subscore(sub.get("trend", 50)),
            rec.get("sector", "Unknown")[:20],
            f"${current}" if isinstance(current, (int, float)) else str(current),
            f"${sl.get('price', 'N/A')}" if sl.get('price') else "N/A",
            f"${tp.get('price', 'N/A')}" if tp.get('price') else "N/A",
            f"{rr}" if isinstance(rr, (int, float)) else str(rr),
        )

    console.print(table)

    # Detailed view for top stocks
    if show_detail:
        buy_recs = [r for r in recommendations[:top_n] if r["action"] in ("STRONG BUY", "BUY")]
        for rec in buy_recs[:5]:
            display_stock_detail(rec, box_style)


def display_stock_detail(rec, box_style=box.ROUNDED):
    """Display detailed analysis for a single stock."""
    console.print()

    # Header with key info
    action = rec["action"]
    score = rec["composite_score"]
    title = f"{rec['ticker']} - {rec.get('name', '')} | {action} ({score:.0f}/100)"

    lines = []

    # Score breakdown
    lines.append("[bold]Score Breakdown:[/bold]")
    for b in rec.get("breakdown", []):
        bar = _score_bar(b["score"])
        lines.append(f"  {b['category']:<12} {bar} {b['score']:>5.1f}  (weight: {b['weight']})")

    # Key signals
    lines.append("")
    lines.append("[bold]Key Signals:[/bold]")
    for reason in rec.get("reasoning", [])[:8]:
        if reason.startswith("+"):
            lines.append(f"  [green]{reason}[/green]")
        elif reason.startswith("-"):
            lines.append(f"  [red]{reason}[/red]")
        else:
            lines.append(f"  {reason}")

    # Risk Management
    risk = rec.get("risk_management", {})
    if risk:
        lines.append("")
        lines.append("[bold]Risk Management:[/bold]")
        current = risk.get("current_price", "N/A")
        sl = risk.get("stop_loss", {})
        tp = risk.get("take_profit", {})
        pos = risk.get("position", {})
        rr = risk.get("risk_reward_ratio", "N/A")

        lines.append(f"  Current Price:  ${current}")
        if sl.get("price"):
            lines.append(f"  Stop Loss:      ${sl['price']} ({sl.get('pct_from_current', 0):+.1f}%)")
        if tp.get("price"):
            lines.append(f"  Take Profit:    ${tp['price']} ({tp.get('pct_from_current', 0):+.1f}%)")
        lines.append(f"  Risk/Reward:    {rr}")
        if pos.get("recommended_shares"):
            lines.append(f"  Position Size:  {pos['recommended_shares']} shares (${pos.get('dollar_amount', 0):,.0f})")
            lines.append(f"  Portfolio %:    {pos.get('pct_of_portfolio', 0):.1f}%")
            if pos.get("risk_pct"):
                lines.append(f"  Risk/Trade:     ${pos.get('risk_per_trade', 0):,.0f} ({pos['risk_pct']:.2f}% of portfolio)")

    content = "\n".join(lines)
    color = "green" if action in ("STRONG BUY", "BUY") else "yellow" if action == "HOLD" else "red"
    console.print(Panel(content, title=title, border_style=color, box=box_style))


def display_trending_sectors(sector_data, box_style_name="rounded"):
    """Display trending sectors analysis."""
    box_style = BOX_STYLES.get(box_style_name, box.ROUNDED)

    console.print()
    console.print(Panel("Trending Sectors Analysis", style="bold cyan", box=box_style))

    table = Table(box=box_style, show_lines=True)
    table.add_column("Sector", style="bold", width=25)
    table.add_column("Stocks", width=8, justify="center")
    table.add_column("Avg 1M Return", width=14, justify="center")
    table.add_column("Avg 3M Return", width=14, justify="center")
    table.add_column("Vol Ratio", width=10, justify="center")
    table.add_column("% Positive", width=10, justify="center")
    table.add_column("Trend Score", width=12, justify="center")

    for sector in sector_data:
        ret_1m = sector["avg_return_1m"]
        ret_3m = sector["avg_return_3m"]
        trend = sector["trend_score"]

        table.add_row(
            sector["sector"],
            str(sector["stock_count"]),
            _color_pct(ret_1m),
            _color_pct(ret_3m),
            f"{sector['avg_vol_ratio']:.2f}x",
            f"{sector['pct_positive_1m']:.0f}%",
            _style_score(trend),
        )

    console.print(table)


def display_diversification_warnings(warnings):
    """Display portfolio diversification warnings."""
    if not warnings:
        return

    console.print()
    lines = "\n".join(f"  {w}" for w in warnings)
    console.print(Panel(
        lines,
        title="Diversification Warnings",
        border_style="yellow",
        box=box.ROUNDED,
    ))


def display_investment_plan(plan):
    """Display the portfolio allocation / investment plan."""
    console.print()

    summary = plan["summary"]
    budget = summary["budget"]

    # Header panel
    header_lines = [
        f"[bold]Total Budget:[/bold]     ${budget:,.2f}",
        f"[bold]Invested:[/bold]          ${summary['total_invested']:,.2f} ({100 - summary['cash_pct']:.1f}%)",
        f"[bold]Cash Reserve:[/bold]      ${summary['cash_reserve']:,.2f} ({summary['cash_pct']:.1f}%)",
        f"[bold]Positions:[/bold]         {summary['num_positions']}",
        f"[bold]Sectors:[/bold]           {summary['sectors']}",
        f"[bold]Avg Score:[/bold]         {summary['avg_score']:.0f}/100",
    ]

    # Sector breakdown
    if summary.get("sector_breakdown"):
        header_lines.append("")
        header_lines.append("[bold]Sector Allocation:[/bold]")
        for sector, pct in sorted(
            summary["sector_breakdown"].items(), key=lambda x: x[1], reverse=True
        ):
            bar_len = int(pct / 2)
            header_lines.append(f"  {sector:<25} [cyan]{'█' * bar_len}[/cyan] {pct:.1f}%")

    console.print(Panel(
        "\n".join(header_lines),
        title="[bold cyan]Investment Plan[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED,
    ))

    # Allocations table
    allocations = plan["allocations"]
    if not allocations:
        console.print("[yellow]  No allocations - no BUY signals found.[/yellow]\n")
        return

    table = Table(
        title="How to Split Your Money",
        box=box.ROUNDED,
        show_lines=True,
        title_style="bold",
    )

    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Ticker", style="bold cyan", width=8)
    table.add_column("Name", width=22, no_wrap=True)
    table.add_column("Action", width=12, justify="center")
    table.add_column("Score", width=6, justify="center")
    table.add_column("Alloc %", width=8, justify="center")
    table.add_column("Amount", width=12, justify="right")
    table.add_column("Shares", width=7, justify="center")
    table.add_column("Price", width=10, justify="right")
    table.add_column("Order Type", width=12, justify="center")
    table.add_column("Stop Loss", width=10, justify="right")
    table.add_column("Target", width=10, justify="right")
    table.add_column("R:R", width=5, justify="center")

    for i, a in enumerate(allocations, 1):
        table.add_row(
            str(i),
            a["ticker"],
            a["name"][:22],
            _style_action(a["action"]),
            _style_score(a["score"]),
            f"{a['allocation_pct']:.1f}%",
            f"${a['dollar_amount']:,.0f}",
            str(a["shares"]),
            f"${a['price']:.2f}",
            _style_order_type(a["order_type"]),
            f"${a['stop_loss']:.2f}" if a["stop_loss"] else "N/A",
            f"${a['take_profit']:.2f}" if a["take_profit"] else "N/A",
            f"{a['risk_reward']:.1f}" if a["risk_reward"] else "N/A",
        )

    console.print(table)

    # Step-by-step order instruction cards
    console.print()
    for a in allocations:
        steps = a.get("order_steps", [])
        if not steps:
            # Fallback to old format
            order_price_str = f" @ ${a['order_price']:.2f}" if a.get("order_price") else ""
            console.print(Panel(
                f"  [bold]{a['order_type']} Order[/bold]{order_price_str} - {a['order_detail']}",
                title=f"[bold cyan]{a['ticker']}[/bold cyan]",
                border_style="green",
                box=box.ROUNDED,
            ))
            continue

        lines = []
        for i, step in enumerate(steps, 1):
            lines.append(f"  [bold]Step {i}:[/bold] {step}")

        if a.get("order_why"):
            lines.append("")
            lines.append(f"  [dim]Why {a['order_type']} Order:[/dim] {a['order_why']}")

        if a.get("order_risk_summary"):
            lines.append(f"  [bold]{a['order_risk_summary']}[/bold]")

        border = "green" if a["order_type"] == "Market" else "cyan" if a["order_type"] == "Limit" else "yellow"

        console.print(Panel(
            "\n".join(lines),
            title=(
                f"[bold cyan]{a['ticker']}[/bold cyan] — "
                f"{_style_action(a['action'])} — "
                f"{a['shares']} shares @ ${a['price']:.2f}"
            ),
            border_style=border,
            box=box.ROUNDED,
        ))

    # Warnings
    if plan["warnings"]:
        console.print()
        warning_lines = "\n".join(f"  [yellow]{w}[/yellow]" for w in plan["warnings"])
        console.print(Panel(
            warning_lines,
            title="Warnings",
            border_style="yellow",
            box=box.ROUNDED,
        ))

    # Cash reserve note
    if plan["cash_reserve"] > 0:
        console.print()
        console.print(
            f"  [dim]Cash reserve: ${plan['cash_reserve']:,.2f} "
            f"({summary['cash_pct']:.1f}% of budget) - "
            f"kept aside due to position/sector limits or rounding[/dim]"
        )
    console.print()


def display_portfolio(positions_data, enriched_positions=None, sector_exposure=None):
    """Display portfolio overview with P&L and optional analysis."""
    console.print()

    pd = positions_data
    total_pnl = pd["total_unrealized_pnl"]
    pnl_color = "green" if total_pnl >= 0 else "red"

    # Summary header
    header_lines = [
        f"[bold]Total Portfolio:[/bold]   ${pd['total_portfolio_value']:,.2f}",
        f"[bold]Invested:[/bold]          ${pd['total_market_value']:,.2f}",
        f"[bold]Cost Basis:[/bold]        ${pd['total_cost']:,.2f}",
        f"[bold]Unrealized P&L:[/bold]    [{pnl_color}]${total_pnl:+,.2f} ({pd['total_pnl_pct']:+.2f}%)[/{pnl_color}]",
        f"[bold]Cash Available:[/bold]    ${pd['cash_available']:,.2f} ({pd['cash_pct']:.1f}%)",
        f"[bold]Positions:[/bold]         {pd['num_positions']}",
    ]

    console.print(Panel(
        "\n".join(header_lines),
        title="[bold cyan]Portfolio Overview[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED,
    ))

    # Positions table
    positions = enriched_positions or pd["positions"]
    has_analysis = enriched_positions is not None

    table = Table(
        title="Your Holdings",
        box=box.ROUNDED,
        show_lines=True,
        title_style="bold",
    )

    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Ticker", style="bold cyan", width=7)
    table.add_column("Shares", width=7, justify="center")
    table.add_column("Avg Price", width=10, justify="right")
    table.add_column("Current", width=10, justify="right")
    table.add_column("P&L $", width=12, justify="right")
    table.add_column("P&L %", width=8, justify="right")
    table.add_column("Value", width=12, justify="right")
    table.add_column("Weight", width=7, justify="center")
    if has_analysis:
        table.add_column("Score", width=6, justify="center")
        table.add_column("Action", width=10, justify="center")

    for i, pos in enumerate(positions, 1):
        pnl = pos["unrealized_pnl"]
        pnl_pct = pos["pnl_pct"]
        pnl_style = "green" if pnl >= 0 else "red"

        row = [
            str(i),
            pos["ticker"],
            str(pos["shares"]),
            f"${pos['avg_price']:.2f}",
            f"${pos['current_price']:.2f}",
            f"[{pnl_style}]${pnl:+,.2f}[/{pnl_style}]",
            f"[{pnl_style}]{pnl_pct:+.1f}%[/{pnl_style}]",
            f"${pos['market_value']:,.2f}",
            f"{pos['weight_pct']:.1f}%",
        ]

        if has_analysis:
            row.append(_style_score(pos.get("analysis_score", 50)))
            row.append(_style_position_action(pos.get("position_action", "HOLD")))

        table.add_row(*row)

    # Totals row
    total_row = [
        "",
        "[bold]TOTAL[/bold]",
        "",
        "",
        "",
        f"[bold {pnl_color}]${total_pnl:+,.2f}[/bold {pnl_color}]",
        f"[bold {pnl_color}]{pd['total_pnl_pct']:+.1f}%[/bold {pnl_color}]",
        f"[bold]${pd['total_market_value']:,.2f}[/bold]",
        "",
    ]
    if has_analysis:
        total_row.extend(["", ""])
    table.add_row(*total_row)

    console.print(table)

    # Sector exposure
    if sector_exposure:
        console.print()
        sector_lines = []
        for sector, data in sector_exposure.items():
            bar_len = int(data["pct"] / 2)
            sector_lines.append(
                f"  {sector:<28} [cyan]{'█' * bar_len}[/cyan] "
                f"{data['pct']:.1f}%  (${data['amount']:,.0f})"
            )
        console.print(Panel(
            "\n".join(sector_lines),
            title="[bold]Sector Exposure[/bold]",
            border_style="blue",
            box=box.ROUNDED,
        ))

    # Detailed action recommendations (only if analysis was run)
    if has_analysis:
        console.print()
        for pos in positions:
            action = pos.get("position_action", "HOLD")
            if action == "HOLD" and pos.get("analysis_score", 50) > 45:
                continue  # Skip boring HOLDs, only show actionable items

            color = {
                "ADD": "green", "HOLD": "yellow",
                "TRIM": "red", "SELL": "bold red",
            }.get(action, "white")

            lines = []

            # Step-by-step action instructions (new format)
            action_steps = pos.get("action_steps", [])
            if action_steps:
                for i, step in enumerate(action_steps, 1):
                    lines.append(f"  [bold]Step {i}:[/bold] {step}")
                lines.append("")

            # P&L / Score / Weight context
            pnl_c = "green" if pos["pnl_pct"] >= 0 else "red"
            lines.append(
                f"  [bold]P&L:[/bold] [{pnl_c}]${pos['unrealized_pnl']:+,.2f} "
                f"({pos['pnl_pct']:+.1f}%)[/{pnl_c}]  |  "
                f"[bold]Score:[/bold] {pos.get('analysis_score', 'N/A')}/100  |  "
                f"[bold]Weight:[/bold] {pos['weight_pct']:.1f}%"
            )

            # Reasons
            lines.append("")
            lines.append("[bold]Why:[/bold]")
            for reason in pos.get("reasons", []):
                lines.append(f"  {reason}")

            # Key signals
            key_signals = pos.get("key_signals", [])
            if key_signals:
                lines.append("")
                lines.append("[bold]Signals:[/bold]")
                for s in key_signals[:4]:
                    sig_color = "green" if s.get("type") == "bullish" else "red" if s.get("type") == "bearish" else "yellow"
                    lines.append(f"  [{sig_color}]{s.get('source', '')}: {s.get('detail', '')}[/{sig_color}]")

            # Summary line
            if pos.get("action_summary"):
                lines.append("")
                lines.append(f"  [bold dim]Summary:[/bold dim] {pos['action_summary']}")

            console.print(Panel(
                "\n".join(lines),
                title=f"[{color}]{action}[/{color}] — [bold cyan]{pos['ticker']}[/bold cyan] ({pos['shares']} shares)",
                border_style=color,
                box=box.ROUNDED,
            ))


def _style_position_action(action):
    """Color-code position actions."""
    styles = {
        "ADD": "[bold green]ADD[/bold green]",
        "HOLD": "[yellow]HOLD[/yellow]",
        "TRIM": "[red]TRIM[/red]",
        "SELL": "[bold red]SELL[/bold red]",
    }
    return styles.get(action, action)


def _style_order_type(order_type):
    """Color-code order types."""
    styles = {
        "Market": "[bold green]Market[/bold green]",
        "Limit": "[cyan]Limit[/cyan]",
        "Stop": "[yellow]Stop[/yellow]",
        "Stop Limit": "[yellow]Stop Limit[/yellow]",
        "Trailing Stop": "[magenta]Trail Stop[/magenta]",
    }
    return styles.get(order_type, order_type)


def display_progress(message, ticker=None, current=None, total=None):
    """Display progress updates during scanning."""
    parts = [message]
    if ticker:
        parts.append(f"[cyan]{ticker}[/cyan]")
    if current is not None and total is not None:
        parts.append(f"[{current}/{total}]")
    console.print(" ".join(parts))


def _style_action(action):
    """Color-code the action label."""
    colors = {
        "STRONG BUY": "[bold green]STRONG BUY[/bold green]",
        "BUY": "[green]BUY[/green]",
        "HOLD": "[yellow]HOLD[/yellow]",
        "SELL": "[red]SELL[/red]",
        "STRONG SELL": "[bold red]STRONG SELL[/bold red]",
    }
    return colors.get(action, action)


def _style_score(score):
    """Color-code a score value."""
    if score >= 75:
        return f"[bold green]{score:.0f}[/bold green]"
    elif score >= 60:
        return f"[green]{score:.0f}[/green]"
    elif score >= 45:
        return f"[yellow]{score:.0f}[/yellow]"
    elif score >= 30:
        return f"[red]{score:.0f}[/red]"
    else:
        return f"[bold red]{score:.0f}[/bold red]"


def _style_subscore(score):
    """Color-code a sub-score value (compact)."""
    if score >= 65:
        return f"[green]{score:.0f}[/green]"
    elif score >= 45:
        return f"[yellow]{score:.0f}[/yellow]"
    else:
        return f"[red]{score:.0f}[/red]"


def _color_pct(value):
    """Color-code a percentage value."""
    if value > 0:
        return f"[green]+{value:.1f}%[/green]"
    elif value < 0:
        return f"[red]{value:.1f}%[/red]"
    else:
        return f"{value:.1f}%"


def _score_bar(score, width=20):
    """Create a visual score bar."""
    filled = int(score / 100 * width)
    empty = width - filled

    if score >= 65:
        color = "green"
    elif score >= 45:
        color = "yellow"
    else:
        color = "red"

    return f"[{color}]{'█' * filled}{'░' * empty}[/{color}]"
