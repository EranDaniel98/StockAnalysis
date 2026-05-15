"""
Paper-trading auto-executor.

Pipeline:
  1. Run scanner (reuses src.main._analyze_and_score via lightweight scan helper)
  2. Filter recommendations by min score + earnings-blackout window
  3. For top N, submit Alpaca bracket orders (entry: market, stop_loss, take_profit
     from the recommendation's risk_management block)
  4. Persist every decision (submitted or skipped) into paper_trading.db

Whole-share constraint: Alpaca bracket orders require integer qty. We size each
order so that (qty * current_price) <= max_per_order_usd, with qty >= 1. If even
1 share exceeds the cap, we skip the trade.
"""

import logging
from datetime import datetime, date, timedelta

import yfinance as yf
from rich.table import Table
from rich import box

from src.execution.alpaca import (
    AlpacaClient,
    AlpacaClientError,
    AlpacaDuplicateOrderError,
    make_client_order_id,
)
from src.execution.paper_db import PaperDB
from src.presentation.cli.cli_output import console
from src.data.cache import DataCache
from src.data.fetcher import DataFetcher
from src.data.fundamentals import FundamentalsFetcher
from src.data.screener import StockScreener

logger = logging.getLogger(__name__)


# --- Defaults (tunable via CLI args) ---------------------------------------

DEFAULT_MIN_SCORE = 55
DEFAULT_TOP_N = 10
DEFAULT_EARNINGS_BLACKOUT_DAYS = 5
DEFAULT_MAX_PER_ORDER_USD = 1000  # cap per single bracket order


def run_paper_trade(config, args):
    """Entry point for `paper trade` CLI command."""
    from src.main import _analyze_and_score, _build_cache  # local to avoid cycle

    strategy_name = args.strategy or config.strategies.get("default_strategy", "default")
    strategy = config.get_strategy(strategy_name)

    min_score = getattr(args, "min_score", None) or DEFAULT_MIN_SCORE
    top_n = getattr(args, "top", None) or DEFAULT_TOP_N
    blackout_days = getattr(args, "earnings_blackout", None) or DEFAULT_EARNINGS_BLACKOUT_DAYS
    max_per_order = getattr(args, "max_per_order", None) or DEFAULT_MAX_PER_ORDER_USD
    dry_run = getattr(args, "dry_run", False)

    console.print(f"\n[bold cyan]Paper trade run[/bold cyan]")
    console.print(f"  Strategy: [bold]{strategy_name}[/bold]")
    console.print(f"  Gate: score >= {min_score}, top {top_n}, earnings blackout {blackout_days}d")
    console.print(f"  Max per order: ${max_per_order}")
    if dry_run:
        console.print(f"  [yellow]DRY RUN — no orders will be submitted[/yellow]")
    console.print()

    # --- Connect Alpaca first so we fail fast on bad keys ---
    try:
        client = AlpacaClient()
    except AlpacaClientError as e:
        console.print(f"[red]Alpaca: {e}[/red]")
        return

    account = client.get_account()
    console.print(
        f"  [dim]Account equity ${account['equity']:,.2f}, "
        f"buying power ${account['buying_power']:,.2f}[/dim]\n"
    )

    # --- Run the scanner ---
    cache = _build_cache(config, args)
    screener = StockScreener(config, cache)
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    console.print("[bold]Discovering stocks...[/bold]")
    if getattr(args, "theme", None):
        tickers = screener.discover(theme_filter=args.theme)
    elif getattr(args, "sector", None):
        tickers = screener.discover(sector_filter=args.sector)
    else:
        tickers = screener.discover_by_sectors()

    console.print(f"  Found {len(tickers)} candidates\n")
    if not tickers:
        console.print("[red]No tickers to analyze.[/red]")
        return

    fundamentals_map = fund_fetcher.fetch_batch(tickers)
    filtered = screener.stage2_filter(tickers, fundamentals_map)
    price_data_map = fetcher.fetch_batch(filtered)

    recommendations = _analyze_and_score(
        price_data_map, fundamentals_map, config, strategy
    )

    # --- Gate ---
    qualified = [
        r for r in recommendations
        if r["composite_score"] >= min_score
        and r["action"] in ("BUY", "STRONG BUY", "HOLD")  # don't trade SELL signals
        and r.get("risk_management", {}).get("stop_loss", {}).get("price")
        and r.get("risk_management", {}).get("take_profit", {}).get("price")
    ][:top_n]

    if not qualified:
        console.print(
            f"[yellow]No recommendations met the gate "
            f"(score >= {min_score}, BUY/STRONG BUY/HOLD).[/yellow]\n"
        )
        return

    console.print(f"[bold]Evaluating {len(qualified)} qualified recommendations...[/bold]\n")

    # --- Open positions to avoid double-buying ---
    open_tickers = {p["ticker"] for p in client.get_positions()}

    # --- Submit / log ---
    db = PaperDB()
    try:
        results = []
        for rec in qualified:
            outcome = _process_recommendation(
                rec, strategy_name, client, db,
                open_tickers, max_per_order, blackout_days, dry_run,
            )
            results.append(outcome)
    finally:
        db.close()

    _display_summary(results, dry_run)


def _process_recommendation(rec, strategy_name, client, db,
                            open_tickers, max_per_order, blackout_days, dry_run):
    """Decide + submit (or skip) a single recommendation. Returns outcome dict."""
    ticker = rec["ticker"]
    score = rec["composite_score"]
    rm = rec.get("risk_management", {})
    current_price = rm.get("current_price")
    stop_loss = rm.get("stop_loss", {}).get("price")
    take_profit = rm.get("take_profit", {}).get("price")
    sub_scores = rec.get("sub_scores", {})
    sector = rec.get("sector", "Unknown")

    skip_reason = None
    if ticker in open_tickers:
        skip_reason = "already_open_in_alpaca"
    elif current_price is None or current_price <= 0:
        skip_reason = "missing_price"
    elif stop_loss is None or take_profit is None:
        skip_reason = "missing_risk_levels"
    elif stop_loss >= current_price or take_profit <= current_price:
        skip_reason = f"invalid_levels (sl={stop_loss}, tp={take_profit}, px={current_price})"

    earnings_in_days = _days_to_next_earnings(ticker)
    if skip_reason is None and earnings_in_days is not None and earnings_in_days <= blackout_days:
        skip_reason = f"earnings_in_{earnings_in_days}d"

    qty = 0
    if skip_reason is None:
        qty = int(max_per_order // current_price)
        if qty < 1:
            skip_reason = f"too_expensive (1 share = ${current_price:.2f} > ${max_per_order})"

    rec_id = db.insert_recommendation(
        ticker=ticker,
        strategy=strategy_name,
        composite_score=score,
        action=rec["action"],
        sub_scores=sub_scores,
        entry_price=current_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        sector=sector,
        earnings_in_days=earnings_in_days,
        submitted=False,
        skip_reason=skip_reason,
    )

    outcome = {
        "ticker": ticker,
        "score": score,
        "action": rec["action"],
        "qty": qty,
        "entry": current_price,
        "stop": stop_loss,
        "target": take_profit,
        "earnings_in_days": earnings_in_days,
        "skip_reason": skip_reason,
        "submitted": False,
        "order_id": None,
    }

    if skip_reason is not None:
        return outcome

    if dry_run:
        outcome["skip_reason"] = "dry_run"
        return outcome

    client_order_id = make_client_order_id(strategy_name, ticker)
    try:
        order = client.submit_bracket_order(
            ticker=ticker,
            qty=qty,
            take_profit_price=take_profit,
            stop_loss_price=stop_loss,
            side="buy",
            client_order_id=client_order_id,
        )
        db.insert_order(rec_id, order, take_profit, stop_loss)
        db.mark_recommendation_submitted(rec_id)
        outcome["submitted"] = True
        outcome["order_id"] = order["order_id"]
    except AlpacaDuplicateOrderError:
        logger.warning(
            "Duplicate client_order_id rejected by Alpaca for %s (%s) — "
            "already submitted today; skipping to prevent double-fill.",
            ticker,
            client_order_id,
        )
        outcome["skip_reason"] = "already_submitted_today"
    except Exception as e:
        logger.error(f"Failed to submit {ticker}: {e}")
        outcome["skip_reason"] = f"submit_failed: {e}"
    return outcome


def _days_to_next_earnings(ticker):
    """Return integer days until next earnings, or None if unknown/past."""
    try:
        cal = yf.Ticker(ticker).calendar
        if cal is None:
            return None
        next_dt = None
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if isinstance(ed, list) and ed:
                next_dt = ed[0]
            else:
                next_dt = ed
        else:
            try:
                next_dt = cal.loc["Earnings Date"].iloc[0]
            except Exception:
                return None
        if next_dt is None:
            return None
        if hasattr(next_dt, "date"):
            next_dt = next_dt.date()
        if not isinstance(next_dt, date):
            return None
        delta = (next_dt - date.today()).days
        return delta if delta >= 0 else None
    except Exception as e:
        logger.debug(f"Earnings lookup failed for {ticker}: {e}")
        return None


def _display_summary(results, dry_run):
    table = Table(box=box.ROUNDED, title="Paper Trade Run — Decisions", show_lines=False)
    table.add_column("Ticker", style="bold cyan")
    table.add_column("Score", justify="right")
    table.add_column("Action", justify="center")
    table.add_column("Qty", justify="right")
    table.add_column("Entry", justify="right")
    table.add_column("Stop", justify="right")
    table.add_column("Target", justify="right")
    table.add_column("Earn(d)", justify="right")
    table.add_column("Outcome")

    submitted = 0
    skipped = 0
    for r in results:
        if r["submitted"]:
            outcome_text = f"[green]SUBMITTED {r['order_id'][:8]}[/green]"
            submitted += 1
        elif r["skip_reason"] == "dry_run":
            outcome_text = "[yellow]would submit[/yellow]"
        else:
            outcome_text = f"[dim]skip:[/dim] {r['skip_reason']}"
            skipped += 1

        table.add_row(
            r["ticker"],
            f"{r['score']:.1f}",
            r["action"],
            str(r["qty"]) if r["qty"] else "—",
            f"${r['entry']:.2f}" if r["entry"] else "—",
            f"${r['stop']:.2f}" if r["stop"] else "—",
            f"${r['target']:.2f}" if r["target"] else "—",
            str(r["earnings_in_days"]) if r["earnings_in_days"] is not None else "—",
            outcome_text,
        )

    console.print(table)
    if dry_run:
        console.print(f"\n  [yellow]Dry run: {len(results)} evaluated, none sent.[/yellow]\n")
    else:
        console.print(f"\n  [bold]{submitted} submitted, {skipped} skipped[/bold]\n")
