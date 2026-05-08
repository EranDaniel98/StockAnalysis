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

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config_loader import Config
from src.data.cache import DataCache
from src.data.fetcher import DataFetcher
from src.data.fundamentals import FundamentalsFetcher
from src.data.screener import StockScreener
from src.analysis import technical, fundamental, patterns, statistical
from src.analysis.trend_detector import analyze_stock_trend, detect_trending_sectors
from src.scoring.engine import calculate_composite_score, batch_score
from src.scoring.recommender import generate_recommendation, check_diversification, allocate_portfolio
from src.display.cli_output import (
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
        plan = allocate_portfolio(recommendations, budget, config)
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
        plan = allocate_portfolio(recommendations, budget, config)
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
        plan = allocate_portfolio(recommendations, budget, config)
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

    # Get current prices for P&L
    current_prices = {}
    for ticker in tickers:
        rt = fetcher.fetch_realtime_price(ticker)
        if rt and rt.get("last_price"):
            current_prices[ticker] = rt["last_price"]
        else:
            # Fallback to latest close from history
            df = fetcher.fetch_price_data(ticker, period="5d")
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
            plan = allocate_portfolio(recommendations, budget, config)
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


def _analyze_and_score(price_data_map, fundamentals_map, config, strategy):
    """
    Run all analysis engines and generate scored recommendations.
    Returns list of recommendation dicts sorted by composite score.
    """
    analysis_results = {}
    total = len(price_data_map)

    for i, (ticker, df) in enumerate(price_data_map.items(), 1):
        console.print(f"  Analyzing [{i}/{total}]: [cyan]{ticker}[/cyan]")
        fund = fundamentals_map.get(ticker, {})

        try:
            tech_result = technical.analyze(df, config)
            fund_result = fundamental.analyze(fund, config)
            pattern_result = patterns.analyze(df, config)
            stat_result = statistical.analyze(df, config)
            trend_result = analyze_stock_trend(df, fund, config)

            analysis_results[ticker] = {
                "technical": tech_result,
                "fundamental": fund_result,
                "pattern": pattern_result,
                "statistical": stat_result,
                "trend": trend_result,
            }
        except Exception as e:
            logger.error(f"Error analyzing {ticker}: {e}")

    console.print(f"\n  Analysis complete: {len(analysis_results)}/{total} stocks\n")

    # Score all stocks
    scored = batch_score(analysis_results, strategy)

    # Generate full recommendations
    recommendations = []
    for ticker, score_result in scored:
        rec = generate_recommendation(
            ticker,
            score_result,
            price_data_map.get(ticker),
            fundamentals_map.get(ticker),
            config,
        )
        recommendations.append(rec)

    return recommendations


if __name__ == "__main__":
    main()
