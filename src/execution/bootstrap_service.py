"""
Bootstrap Alpaca paper account from config/portfolio.yaml.

Submits a market BUY order for every holding so the paper account mirrors
the user's real positions (one-time setup, typically right after resetting
the paper account from the Alpaca dashboard).

Notes:
  * Bootstrap orders are NOT logged to paper_trading.db — they're not strategy
    recommendations and would skew calibration buckets.
  * Fractional shares are supported (Alpaca accepts fractional market orders).
  * If the market is closed, DAY orders queue for the next regular session.
"""

import logging

from rich.table import Table
from rich import box

from src.execution.alpaca import (
    AlpacaClient,
    AlpacaClientError,
    AlpacaDuplicateOrderError,
    make_client_order_id,
)
from src.execution.safety_gates import TradingHaltedError, TradingSafetyGate
from src.portfolio import Portfolio
from src.data.fetcher import DataFetcher
from src.data.cache import DataCache
from src.presentation.cli.cli_output import console

logger = logging.getLogger(__name__)


def run_paper_bootstrap(config, args):
    """Entry point for `paper bootstrap`."""
    yes = getattr(args, "yes", False)

    portfolio = Portfolio(config)
    holdings = portfolio.holdings
    if not holdings:
        console.print("[red]No holdings in config/portfolio.yaml — nothing to bootstrap.[/red]")
        return

    safety_gate = TradingSafetyGate.from_config(config)
    if not safety_gate.trading_enabled:
        console.print(
            "[yellow]trading_enabled is False — bootstrap orders will be "
            "refused at the broker boundary. Set STOCKNEW_TRADING_ENABLED=1 "
            "or trading.trading_enabled: true in settings.yaml.[/yellow]"
        )
    try:
        client = AlpacaClient(safety_gate=safety_gate)
    except AlpacaClientError as e:
        console.print(f"[red]Alpaca: {e}[/red]")
        return

    account = client.get_account()
    clock = client.get_clock()
    existing = {p["ticker"]: p for p in client.get_positions()}

    # Get current prices for cost preview
    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get("data", "market_hours_cache_minutes", default=5),
    )
    fetcher = DataFetcher(config, cache)

    plan = []
    total_est_cost = 0
    for h in holdings:
        ticker = h["ticker"].upper()
        shares = float(h["shares"])
        if shares <= 0:
            continue

        already = existing.get(ticker)
        rt = fetcher.fetch_realtime_price(ticker)
        current_px = rt.get("last_price") if rt else None
        if current_px is None or current_px <= 0:
            df = fetcher.fetch_price_data(ticker, period="5d")
            if df is not None and not df.empty:
                current_px = float(df["Close"].iloc[-1])

        est_cost = shares * current_px if current_px else None
        if est_cost:
            total_est_cost += est_cost

        plan.append({
            "ticker": ticker,
            "shares": shares,
            "current_price": current_px,
            "est_cost": est_cost,
            "already_held": already is not None,
            "yaml_avg_price": float(h.get("avg_price", 0)),
        })

    _display_plan(plan, account, clock, total_est_cost)

    if not yes:
        console.print(
            "\n  [yellow]Preview only.[/yellow] "
            "Re-run with [bold]--yes[/bold] to actually submit these orders.\n"
        )
        return

    if total_est_cost > account["cash"]:
        console.print(
            f"\n[red]Insufficient cash: estimated cost ${total_est_cost:,.2f} > "
            f"account cash ${account['cash']:,.2f}.[/red]\n"
            f"[yellow]Reset the paper account at "
            f"https://app.alpaca.markets/paper/dashboard/overview "
            f"with at least ${total_est_cost:,.0f} starting cash, then retry.[/yellow]\n"
        )
        return

    if not clock["is_open"]:
        console.print(
            f"\n  [yellow]Market is CLOSED. Submitting DAY orders — "
            f"they will queue and fill at next open ({clock['next_open']}).[/yellow]\n"
        )

    _submit_orders(client, plan)


def _display_plan(plan, account, clock, total_est_cost):
    table = Table(box=box.ROUNDED, title="Bootstrap Plan")
    table.add_column("Ticker", style="bold cyan")
    table.add_column("Shares", justify="right")
    table.add_column("Current $", justify="right")
    table.add_column("Est. Cost", justify="right")
    table.add_column("YAML Avg", justify="right")
    table.add_column("Status")

    for p in plan:
        if p["already_held"]:
            status = "[yellow]already in Alpaca — will skip[/yellow]"
        elif p["current_price"] is None:
            status = "[red]no price — cannot order[/red]"
        else:
            status = "[green]will buy[/green]"
        table.add_row(
            p["ticker"],
            f"{p['shares']:.4g}",
            f"${p['current_price']:.2f}" if p["current_price"] else "—",
            f"${p['est_cost']:,.2f}" if p["est_cost"] else "—",
            f"${p['yaml_avg_price']:.2f}",
            status,
        )

    console.print(table)
    console.print()
    market_state = "[green]OPEN[/green]" if clock["is_open"] else "[dim]CLOSED[/dim]"
    console.print(f"  Market:        {market_state}")
    console.print(f"  Account cash:  ${account['cash']:,.2f}")
    console.print(f"  Account equity: ${account['equity']:,.2f}")
    console.print(f"  Est. total cost: ${total_est_cost:,.2f}")


def _submit_orders(client, plan):
    submitted, skipped, failed = 0, 0, 0
    table = Table(box=box.ROUNDED, title="Bootstrap Submission")
    table.add_column("Ticker", style="bold cyan")
    table.add_column("Shares", justify="right")
    table.add_column("Result")

    for p in plan:
        ticker = p["ticker"]
        if p["already_held"]:
            table.add_row(ticker, f"{p['shares']:.4g}", "[yellow]skipped (already held)[/yellow]")
            skipped += 1
            continue
        if p["current_price"] is None:
            table.add_row(ticker, f"{p['shares']:.4g}", "[red]no price — skipped[/red]")
            skipped += 1
            continue
        client_order_id = make_client_order_id("bootstrap", ticker)
        try:
            order = client.submit_market_order(
                ticker, p["shares"], side="buy",
                client_order_id=client_order_id,
                reference_price=p.get("current_price"),
            )
            table.add_row(
                ticker,
                f"{p['shares']:.4g}",
                f"[green]submitted ({order['order_id'][:8]}, status={order['status']})[/green]",
            )
            submitted += 1
        except AlpacaDuplicateOrderError:
            table.add_row(
                ticker,
                f"{p['shares']:.4g}",
                "[yellow]skipped (already bootstrapped today)[/yellow]",
            )
            skipped += 1
        except TradingHaltedError as e:
            table.add_row(
                ticker,
                f"{p['shares']:.4g}",
                f"[red]safety gate refused: {e}[/red]",
            )
            skipped += 1
        except Exception as e:
            table.add_row(ticker, f"{p['shares']:.4g}", f"[red]failed: {e}[/red]")
            failed += 1

    console.print(table)
    console.print(
        f"\n  [bold]{submitted} submitted, {skipped} skipped, {failed} failed[/bold]\n"
        f"  [dim]Run `paper status` after market open to see fills, "
        f"then `paper sync` to mirror back to portfolio.yaml.[/dim]\n"
    )
