"""
Stock Market Scanner - Main CLI Entry Point

Usage:
    python -m src.main scan [--strategy NAME] [--sector SECTOR] [--theme THEME] [--top N]
    python -m src.main analyze TICKER [TICKER ...] [--strategy NAME]
    python -m src.main trending
    python -m src.main alert [--strategy NAME]
    python -m src.main watchlist [--strategy NAME]
    python -m src.main strategies
    python -m src.main help [TOPIC]
    python -m src.main cache --clear
"""

import argparse
import logging
import sys
from pathlib import Path

# Allow `python src/cli/main.py` to work alongside `python -m src.cli.main`
# by adding the repo root to sys.path. `python -m` already handles this.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.config_loader import Config
from src.data.cache import DataCache
from src.data.fetcher import DataFetcher
from src.data.fundamentals import FundamentalsFetcher
from src.data.screener import StockScreener
from src.scoring.analyzers import technical, fundamental, patterns, statistical, alpha158
from src.scoring.analyzers.trend_detector import analyze_stock_trend, detect_trending_sectors
from src.scoring.engine import calculate_composite_score, batch_score
from src.scoring.recommender import generate_recommendation, check_diversification, allocate_portfolio
from src.scoring.service import analyze_and_score
from src.presentation.cli.cli_output import (
    console,
    display_scan_results,
    display_stock_detail,
    display_trending_sectors,
    display_diversification_warnings,
    display_investment_plan,
    display_portfolio,
)
from src.alerts.telegram_bot import TelegramAlerter
from src.portfolio import Portfolio
from src.help_system import show_help

logger = logging.getLogger(__name__)


def _analyze_and_score(price_data_map, fundamentals_map, config, strategy):
    """CLI-flavored wrapper: keeps the legacy per-ticker Rich-console print
    that users expect, then delegates to the bounded-context implementation
    in ``src.scoring.service.analyze_and_score`` for the actual work."""
    total = len(price_data_map)

    def emit(event):
        stage = event.get("stage")
        if stage == "analyze_ticker_start":
            console.print(
                f"  Analyzing [{event['i']}/{event['n']}]: [cyan]{event['ticker']}[/cyan]"
            )
        elif stage == "score_start":
            console.print(
                f"\n  Analysis complete: {event['n_analyzed']}/{total} stocks\n"
            )

    return analyze_and_score(
        price_data_map, fundamentals_map, config, strategy, on_event=emit
    )


def main():
    parser = argparse.ArgumentParser(
        description="Stock Market Scanner - AI-powered stock analysis and recommendations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- Shared arguments added to multiple parsers ---
    def add_common_args(p):
        p.add_argument("--strategy", "-s", type=str, default=None, help="Strategy name to use")
        p.add_argument("--budget", "-b", type=float, default=None, help="Total budget to invest (e.g., --budget 50000)")
        p.add_argument("--fresh", action="store_true", help="Bypass cache, fetch live data (important during market hours)")

    # --- scan command ---
    scan_parser = subparsers.add_parser("scan", help="Scan the market for opportunities")
    add_common_args(scan_parser)
    scan_parser.add_argument("--sector", type=str, default=None, help="Sector key to focus on")
    scan_parser.add_argument("--theme", type=str, default=None, help="Theme key to focus on")
    scan_parser.add_argument("--top", type=int, default=None, help="Number of top results to show")
    scan_parser.add_argument("--no-alert", action="store_true", help="Skip sending Telegram alerts")

    # --- analyze command ---
    analyze_parser = subparsers.add_parser("analyze", help="Deep analyze specific tickers")
    analyze_parser.add_argument("tickers", nargs="+", type=str, help="Ticker symbols to analyze")
    add_common_args(analyze_parser)

    # --- trending command ---
    trending_parser = subparsers.add_parser("trending", help="Show trending sectors and themes")
    trending_parser.add_argument("--fresh", action="store_true", help="Bypass cache, fetch live data")

    # --- alert command ---
    alert_parser = subparsers.add_parser("alert", help="Run scan and send Telegram alerts")
    add_common_args(alert_parser)

    # --- watchlist command ---
    wl_parser = subparsers.add_parser("watchlist", help="Analyze watchlist stocks")
    add_common_args(wl_parser)

    # --- portfolio command ---
    port_parser = subparsers.add_parser("portfolio", help="View your portfolio and get position recommendations")
    add_common_args(port_parser)
    port_parser.add_argument("--analyze", "-a", action="store_true", help="Run full analysis on holdings")

    # --- strategies command ---
    subparsers.add_parser("strategies", help="List available strategies")

    # --- help command ---
    help_parser = subparsers.add_parser("help", help="Detailed help on any topic")
    help_parser.add_argument(
        "topic", nargs="?", default=None,
        help="Topic: overview, strategies, scan, setup, indicators, scoring, risk, config, enhance, missing, commands, glossary",
    )

    # --- cache command ---
    cache_parser = subparsers.add_parser("cache", help="Manage data cache")
    cache_parser.add_argument("--clear", action="store_true", help="Clear all cached data")
    cache_parser.add_argument("--stats", action="store_true", help="Show cache statistics")

    # --- paper command (Alpaca paper trading + validation loop) ---
    paper_parser = subparsers.add_parser(
        "paper", help="Alpaca paper trading: status, sync, trade, evaluate"
    )
    paper_sub = paper_parser.add_subparsers(dest="paper_cmd", help="Paper trading subcommand")

    paper_sub.add_parser("status", help="Show Alpaca account, positions, market clock")

    p_sync = paper_sub.add_parser(
        "sync", help="Pull positions from Alpaca and rewrite portfolio.yaml"
    )
    p_sync.add_argument(
        "--no-write", action="store_true",
        help="Display only — do not modify portfolio.yaml",
    )

    p_trade = paper_sub.add_parser(
        "trade", help="Run scan and submit paper bracket orders for top recommendations"
    )
    add_common_args(p_trade)
    p_trade.add_argument("--sector", type=str, default=None)
    p_trade.add_argument("--theme", type=str, default=None)
    p_trade.add_argument("--top", type=int, default=None, help="Max orders to submit (default 10)")
    p_trade.add_argument("--min-score", type=float, default=None, dest="min_score",
                         help="Minimum composite score (default 55)")
    p_trade.add_argument("--earnings-blackout", type=int, default=None, dest="earnings_blackout",
                         help="Skip stocks with earnings within N days (default 5)")
    p_trade.add_argument("--max-per-order", type=float, default=None, dest="max_per_order",
                         help="Max USD per single bracket order (default 1000)")
    p_trade.add_argument("--dry-run", action="store_true", dest="dry_run",
                         help="Evaluate + log decisions but do not submit orders")

    p_eval = paper_sub.add_parser(
        "evaluate", help="Reconcile closed trades and show score calibration"
    )
    p_eval.add_argument("--days", type=int, default=None,
                        help="Lookback window for Alpaca order history (default 90)")

    p_boot = paper_sub.add_parser(
        "bootstrap",
        help="Submit market buy orders to recreate portfolio.yaml holdings in Alpaca",
    )
    p_boot.add_argument("--yes", action="store_true",
                        help="Actually submit (default is preview-only)")

    # --- backtest command ---
    bt_parser = subparsers.add_parser(
        "backtest",
        help="Walk-forward backtest of the scoring engine over historical data",
    )
    bt_parser.add_argument("--strategy", "-s", type=str, default=None)
    bt_parser.add_argument("--universe", type=str, default="watchlist",
                           choices=["watchlist", "portfolio", "themes"],
                           help="Ticker universe to test against")
    bt_parser.add_argument("--tickers", type=str, default=None,
                           help="Comma-separated tickers (overrides --universe)")
    bt_parser.add_argument("--years", type=float, default=3.0,
                           help="Backtest window length (default 3 years)")
    bt_parser.add_argument("--start", type=str, default=None,
                           help="Start date YYYY-MM-DD (overrides --years)")
    bt_parser.add_argument("--end", type=str, default=None,
                           help="End date YYYY-MM-DD (default: today)")
    bt_parser.add_argument("--min-score", type=float, default=None, dest="min_score",
                           help="Minimum composite to enter a trade")
    bt_parser.add_argument("--hold-days", type=int, default=90, dest="hold_days",
                           help="Max days to hold before timeout exit (default 90)")
    bt_parser.add_argument("--cash", type=float, default=10000.0,
                           help="Starting simulated cash (default $10000)")
    bt_parser.add_argument("--max-positions", type=int, default=20, dest="max_positions",
                           help="Max simultaneous open positions (default 20)")
    bt_parser.add_argument("--position-pct", type=float, default=0.10, dest="position_pct",
                           help="Fraction of starting cash per position (default 0.10)")
    bt_parser.add_argument("--compound", action="store_true",
                           help="Compound: budget = (cash + book value) * position-pct (default off)")
    bt_parser.add_argument("--commission", type=float, default=0.0,
                           help="$ commission per trade (default 0)")
    bt_parser.add_argument("--slippage-bps", type=float, default=5.0, dest="slippage_bps",
                           help="Slippage in bps each side (default 5)")
    bt_parser.add_argument("--regulatory-bps", type=float, default=3.0, dest="regulatory_bps",
                           help="Regulatory bps on sale, SEC+FINRA (default 3)")
    bt_parser.add_argument("--earnings-blackout", type=int, default=3, dest="earnings_blackout",
                           help="Skip entries within +/- N days of earnings (default 3, 0=disable)")
    bt_parser.add_argument("--accept-lookahead", action="store_true", dest="accept_lookahead",
                           help="Bypass fundamentals lookahead guard (results invalid)")
    bt_parser.add_argument("--oos-split", type=float, default=0.30, dest="oos_split",
                           help="Fraction of window held out for OOS validation (default 0.30)")
    bt_parser.add_argument("--bootstrap-resamples", type=int, default=2000, dest="bootstrap_resamples",
                           help="Bootstrap resamples for CIs (default 2000, 0 disables)")
    bt_parser.add_argument("--vol-target-risk", type=float, default=0.0, dest="vol_target_risk",
                           help="Risk fraction per trade (e.g. 0.01 = 1%%); 0 = fixed-fractional sizing")
    bt_parser.add_argument("--compare", action="store_true",
                           help="Run all strategies side-by-side on the same window/universe")
    bt_parser.add_argument("--sweep", nargs="?", const="default", default=None,
                           help="Parameter sweep. Pass nothing for default grid, or "
                                "'min_score=55,60;atr_stop_mult=1.5,2'")
    bt_parser.add_argument("--html-report", type=str, default=None, dest="html_report",
                           help="Render charts as embedded base64 PNGs in a self-contained HTML file")
    bt_parser.add_argument("--quantstats-report", type=str, default=None, dest="quantstats_report",
                           help="Render a quantstats tearsheet (canonical retail tearsheet library) to HTML path")
    bt_parser.add_argument("--save", type=str, default=None,
                           help="Optional JSON path to save full results")

    # --- diagnose command (alphalens IC analysis) ---
    diag_parser = subparsers.add_parser(
        "diagnose",
        help="Alphalens IC diagnostic — does our composite score predict forward returns?",
    )
    diag_parser.add_argument("--strategy", "-s", type=str, default=None)
    diag_parser.add_argument("--universe", type=str, default="themes",
                             choices=["watchlist", "portfolio", "themes"])
    diag_parser.add_argument("--tickers", type=str, default=None,
                             help="Comma-separated tickers (overrides --universe)")
    diag_parser.add_argument("--years", type=float, default=3.0)
    diag_parser.add_argument("--factor", type=str, default="composite",
                             choices=["composite", "technical", "fundamental", "pattern",
                                      "statistical", "trend", "alpha158"],
                             help="Which sub-score to analyze (default composite)")
    diag_parser.add_argument("--quantiles", type=int, default=5)
    diag_parser.add_argument("--periods", type=str, default="1,5,21",
                             help="Forward-return periods in days, comma-separated")
    diag_parser.add_argument("--html-report", type=str, default=None, dest="html_report")
    diag_parser.add_argument("--accept-lookahead", action="store_true", dest="accept_lookahead")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Help doesn't need config
    if args.command == "help":
        show_help(args.topic)
        return

    # Initialize config
    try:
        config = Config()
    except FileNotFoundError as e:
        console.print(f"[red]Configuration error: {e}[/red]")
        return

    # Execute command
    if args.command == "scan":
        cmd_scan(config, args)
    elif args.command == "analyze":
        cmd_analyze(config, args)
    elif args.command == "trending":
        cmd_trending(config, args)
    elif args.command == "alert":
        cmd_alert(config, args)
    elif args.command == "watchlist":
        cmd_watchlist(config, args)
    elif args.command == "portfolio":
        cmd_portfolio(config, args)
    elif args.command == "strategies":
        cmd_strategies(config)
    elif args.command == "cache":
        cmd_cache(config, args)
    elif args.command == "paper":
        cmd_paper(config, args)
    elif args.command == "backtest":
        cmd_backtest(config, args)
    elif args.command == "diagnose":
        cmd_diagnose(config, args)


def _build_cache(config, args):
    """Build a DataCache with market-hours awareness and --fresh support."""
    from src.data.cache import is_market_open

    force_fresh = getattr(args, "fresh", False)
    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get("data", "market_hours_cache_minutes", default=5),
        force_fresh=force_fresh,
    )

    if is_market_open():
        cache_min = config.get("data", "market_hours_cache_minutes", default=5)
        console.print(f"  [yellow]Market is OPEN — price cache expires every {cache_min} minutes[/yellow]")
        if force_fresh:
            console.print(f"  [yellow]--fresh flag: all cache bypassed, fetching live data[/yellow]")
    elif force_fresh:
        console.print(f"  [dim]--fresh flag: all cache bypassed[/dim]")

    return cache


def cmd_scan(config, args):
    """Full market scan: discover -> filter -> analyze -> score -> display."""
    strategy_name = args.strategy
    strategy = config.get_strategy(strategy_name)
    if strategy_name is None:
        strategy_name = config.strategies.get("default_strategy", "default")

    console.print(f"\n[bold cyan]Starting market scan...[/bold cyan]")
    console.print(f"Strategy: [bold]{strategy_name}[/bold] - {strategy.get('description', '')}")
    console.print()

    cache = _build_cache(config, args)
    screener = StockScreener(config, cache)
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    # Stage 1: Discover stocks
    console.print("[bold]Stage 1: Discovering stocks...[/bold]")
    if args.theme:
        tickers = screener.discover(theme_filter=args.theme)
    elif args.sector:
        tickers = screener.discover(sector_filter=args.sector)
    else:
        tickers = screener.discover_by_sectors()
    console.print(f"  Found {len(tickers)} stocks for analysis\n")

    if not tickers:
        console.print("[red]No stocks found. Check your config filters.[/red]")
        return

    # Fetch fundamentals for stage 2 filtering
    console.print("[bold]Stage 2: Filtering by fundamentals...[/bold]")
    fundamentals_map = fund_fetcher.fetch_batch(tickers)
    filtered_tickers = screener.stage2_filter(tickers, fundamentals_map)
    console.print(f"  Filtered to {len(filtered_tickers)} stocks for deep analysis\n")

    # Fetch price data for filtered stocks
    console.print("[bold]Stage 3: Fetching price data...[/bold]")
    price_data_map = fetcher.fetch_batch(filtered_tickers)
    console.print(f"  Got price data for {len(price_data_map)} stocks\n")

    # Run analysis and scoring
    console.print("[bold]Stage 4: Running analysis engines...[/bold]")
    recommendations = _analyze_and_score(
        price_data_map, fundamentals_map, config, strategy
    )

    # Display results
    top_n = args.top or config.get("display", "top_n_results", default=20)
    config.settings.setdefault("display", {})["top_n_results"] = top_n
    display_scan_results(recommendations, config, strategy_name)

    # Portfolio allocation if budget specified
    budget = getattr(args, "budget", None)
    if budget:
        plan = allocate_portfolio(recommendations, budget, config, strategy=strategy)
        display_investment_plan(plan)
    else:
        # Just show diversification warnings
        warnings = check_diversification(recommendations, config)
        display_diversification_warnings(warnings)

    # Send alerts if not disabled
    if not getattr(args, "no_alert", False):
        alerter = TelegramAlerter(config)
        alerter.send_summary(recommendations, strategy_name)
        alerter.send_alerts(recommendations)


def cmd_analyze(config, args):
    """Deep analyze specific tickers."""
    strategy_name = args.strategy
    strategy = config.get_strategy(strategy_name)
    tickers = [t.upper() for t in args.tickers]

    console.print(f"\n[bold cyan]Analyzing {len(tickers)} stock(s)...[/bold cyan]\n")

    cache = _build_cache(config, args)
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    price_data_map = fetcher.fetch_batch(tickers)
    fundamentals_map = fund_fetcher.fetch_batch(tickers)

    recommendations = _analyze_and_score(
        price_data_map, fundamentals_map, config, strategy
    )

    display_scan_results(recommendations, config, strategy_name)

    budget = getattr(args, "budget", None)
    if budget:
        plan = allocate_portfolio(recommendations, budget, config, strategy=strategy)
        display_investment_plan(plan)


def cmd_trending(config, args):
    """Show trending sectors and themes."""
    console.print(f"\n[bold cyan]Analyzing sector trends...[/bold cyan]\n")

    cache = _build_cache(config, args)
    screener = StockScreener(config, cache)
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    # Get a broad set of stocks across sectors
    tickers = screener.discover_by_sectors()
    console.print(f"  Analyzing {len(tickers)} stocks across sectors\n")

    # Fetch data (use shorter period for trend detection)
    price_data_map = fetcher.fetch_batch(tickers, period="6mo")
    fundamentals_map = fund_fetcher.fetch_batch(tickers)

    # Detect trending sectors
    sector_trends = detect_trending_sectors(price_data_map, fundamentals_map, config)

    table_style = config.get("display", "table_style", default="rounded")
    display_trending_sectors(sector_trends, table_style)


def cmd_alert(config, args):
    """Run scan and send Telegram alerts."""
    args.no_alert = False
    args.sector = None
    args.theme = None
    args.top = None
    if not hasattr(args, "budget"):
        args.budget = None
    cmd_scan(config, args)


def cmd_watchlist(config, args):
    """Analyze watchlist stocks."""
    strategy_name = args.strategy
    strategy = config.get_strategy(strategy_name)
    tickers = config.get_watchlist()

    if not tickers:
        console.print("[red]No tickers in watchlist. Add them in config/sectors.yaml[/red]")
        return

    console.print(f"\n[bold cyan]Analyzing watchlist ({len(tickers)} stocks)...[/bold cyan]\n")

    cache = _build_cache(config, args)
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    price_data_map = fetcher.fetch_batch(tickers)
    fundamentals_map = fund_fetcher.fetch_batch(tickers)

    recommendations = _analyze_and_score(
        price_data_map, fundamentals_map, config, strategy
    )

    display_scan_results(recommendations, config, strategy_name)

    budget = getattr(args, "budget", None)
    if budget:
        plan = allocate_portfolio(recommendations, budget, config, strategy=strategy)
        display_investment_plan(plan)
    else:
        warnings = check_diversification(recommendations, config)
        display_diversification_warnings(warnings)


def cmd_portfolio(config, args):
    """View portfolio, P&L, and get position-level recommendations."""
    portfolio = Portfolio(config)
    tickers = portfolio.get_tickers()

    if not tickers:
        console.print("[red]No holdings found. Add them in config/portfolio.yaml[/red]")
        return

    console.print(f"\n[bold cyan]Loading portfolio ({len(tickers)} positions)...[/bold cyan]\n")

    cache = _build_cache(config, args)
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    # Get current prices for P&L (parallel)
    current_prices = {}
    rt_map = fetcher.fetch_realtime_batch(tickers)
    missing = []
    for ticker in tickers:
        rt = rt_map.get(ticker)
        if rt and rt.get("last_price"):
            current_prices[ticker] = rt["last_price"]
        else:
            missing.append(ticker)
    # Fallback to latest close from history for any that didn't return realtime
    if missing:
        fallback = fetcher.fetch_batch(missing, period="5d")
        for ticker, df in fallback.items():
            if df is not None and not df.empty:
                current_prices[ticker] = float(df["Close"].iloc[-1])

    # Calculate P&L
    positions_data = portfolio.calculate_positions(current_prices)

    # Get fundamentals for sector info
    fundamentals_map = fund_fetcher.fetch_batch(tickers)
    sector_exposure = portfolio.get_sector_exposure(positions_data, fundamentals_map)

    if args.analyze:
        # Run full analysis on holdings
        strategy_name = args.strategy
        strategy = config.get_strategy(strategy_name)

        console.print("[bold]Running analysis on holdings...[/bold]\n")
        price_data_map = fetcher.fetch_batch(tickers)

        recommendations = _analyze_and_score(
            price_data_map, fundamentals_map, config, strategy
        )

        # Build lookup for recommendations
        rec_map = {r["ticker"]: r for r in recommendations}
        enriched = portfolio.recommend_actions(positions_data, rec_map)

        display_portfolio(positions_data, enriched, sector_exposure)

        # If budget specified, show how to invest new cash
        budget = getattr(args, "budget", None)
        if budget is None and portfolio.cash_available > 0:
            budget = portfolio.cash_available
            console.print(
                f"\n  [dim]Using cash_available from portfolio.yaml: "
                f"${budget:,.2f}[/dim]\n"
            )

        if budget and budget > 0:
            # Portfolio-aware allocation: factor in existing sector exposure
            plan = allocate_portfolio(recommendations, budget, config, strategy=strategy)
            if plan["allocations"]:
                console.print(
                    "\n  [bold cyan]How to invest your available cash"
                    " (considering existing holdings):[/bold cyan]"
                )
                display_investment_plan(plan)
    else:
        display_portfolio(positions_data, sector_exposure=sector_exposure)
        console.print(
            "  [dim]Tip: Use --analyze to get action recommendations "
            "for each position[/dim]\n"
        )


def cmd_strategies(config):
    """List all available strategies."""
    from rich.table import Table
    from rich import box

    console.print("\n[bold cyan]Available Strategies[/bold cyan]\n")

    table = Table(box=box.ROUNDED, show_lines=True)
    table.add_column("Name", style="bold cyan")
    table.add_column("Description")
    table.add_column("Time Horizon")
    table.add_column("Tech", justify="center")
    table.add_column("Fund", justify="center")
    table.add_column("Pattern", justify="center")
    table.add_column("Stat", justify="center")
    table.add_column("Trend", justify="center")

    default = config.strategies.get("default_strategy", "")
    for name in config.get_strategy_names():
        s = config.get_strategy(name)
        w = s.get("weights", {})
        display_name = f"{name} *" if name == default else name

        table.add_row(
            display_name,
            s.get("description", ""),
            s.get("time_horizon", "N/A"),
            f"{w.get('technical', 0)*100:.0f}%",
            f"{w.get('fundamental', 0)*100:.0f}%",
            f"{w.get('pattern', 0)*100:.0f}%",
            f"{w.get('statistical', 0)*100:.0f}%",
            f"{w.get('trend', 0)*100:.0f}%",
        )

    console.print(table)
    console.print(f"\n  [dim]* = default strategy[/dim]")
    console.print(f"  [dim]Use --strategy NAME to select a strategy[/dim]\n")


def cmd_cache(config, args):
    """Manage data cache."""
    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get("data", "market_hours_cache_minutes", default=5),
    )

    if args.clear:
        cache.clear()
        console.print("[green]Cache cleared successfully[/green]")
    elif args.stats:
        stats = cache.get_stats()
        market_status = "[green]OPEN[/green]" if stats["market_open"] else "[dim]CLOSED[/dim]"
        console.print(f"\n[bold]Cache Statistics:[/bold]")
        console.print(f"  Market status:   {market_status}")
        console.print(f"  Price expiry:    {stats['price_cache_expiry']}")
        console.print(f"  Total entries:   {stats['total_entries']}")
        console.print(f"  Valid entries:   {stats['valid_entries']}")
        console.print(f"  Expired entries: {stats['expired_entries']}\n")
    else:
        console.print("Use --clear to clear cache or --stats to view statistics")


def cmd_paper(config, args):
    """Dispatch `paper` subcommands."""
    sub = getattr(args, "paper_cmd", None)
    if sub is None:
        console.print(
            "[yellow]Usage: paper {status|sync|bootstrap|trade|evaluate}[/yellow]\n"
            "  status    — show Alpaca account & positions\n"
            "  sync      — pull positions into portfolio.yaml\n"
            "  bootstrap — recreate portfolio.yaml holdings as paper orders\n"
            "  trade     — run scan + submit bracket orders\n"
            "  evaluate  — calibration report from closed trades\n"
        )
        return

    from src.execution.alpaca import AlpacaClient, AlpacaClientError

    if sub == "status":
        try:
            client = AlpacaClient()
        except AlpacaClientError as e:
            console.print(f"[red]Alpaca: {e}[/red]")
            return
        from src.execution.sync_service import _display_account, _display_positions
        account = client.get_account()
        positions = client.get_positions()
        clock = client.get_clock()
        _display_account(account)
        _display_positions(positions)
        market = "[green]OPEN[/green]" if clock["is_open"] else "[dim]CLOSED[/dim]"
        console.print(f"  Market: {market}  (next open: {clock['next_open']})\n")

    elif sub == "sync":
        from src.execution.sync_service import sync_portfolio
        try:
            sync_portfolio(config, write=not getattr(args, "no_write", False))
        except AlpacaClientError as e:
            console.print(f"[red]Alpaca: {e}[/red]")

    elif sub == "trade":
        from src.execution.paper_trade_service import run_paper_trade
        run_paper_trade(config, args)

    elif sub == "evaluate":
        from src.execution.paper_evaluate_service import run_paper_evaluate
        run_paper_evaluate(config, args)

    elif sub == "bootstrap":
        from src.execution.bootstrap_service import run_paper_bootstrap
        run_paper_bootstrap(config, args)


def cmd_backtest(config, args):
    """Walk-forward backtest of the scoring engine over historical data."""
    import json
    import pandas as pd

    from src.backtest.engine import (
        BacktestConfig, LookaheadGuardError,
        fetch_earnings_dates, fetch_earnings_history, run_backtest,
    )
    from src.backtest.display import display_backtest_results

    strategy_name = args.strategy or config.strategies.get("default_strategy", "long_term_growth")
    strategy = config.get_strategy(strategy_name)

    # Resolve universe
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        universe_label = f"custom ({len(tickers)} tickers)"
    elif args.universe == "portfolio":
        from src.portfolio import Portfolio
        tickers = Portfolio(config).get_tickers()
        universe_label = f"portfolio ({len(tickers)})"
    elif args.universe == "themes":
        tickers = config.get_theme_tickers()
        universe_label = f"themes ({len(tickers)})"
    else:
        tickers = config.get_watchlist()
        universe_label = f"watchlist ({len(tickers)})"

    if not tickers:
        console.print(f"[red]No tickers found for universe '{args.universe}'[/red]")
        return

    # Resolve dates
    end = pd.Timestamp(args.end) if args.end else pd.Timestamp.now().normalize()
    start = pd.Timestamp(args.start) if args.start else end - pd.Timedelta(days=int(365.25 * args.years))

    # Need extra history before start_date for SMA200 etc.
    fetch_period_years = max(args.years + 2, 5)
    fetch_period = f"{int(fetch_period_years)}y"

    console.print(f"\n[bold cyan]Backtest[/bold cyan]")
    console.print(f"  Strategy: [bold]{strategy_name}[/bold]")
    console.print(f"  Universe: [bold]{universe_label}[/bold]")
    console.print(f"  Window:   {start.strftime('%Y-%m-%d')} -> {end.strftime('%Y-%m-%d')}")
    console.print(f"  Min score: {args.min_score or strategy.get('min_score', 65)}\n")

    # Fetch data
    cache = _build_cache(config, args)
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    console.print("[bold]Fetching price history...[/bold]")
    price_data = fetcher.fetch_batch(tickers, period=fetch_period)
    console.print(f"  Got price data for {len(price_data)}/{len(tickers)} tickers")

    console.print("[bold]Fetching fundamentals (current snapshot)...[/bold]")
    fundamentals = fund_fetcher.fetch_batch(tickers)
    console.print(f"  Got fundamentals for {len(fundamentals)}/{len(tickers)} tickers\n")

    # SPY + VIX (regime tagging)
    console.print("[bold]Fetching SPY + VIX...[/bold]")
    bench_map = fetcher.fetch_batch(["SPY", "^VIX"], period=fetch_period)
    spy_df = bench_map.get("SPY")
    vix_df = bench_map.get("^VIX")

    # Earnings dates for blackout + earnings history for PEAD detector
    earnings_dates = {}
    earnings_history = {}
    need_earnings = args.earnings_blackout > 0
    console.print("[bold]Fetching earnings history (PEAD + blackout)...[/bold]")
    earnings_history = fetch_earnings_history(list(price_data.keys()))
    with_history = sum(1 for v in earnings_history.values() if v is not None and not v.empty)
    console.print(f"  Got earnings history for {with_history}/{len(price_data)} tickers")
    # Derive blackout date list from history (avoids second yfinance call)
    if need_earnings:
        for t, df_h in earnings_history.items():
            if df_h is None or df_h.empty:
                earnings_dates[t] = []
            else:
                earnings_dates[t] = sorted(df_h.index.tolist())
    print()

    # Build engine config
    bt_cfg = BacktestConfig(
        start_date=start,
        end_date=end,
        min_score=args.min_score if args.min_score is not None else strategy.get("min_score", 65),
        max_open_positions=args.max_positions,
        max_position_pct=args.position_pct,
        starting_cash=args.cash,
        max_hold_days=args.hold_days,
        compound=getattr(args, "compound", False),
        commission_per_trade=args.commission,
        slippage_bps=args.slippage_bps,
        regulatory_bps_on_sale=args.regulatory_bps,
        earnings_blackout_days=args.earnings_blackout,
        accept_lookahead=args.accept_lookahead,
        oos_split_pct=args.oos_split,
        bootstrap_resamples=args.bootstrap_resamples,
        vol_target_risk_pct=args.vol_target_risk,
    )

    if args.sweep is not None:
        from src.backtest.sweep import parameter_sweep, parse_grid
        from src.backtest.display import display_sweep_results
        sweep_spec = None if args.sweep == "default" else args.sweep
        try:
            grid = parse_grid(sweep_spec)
        except ValueError as e:
            console.print(f"[red]Bad --sweep spec: {e}[/red]")
            return
        console.print(
            f"\n[bold cyan]Sweeping {sum(1 for _ in __import__('itertools').product(*grid.values()))} "
            f"combinations of {list(grid.keys())}[/bold cyan]\n"
        )
        rows = parameter_sweep(
            price_data, fundamentals, config, strategy, bt_cfg, grid,
            spy_df=spy_df, vix_df=vix_df, earnings_dates=earnings_dates,
        )
        display_sweep_results(rows, strategy_name, universe_label)
        if args.save:
            with open(Path(args.save), "w", encoding="utf-8") as f:
                json.dump(rows, f, indent=2, default=str)
            console.print(f"\n[dim]Sweep results saved to {args.save}[/dim]")
        return

    if args.compare:
        from src.backtest.display import display_strategy_comparison
        comparison_rows = []
        for name in config.get_strategy_names():
            strat = config.get_strategy(name)
            try:
                r = run_backtest(
                    price_data, fundamentals, config, strat, bt_cfg,
                    spy_df=spy_df, vix_df=vix_df, earnings_dates=earnings_dates,
                )
                comparison_rows.append({"strategy": name, "result": r})
            except LookaheadGuardError as e:
                comparison_rows.append({"strategy": name, "error": str(e)[:80]})
        display_strategy_comparison(comparison_rows, universe_label)
        if args.save:
            with open(Path(args.save), "w", encoding="utf-8") as f:
                json.dump(comparison_rows, f, indent=2, default=str)
            console.print(f"\n[dim]Comparison saved to {args.save}[/dim]")
        return

    try:
        result = run_backtest(
            price_data, fundamentals, config, strategy, bt_cfg,
            spy_df=spy_df, vix_df=vix_df,
            earnings_dates=earnings_dates,
            earnings_history=earnings_history,
        )
    except LookaheadGuardError as e:
        console.print(f"\n[red]LOOKAHEAD GUARD:[/red] {e}\n")
        console.print(
            "[yellow]Pick a strategy with low fundamental weight (e.g. short_term_momentum, "
            "swing_trading) or pass --accept-lookahead to override.[/yellow]\n"
        )
        return

    display_backtest_results(result, strategy_name, universe_label)

    if args.html_report:
        from src.backtest.report import render_html_report
        report_path = render_html_report(result, strategy_name, universe_label, args.html_report)
        console.print(f"\n[bold green]HTML report saved to {report_path}[/bold green]")

    if args.quantstats_report:
        from src.research.quantstats_service import render_quantstats_report
        try:
            qs_path = render_quantstats_report(
                result.get("equity_curve", []),
                args.quantstats_report,
                title=f"{strategy_name} on {universe_label}",
            )
            console.print(f"[bold green]Quantstats tearsheet saved to {qs_path}[/bold green]")
        except Exception as e:
            console.print(f"[red]Quantstats report failed: {e}[/red]")

    if args.save:
        out_path = Path(args.save)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
        console.print(f"\n[dim]Full results saved to {out_path}[/dim]")


def cmd_diagnose(config, args):
    """Alphalens IC diagnostic — does the composite score predict forward returns?"""
    import json
    import pandas as pd
    from src.research.diagnostic_service import (
        build_score_panel, build_price_matrix, run_alphalens, render_html_report,
    )
    from src.backtest.engine import (
        BacktestConfig, LookaheadGuardError, fetch_earnings_history,
    )

    strategy_name = args.strategy or config.strategies.get("default_strategy", "swing_trading")
    strategy = config.get_strategy(strategy_name)

    # Gate fundamentals lookahead — same guard as backtest
    fund_weight = strategy.get("weights", {}).get("fundamental", 0)
    if fund_weight > 0.05 and not args.accept_lookahead:
        console.print(
            f"\n[red]LOOKAHEAD GUARD:[/red] strategy weights fundamentals at "
            f"{fund_weight*100:.0f}%. yfinance is current-snapshot.\n"
            "[yellow]Use a low-fundamental strategy (short_term_momentum, swing_trading) "
            "or pass --accept-lookahead.[/yellow]\n"
        )
        return

    # Resolve universe
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        universe_label = f"custom ({len(tickers)})"
    elif args.universe == "portfolio":
        from src.portfolio import Portfolio
        tickers = Portfolio(config).get_tickers()
        universe_label = f"portfolio ({len(tickers)})"
    elif args.universe == "themes":
        tickers = config.get_theme_tickers()
        universe_label = f"themes ({len(tickers)})"
    else:
        tickers = config.get_watchlist()
        universe_label = f"watchlist ({len(tickers)})"

    if not tickers:
        console.print(f"[red]No tickers found for universe '{args.universe}'[/red]")
        return

    end = pd.Timestamp.now().normalize()
    start = end - pd.Timedelta(days=int(365.25 * args.years))
    fetch_period_years = max(args.years + 2, 5)
    fetch_period = f"{int(fetch_period_years)}y"

    console.print(f"\n[bold cyan]Alphalens IC Diagnostic[/bold cyan]")
    console.print(f"  Strategy: [bold]{strategy_name}[/bold]")
    console.print(f"  Universe: [bold]{universe_label}[/bold]")
    console.print(f"  Window:   {start.strftime('%Y-%m-%d')} -> {end.strftime('%Y-%m-%d')}")
    console.print(f"  Factor:   [bold]{args.factor}[/bold]   Quantiles: {args.quantiles}\n")

    cache = _build_cache(config, args)
    fetcher = DataFetcher(config, cache)
    fund_fetcher = FundamentalsFetcher(config, cache)

    console.print("[bold]Fetching price history...[/bold]")
    price_data = fetcher.fetch_batch(tickers, period=fetch_period)
    console.print(f"  Got prices for {len(price_data)}/{len(tickers)} tickers")

    console.print("[bold]Fetching fundamentals (snapshot)...[/bold]")
    fundamentals = fund_fetcher.fetch_batch(tickers)

    console.print("[bold]Fetching earnings history...[/bold]")
    earnings_history = fetch_earnings_history(list(price_data.keys()))

    console.print("[bold]Building score panel (this is the slow part)...[/bold]")
    try:
        panel = build_score_panel(
            price_data, fundamentals, earnings_history,
            config, strategy, start, end,
        )
    except LookaheadGuardError as e:
        console.print(f"[red]Lookahead blocked: {e}[/red]")
        return

    console.print(f"  Built panel: {len(panel)} (date, ticker) rows")

    if panel.empty:
        console.print("[red]Empty panel — nothing to analyze[/red]")
        return

    console.print("[bold]Building price matrix...[/bold]")
    prices = build_price_matrix(price_data, panel["date"].min(), end + pd.Timedelta(days=30))
    console.print(f"  Price matrix: {prices.shape}")

    periods = tuple(int(p.strip()) for p in args.periods.split(","))

    console.print("[bold]Running alphalens IC analysis...[/bold]\n")
    stats = run_alphalens(panel, prices, factor_column=args.factor,
                          periods=periods, quantiles=args.quantiles)

    # Display
    from rich.table import Table
    from rich.panel import Panel
    from rich import box

    ic_table = Table(title=f"Information Coefficient — factor: {args.factor}", box=box.ROUNDED)
    ic_table.add_column("Horizon", style="bold")
    ic_table.add_column("IC mean", justify="right")
    ic_table.add_column("IC std", justify="right")
    ic_table.add_column("IC IR", justify="right", style="bold yellow")
    for h in stats["ic_mean"]:
        ic_table.add_row(
            h,
            f"{stats['ic_mean'][h]:+.4f}",
            f"{stats['ic_std'][h]:.4f}",
            f"{stats['ic_ir'][h]:+.3f}",
        )
    console.print(ic_table)

    spread_table = Table(title="Top-Minus-Bottom Quantile Spread", box=box.ROUNDED)
    spread_table.add_column("Horizon", style="bold")
    spread_table.add_column("Spread (%)", justify="right", style="bold yellow")
    for h, v in stats["top_minus_bottom_pct"].items():
        spread_table.add_row(h, f"{v:+.3f}%")
    console.print(spread_table)

    # Verdict
    best_ic = max(stats["ic_mean"].values()) if stats["ic_mean"] else 0
    if best_ic > 0.05:
        verdict = f"STRONG signal (best IC {best_ic:+.4f}). Worth scaling capital."
        style = "bold green"
    elif best_ic > 0.03:
        verdict = f"MODEST signal (best IC {best_ic:+.4f}). Edge exists; manage costs."
        style = "bold yellow"
    elif best_ic > 0.01:
        verdict = f"WEAK signal (best IC {best_ic:+.4f}). Probably not exploitable after costs."
        style = "bold red"
    else:
        verdict = f"NO signal (best IC {best_ic:+.4f}). Composite score is noise; redesign needed."
        style = "bold red"
    console.print(Panel(verdict, title="IC Verdict", box=box.ROUNDED, style=style))
    console.print(f"\n[dim]Sample size: {stats['n_observations']:,} observations.[/dim]")

    if args.html_report:
        out = render_html_report(panel, prices, args.html_report,
                                  factor_column=args.factor, periods=periods,
                                  quantiles=args.quantiles)
        console.print(f"\n[bold green]Full report saved to {out}[/bold green]")


if __name__ == "__main__":
    main()
