"""
Comprehensive help system for the Stock Market Scanner.
Explains every concept, strategy, indicator, and workflow in plain language.
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich import box

console = Console()


TOPICS = {
    "overview":    "System overview - what this tool does and how to use it",
    "strategies":  "All trading strategies explained in detail",
    "scan":        "How the market scan works step-by-step",
    "setup":       "APIs, dependencies, and setup requirements",
    "indicators":  "All technical indicators explained",
    "scoring":     "How stocks are scored and ranked",
    "risk":        "Risk management - stop-loss, take-profit, position sizing",
    "config":      "How to configure and customize everything",
    "enhance":     "Ideas and roadmap for enhancing this project",
    "missing":     "What's currently missing and known limitations",
    "commands":    "All CLI commands with examples",
    "glossary":    "Key financial terms explained",
}


def show_help(topic=None):
    """Display help for a topic, or list all topics."""
    if topic is None:
        _show_topic_list()
        return

    topic = topic.lower().strip()
    handler = TOPIC_HANDLERS.get(topic)
    if handler:
        handler()
    else:
        console.print(f"[red]Unknown topic: '{topic}'[/red]")
        console.print(f"Available topics: {', '.join(TOPICS.keys())}\n")
        _show_topic_list()


def _show_topic_list():
    console.print()
    console.print(Panel(
        "[bold]Stock Market Scanner - Help System[/bold]\n\n"
        "Use [cyan]python -m src.main help <topic>[/cyan] to learn about a specific topic.",
        border_style="cyan",
        box=box.ROUNDED,
    ))

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Topic", style="cyan", width=14)
    table.add_column("Description")

    for topic, desc in TOPICS.items():
        table.add_row(topic, desc)

    console.print(table)
    console.print()
    console.print("  [dim]Example: python -m src.main help strategies[/dim]")
    console.print("  [dim]Example: python -m src.main help scan[/dim]\n")


# =============================================================================
# TOPIC: Overview
# =============================================================================
def _help_overview():
    text = """
# Stock Market Scanner - Overview

## What Is This?

This is a **personal stock market analysis tool** that scans the US stock market,
analyzes stocks using mathematical models, and recommends what to buy, sell, or hold.

Think of it as your personal financial analyst that:
- **Discovers** stocks worth looking at (from ~6,000+ US stocks)
- **Analyzes** them using 20+ technical and fundamental indicators
- **Scores** each stock from 0-100 based on your chosen strategy
- **Recommends** actions (STRONG BUY / BUY / HOLD / SELL / STRONG SELL)
- **Calculates** exactly how much to buy, where to set stop-loss, and target price
- **Alerts** you via Telegram when opportunities appear

## Is It Ready For Use?

**Yes!** The core system is fully functional:
- [green]READY[/green]  Market scanning with staged filtering
- [green]READY[/green]  5 pre-built investment strategies
- [green]READY[/green]  Technical analysis (RSI, MACD, Bollinger, MA crossovers, etc.)
- [green]READY[/green]  Fundamental analysis (P/E, growth, profitability, debt)
- [green]READY[/green]  Pattern detection (10 candlestick patterns, support/resistance)
- [green]READY[/green]  Statistical models (momentum, mean reversion, seasonality, regression)
- [green]READY[/green]  Risk management (stop-loss, take-profit, position sizing)
- [green]READY[/green]  Telegram alerts
- [green]READY[/green]  Data caching (avoids redundant API calls)
- [yellow]MISSING[/yellow] Backtesting (test strategies on historical data)
- [yellow]MISSING[/yellow] Portfolio tracking (track your actual positions)
- [yellow]MISSING[/yellow] News/sentiment analysis
- [yellow]MISSING[/yellow] Web dashboard (CLI only for now)

## Quick Start

    python -m src.main watchlist                     # Analyze your watchlist
    python -m src.main analyze NVDA AAPL TSLA        # Analyze specific stocks
    python -m src.main scan --theme artificial_intelligence  # Scan AI stocks
    python -m src.main help strategies               # Learn about strategies

## Important Disclaimer

This tool is for **educational and informational purposes only**. It is NOT financial
advice. Always do your own research and consult a financial advisor before investing.
Past performance does not guarantee future results. All investing involves risk.
"""
    console.print(Markdown(text))


# =============================================================================
# TOPIC: Strategies
# =============================================================================
def _help_strategies():
    console.print()
    console.print(Panel("[bold]Trading & Investing Strategies[/bold]", border_style="cyan"))

    strategies = [
        {
            "name": "long_term_growth",
            "title": "Long-Term Growth",
            "horizon": "6-24 months",
            "risk": "Medium",
            "who": "Investors looking for companies with strong, sustained growth",
            "how": (
                "This strategy heavily weights FUNDAMENTAL analysis (35%) and "
                "STATISTICAL models (25%). It looks for companies with strong revenue "
                "growth, expanding earnings, high return on equity, and positive "
                "12-month momentum. Technical analysis plays a supporting role (20%) "
                "to help with entry timing.\n\n"
                "Best for: Companies like NVDA, MSFT, GOOGL that are growing revenues "
                "and earnings rapidly. The strategy favors profitable companies with "
                "$5B+ market cap."
            ),
            "weights": "Tech 20% | Fund 35% | Pattern 5% | Stat 25% | Trend 15%",
            "example": "python -m src.main scan --strategy long_term_growth",
        },
        {
            "name": "short_term_momentum",
            "title": "Short-Term Momentum",
            "horizon": "1-30 days",
            "risk": "High",
            "who": "Active traders looking to ride existing trends",
            "how": (
                "This strategy heavily weights TECHNICAL analysis (45%) and "
                "PATTERN detection (25%). It focuses on RSI, MACD crossovers, "
                "volume spikes, and short-term momentum (3-month returns). "
                "Fundamentals are almost ignored (5%) because in the short term, "
                "price action matters more than financials.\n\n"
                "Best for: Stocks showing breakout patterns, unusual volume, "
                "or strong recent momentum. Higher risk due to short timeframe."
            ),
            "weights": "Tech 45% | Fund 5% | Pattern 25% | Stat 15% | Trend 10%",
            "example": "python -m src.main scan --strategy short_term_momentum",
        },
        {
            "name": "value_investing",
            "title": "Value Investing",
            "horizon": "12-36 months",
            "risk": "Low-Medium",
            "who": "Patient investors seeking undervalued companies (Warren Buffett style)",
            "how": (
                "This strategy heavily weights FUNDAMENTALS (45%) and "
                "STATISTICAL models (30%). It looks for low P/E, low P/B (price "
                "below book value), low debt, and strong free cash flow. The mean "
                "reversion model is key here - it finds stocks that have dropped "
                "below their historical average and may bounce back.\n\n"
                "Best for: Established companies temporarily beaten down. "
                "Requires patience - value stocks can take months to recover."
            ),
            "weights": "Tech 10% | Fund 45% | Pattern 5% | Stat 30% | Trend 10%",
            "example": "python -m src.main scan --strategy value_investing",
        },
        {
            "name": "swing_trading",
            "title": "Swing Trading",
            "horizon": "2-14 days",
            "risk": "Medium-High",
            "who": "Traders capturing multi-day price swings",
            "how": (
                "This strategy balances TECHNICAL analysis (35%) and "
                "PATTERN detection (30%). It focuses on Bollinger Band squeezes "
                "(which predict breakouts), candlestick reversal patterns "
                "(hammer, engulfing), and support/resistance levels. Volume "
                "confirmation is critical.\n\n"
                "Best for: Stocks near support/resistance levels showing "
                "reversal patterns with volume confirmation. Requires active "
                "monitoring and disciplined stop-losses."
            ),
            "weights": "Tech 35% | Fund 5% | Pattern 30% | Stat 20% | Trend 10%",
            "example": "python -m src.main scan --strategy swing_trading",
        },
        {
            "name": "dividend_income",
            "title": "Dividend Income",
            "horizon": "12+ months",
            "risk": "Low",
            "who": "Income-focused investors seeking reliable dividend payments",
            "how": (
                "This strategy heavily weights FUNDAMENTALS (40%) and "
                "STATISTICAL models (30%). It looks for high dividend yield, "
                "sustainable payout ratios (20-60%), consistent earnings, "
                "and low debt. It favors large, stable companies ($10B+ market cap) "
                "that have a history of growing their dividends.\n\n"
                "Best for: Utility companies, REITs, established blue-chips. "
                "The goal is steady income, not explosive growth."
            ),
            "weights": "Tech 10% | Fund 40% | Pattern 5% | Stat 30% | Trend 15%",
            "example": "python -m src.main scan --strategy dividend_income",
        },
    ]

    for s in strategies:
        lines = [
            f"[bold]Time Horizon:[/bold] {s['horizon']}  |  [bold]Risk Level:[/bold] {s['risk']}",
            f"[bold]Best For:[/bold] {s['who']}",
            "",
            f"[bold]How It Works:[/bold]",
            s["how"],
            "",
            f"[bold]Weights:[/bold] {s['weights']}",
            "",
            f"[dim]{s['example']}[/dim]",
        ]
        console.print(Panel(
            "\n".join(lines),
            title=f"[bold cyan]{s['title']}[/bold cyan] ({s['name']})",
            border_style="cyan",
            box=box.ROUNDED,
        ))

    console.print(Panel(
        "[bold]How to choose?[/bold]\n\n"
        "  - New to investing? Start with [cyan]long_term_growth[/cyan] or [cyan]value_investing[/cyan]\n"
        "  - Want passive income? Use [cyan]dividend_income[/cyan]\n"
        "  - Active trader? Try [cyan]short_term_momentum[/cyan] or [cyan]swing_trading[/cyan]\n"
        "  - You can create your own strategy in [bold]config/strategies.yaml[/bold]\n\n"
        "[bold]Tip:[/bold] Run the same scan with different strategies to see how results change.\n"
        "A stock rated STRONG BUY across multiple strategies is a stronger signal.",
        title="Which Strategy Should I Use?",
        border_style="green",
    ))


# =============================================================================
# TOPIC: Scan
# =============================================================================
def _help_scan():
    console.print()
    console.print(Panel("[bold]How the Market Scan Works[/bold]", border_style="cyan"))

    text = """
The scan runs in 4 stages, like a funnel that narrows down from thousands of stocks
to the best opportunities:

[bold cyan]STAGE 1: Discovery[/bold cyan] (Broad net - finds ~500 stocks)
  What: Queries the stock market for all stocks matching your criteria
  How:  Uses Finviz screener to filter by exchange, market cap, volume, sector
  Config: settings.yaml -> markets, screening, sectors_focus
  Time: ~5 seconds

  Example: From ~6,000 US stocks, filter to ~500 that meet minimum
  market cap ($1B), average volume (500K), and are in focused sectors.

                    6,000 stocks
                         |
              [Market Cap > $1B]
              [Volume > 500K/day]
              [Sector = Tech/AI/Chips]
                         |
                    ~500 stocks

[bold cyan]STAGE 2: Fundamental Filtering[/bold cyan] (Quality filter - keeps ~50 stocks)
  What: Downloads basic financial data and ranks by quality
  How:  Fetches P/E, revenue growth, margins from yfinance
  Scores: Market cap, revenue growth, profitability, analyst ratings
  Time: ~2-5 minutes (depends on number of stocks)

                    ~500 stocks
                         |
              [Fetch fundamentals]
              [Rank by quality score]
              [Keep top 50]
                         |
                    ~50 stocks

[bold cyan]STAGE 3: Data Collection[/bold cyan] (Deep data gathering)
  What: Downloads 5 years of daily price data for each stock
  How:  Uses yfinance with local SQLite caching
  Data: Open, High, Low, Close, Volume (OHLCV) per day
  Time: ~1-3 minutes (cached runs are instant)

[bold cyan]STAGE 4: Analysis & Scoring[/bold cyan] (The math)
  What: Runs 5 analysis engines on each stock simultaneously
  How:  Each engine produces a score from 0-100
  Engines:
    1. TECHNICAL  - RSI, MACD, Moving Averages, Bollinger, Stochastic, Volume
    2. FUNDAMENTAL - Valuation, growth, profitability, financial health
    3. PATTERNS    - Candlestick patterns, support/resistance, divergences
    4. STATISTICAL - Momentum, mean reversion, seasonality, trend regression
    5. TREND       - Sector alignment, theme matching, trend confirmation

  The composite score = weighted average based on your chosen strategy.

[bold cyan]OUTPUT:[/bold cyan]
  - Ranked table of all analyzed stocks
  - Detailed breakdown for top BUY signals
  - Risk management: stop-loss, take-profit, position sizing
  - Diversification warnings
  - Telegram alert (if configured)

[bold]Total time:[/bold] ~5-10 minutes for a full scan (much faster on cached data)
"""
    console.print(text)

    console.print(Panel(
        "python -m src.main scan                                    # Full scan, default strategy\n"
        "python -m src.main scan --strategy value_investing          # Scan with value strategy\n"
        "python -m src.main scan --theme artificial_intelligence     # Scan only AI stocks\n"
        "python -m src.main scan --sector semiconductors             # Scan only chip stocks\n"
        "python -m src.main scan --top 10                            # Show only top 10\n"
        "python -m src.main scan --no-alert                          # Skip Telegram alerts",
        title="Scan Examples",
        border_style="green",
    ))


# =============================================================================
# TOPIC: Setup
# =============================================================================
def _help_setup():
    console.print()
    console.print(Panel("[bold]Setup, APIs & Dependencies[/bold]", border_style="cyan"))

    text = """
[bold cyan]REQUIRED APIs (all FREE - no API key needed):[/bold cyan]

  1. [bold]yfinance[/bold] (Yahoo Finance)
     - Provides: Price data (OHLCV), fundamentals, analyst ratings
     - Cost: FREE, no API key required
     - Rate limit: ~2,000 requests/hour (we add delays automatically)
     - Note: Unofficial API, may occasionally have downtime

  2. [bold]finvizfinance[/bold] (Finviz)
     - Provides: Stock screening and discovery
     - Cost: FREE, no API key required
     - Used for: Stage 1 of the scan (finding stocks to analyze)
     - Note: Scrapes finviz.com, respect rate limits

[bold cyan]OPTIONAL APIs (need setup):[/bold cyan]

  3. [bold]Telegram Bot API[/bold] (for alerts)
     - Provides: Push notifications to your phone
     - Cost: FREE
     - Setup:
       a. Message @BotFather on Telegram
       b. Send /newbot and follow instructions
       c. Copy the bot token
       d. Message your bot, then visit:
          https://api.telegram.org/bot<TOKEN>/getUpdates
       e. Find your chat_id in the response
       f. Add to .env file:
          TELEGRAM_BOT_TOKEN=your_token_here
          TELEGRAM_CHAT_ID=your_chat_id_here

[bold cyan]INSTALLATION:[/bold cyan]

  1. Install Python 3.10+ (if not already installed)
  2. Install dependencies:
     [green]pip install -r requirements.txt[/green]
  3. Copy .env.example to .env and add your Telegram credentials:
     [green]copy .env.example .env[/green]
  4. Run your first scan:
     [green]python -m src.main watchlist[/green]

[bold cyan]NO PAID SERVICES REQUIRED[/bold cyan]
  Everything runs locally on your machine. No cloud servers, no subscriptions.
  The only network calls are to Yahoo Finance (price data) and Finviz (screening).
"""
    console.print(text)


# =============================================================================
# TOPIC: Indicators
# =============================================================================
def _help_indicators():
    console.print()
    console.print(Panel("[bold]Technical Indicators Explained[/bold]", border_style="cyan"))

    indicators = [
        ("RSI (Relative Strength Index)",
         "14 periods",
         "Measures if a stock is overbought or oversold on a scale of 0-100.\n"
         "Below 30 = oversold (potential buy), Above 70 = overbought (potential sell).\n"
         "Think of it as: 'How tired are the buyers/sellers?'"),

        ("MACD (Moving Average Convergence Divergence)",
         "12/26/9",
         "Shows momentum direction and strength using two moving averages.\n"
         "When MACD crosses ABOVE signal line = bullish (buy signal).\n"
         "When MACD crosses BELOW signal line = bearish (sell signal).\n"
         "The histogram shows how strong the momentum is."),

        ("SMA (Simple Moving Average)",
         "20, 50, 200 days",
         "The average price over N days. Key levels:\n"
         "- SMA20: Short-term trend\n"
         "- SMA50: Medium-term trend\n"
         "- SMA200: Long-term trend (the big one)\n"
         "Price above SMA = bullish. Golden Cross (SMA50 > SMA200) = very bullish."),

        ("EMA (Exponential Moving Average)",
         "9, 12, 26 days",
         "Like SMA but gives more weight to recent prices, reacts faster.\n"
         "Used internally by MACD. EMA9 is popular for short-term trading."),

        ("Bollinger Bands",
         "20 periods, 2 std dev",
         "Creates an envelope around price using standard deviation.\n"
         "Price at lower band = potential buy (oversold).\n"
         "Price at upper band = potential sell (overbought).\n"
         "Squeeze (narrow bands) = breakout coming soon!"),

        ("Stochastic Oscillator",
         "K=14, D=3",
         "Shows where the price closed relative to its range over N periods.\n"
         "Below 20 = oversold, Above 80 = overbought.\n"
         "Similar to RSI but uses high/low range instead of close-to-close changes."),

        ("ATR (Average True Range)",
         "14 periods",
         "Measures volatility - how much a stock typically moves per day.\n"
         "Not a direction signal, but used for setting stop-losses.\n"
         "Higher ATR = more volatile = wider stop-loss needed."),

        ("Volume Analysis",
         "20-day average",
         "Compares current volume to average. Volume spike (2x+) = significant.\n"
         "Rising price + high volume = strong move (confirmed).\n"
         "Rising price + low volume = weak move (suspicious)."),
    ]

    for name, params, explanation in indicators:
        console.print(Panel(
            f"[bold]Default Parameters:[/bold] {params}\n\n{explanation}\n\n"
            f"[dim]All parameters are configurable in config/settings.yaml -> technical_indicators[/dim]",
            title=f"[bold cyan]{name}[/bold cyan]",
            border_style="blue",
            box=box.ROUNDED,
        ))

    console.print()
    console.print(Panel("[bold]Statistical Models[/bold]", border_style="cyan"))

    stat_models = [
        ("Momentum Scoring",
         "Measures returns over 1, 3, 6, and 12 months.\n"
         "Stocks with strong recent returns tend to continue performing well\n"
         "(momentum effect). This is one of the most well-documented market anomalies."),

        ("Mean Reversion (Z-Score)",
         "Measures how far the current price is from its 200-day average.\n"
         "Z-score > 2 = very extended above mean (may pull back).\n"
         "Z-score < -2 = very depressed below mean (may bounce).\n"
         "Works best for stable stocks, less reliable for high-growth names."),

        ("Seasonality",
         "Analyzes historical returns month-by-month.\n"
         "Some stocks consistently perform better in certain months.\n"
         "'Sell in May and go away' is a famous example.\n"
         "Uses the stock's own history, not general market patterns."),

        ("Trend Regression (R-squared)",
         "Fits a straight line through 60 days of log-prices.\n"
         "Slope = direction and speed of trend.\n"
         "R-squared = how clean/consistent the trend is (0 to 1).\n"
         "R-squared > 0.7 with positive slope = strong, clean uptrend."),
    ]

    for name, explanation in stat_models:
        console.print(Panel(explanation,
            title=f"[bold cyan]{name}[/bold cyan]",
            border_style="blue",
            box=box.ROUNDED,
        ))


# =============================================================================
# TOPIC: Scoring
# =============================================================================
def _help_scoring():
    console.print()
    console.print(Panel("[bold]How Stocks Are Scored[/bold]", border_style="cyan"))

    text = """
[bold cyan]THE SCORING PIPELINE:[/bold cyan]

  Each stock runs through 5 analysis engines. Each engine returns a score
  from 0 to 100:

    TECHNICAL SCORE    ─┐
    FUNDAMENTAL SCORE  ─┤
    PATTERN SCORE      ─┼─> WEIGHTED AVERAGE ──> COMPOSITE SCORE (0-100)
    STATISTICAL SCORE  ─┤
    TREND SCORE        ─┘

  The weights depend on your chosen strategy (see: help strategies).

[bold cyan]SCORE INTERPRETATION:[/bold cyan]

    80-100  [bold green]STRONG BUY[/bold green]   High confidence buying opportunity
    65-79   [green]BUY[/green]          Good opportunity, moderate confidence
    50-64   [yellow]HOLD[/yellow]         Neutral, no clear direction
    35-49   [yellow]HOLD[/yellow]         Slightly bearish, wait for better entry
    20-34   [red]SELL[/red]         Bearish signals, consider exiting
     0-19   [bold red]STRONG SELL[/bold red]  Multiple bearish signals, exit recommended

  These thresholds are configurable in config/settings.yaml -> scoring -> thresholds.

[bold cyan]SIGNAL CONSENSUS:[/bold cyan]

  On top of the weighted score, we count bullish vs bearish signals.
  If most signals agree (e.g., 8 bullish, 2 bearish), the composite score
  gets a small bonus (+/- 5 points max). This rewards conviction.

[bold cyan]INDIVIDUAL ENGINE SCORING:[/bold cyan]

  Each indicator within an engine produces its own signal and mini-score:

  Example for RSI:
    RSI = 25 (below 30)  ->  "Oversold"  ->  bullish signal  ->  score ~75
    RSI = 50 (neutral)   ->  no signal   ->  score ~50
    RSI = 78 (above 70)  ->  "Overbought" -> bearish signal  ->  score ~22

  These mini-scores are averaged within each engine to produce the engine's
  overall score. Then engines are combined using strategy weights.

[bold cyan]WHY A STOCK MIGHT SCORE DIFFERENTLY ACROSS STRATEGIES:[/bold cyan]

  NVDA example:
    Technical:    57 (neutral - RSI divergence)
    Fundamental:  69 (good growth, high debt)
    Statistical:  56 (extended from mean)
    Trend:        77 (AI theme, tech sector)

    Long-Term Growth strategy (Fund 35%, Stat 25%):  Score = 66 (BUY)
    Short-Term Momentum (Tech 45%, Pattern 25%):     Score = 54 (HOLD)

  Same stock, different conclusion - because strategies weigh factors differently.
"""
    console.print(text)


# =============================================================================
# TOPIC: Risk
# =============================================================================
def _help_risk():
    console.print()
    console.print(Panel("[bold]Risk Management Explained[/bold]", border_style="cyan"))

    text = """
[bold cyan]STOP-LOSS (Where to cut losses):[/bold cyan]

  Three methods available (configurable):

  1. [bold]ATR-Based[/bold] (default, recommended)
     Stop = Current Price - (ATR x Multiplier)
     Example: Price $100, ATR $5, Multiplier 2.0  ->  Stop at $90
     Why: Adapts to volatility. Volatile stocks get wider stops.
     Config: risk_management.stop_loss.atr_multiplier (default: 2.0)

  2. [bold]Percentage-Based[/bold]
     Stop = Current Price x (1 - Percentage)
     Example: Price $100, 5% stop  ->  Stop at $95
     Simple but doesn't account for volatility.
     Config: risk_management.stop_loss.percentage (default: 5.0)

  3. [bold]Support-Based[/bold]
     Stop = Just below nearest support level (2% buffer)
     Uses actual price history to find meaningful levels.
     Most sophisticated but support levels can be ambiguous.

[bold cyan]TAKE-PROFIT (Where to cash out):[/bold cyan]

  1. [bold]Risk/Reward Ratio[/bold] (default)
     Target = Current Price + (Risk x Ratio)
     Example: Risk is $10 (price to stop-loss), Ratio 3.0  ->  Target +$30
     Config: risk_management.take_profit.risk_reward_ratio (default: 3.0)
     A 3:1 ratio means you need to be right only 25% of the time to break even!

  2. [bold]ATR-Based[/bold]
     Target = Current Price + (ATR x Multiplier)

  3. [bold]Resistance-Based[/bold]
     Target = Nearest resistance level (historical price ceiling)

[bold cyan]POSITION SIZING (How much to buy):[/bold cyan]

  1. [bold]Fixed Fractional[/bold] (default)
     - Risks 1% of portfolio per trade
     - Maximum 10% of portfolio in a single position
     - Calculates exact number of shares based on stop-loss distance

     Example: $100,000 portfolio, Stock at $50, Stop at $45
       Risk per share = $5
       Max risk (1%) = $1,000
       Shares = $1,000 / $5 = 200 shares ($10,000 = 10% of portfolio)

  2. [bold]Kelly Criterion[/bold]
     - Mathematical formula for optimal bet sizing
     - Uses win probability and average win/loss ratio
     - We use Half-Kelly (half the suggested amount) for safety

     Config: risk_management.position_sizing.method

[bold cyan]DIVERSIFICATION WARNINGS:[/bold cyan]

  The system checks your recommendations for concentration risk:
  - Max 10% of portfolio in one stock (configurable)
  - Max 30% of portfolio in one sector (configurable)
  - Warning if too many positions (over 20)
  - Warning if no buy signals found

[bold]Golden Rule:[/bold] Never risk more than you can afford to lose.
The position sizing is a guide, not a guarantee.
"""
    console.print(text)


# =============================================================================
# TOPIC: Config
# =============================================================================
def _help_config():
    console.print()
    console.print(Panel("[bold]Configuration Guide[/bold]", border_style="cyan"))

    text = """
[bold cyan]NOTHING IS HARDCODED[/bold cyan] - every parameter can be changed in config files:

[bold]config/settings.yaml[/bold] - Main configuration
  - data.history_years        How many years of price data to fetch
  - data.interval             Data granularity (1d, 1h, 5m, etc.)
  - data.cache_expiry_hours   How long to cache data before refreshing
  - markets.min_market_cap    Filter out small companies
  - markets.min_avg_volume    Filter out illiquid stocks
  - markets.min_price         Filter out penny stocks
  - screening.stage1_max_stocks   Max stocks after initial screen
  - screening.stage2_max_stocks   Max stocks for deep analysis
  - technical_indicators.*    All indicator periods and thresholds
  - fundamental_filters.*     All fundamental thresholds
  - scoring.thresholds.*      Score-to-action mapping
  - risk_management.*         Stop-loss, take-profit, position sizing
  - alerts.telegram.*         Alert thresholds and settings
  - display.*                 Output formatting

[bold]config/strategies.yaml[/bold] - Strategy definitions
  - Add, modify, or remove strategies
  - Each strategy has its own weights and parameters
  - Set default_strategy to change the default

[bold]config/sectors.yaml[/bold] - Stock universe
  - sectors: Add/modify sector definitions with industry mappings
  - themes: Add themes (like "AI") with keywords and known tickers
  - watchlist: Your personal list of tickers to always analyze

[bold].env[/bold] - Secrets (never committed to git)
  - TELEGRAM_BOT_TOKEN
  - TELEGRAM_CHAT_ID

[bold cyan]TIPS:[/bold cyan]
  - Increase stage2_max_stocks for more thorough scans (slower)
  - Lower min_market_cap to include smaller companies (riskier)
  - Adjust scoring.thresholds to be more/less aggressive
  - Add your own tickers to the watchlist in sectors.yaml
  - Create custom strategies by copying an existing one and tweaking weights
"""
    console.print(text)


# =============================================================================
# TOPIC: Enhance
# =============================================================================
def _help_enhance():
    console.print()
    console.print(Panel("[bold]Enhancement Roadmap[/bold]", border_style="cyan"))

    enhancements = [
        ("HIGH PRIORITY", "green", [
            ("Backtesting Engine",
             "Test strategies against historical data before risking real money. "
             "Simulate: 'If I followed this strategy for the last 5 years, "
             "what would my returns be?' This is the #1 most important addition."),
            ("Portfolio Tracker",
             "Track your actual positions, P&L, and performance over time. "
             "Compare your results to benchmarks (S&P 500). Store buy/sell "
             "history in a local database."),
            ("News & Sentiment Analysis",
             "Scrape financial news headlines and analyze sentiment. "
             "Could use free APIs (NewsAPI, RSS feeds) or even Claude API "
             "for advanced sentiment analysis."),
            ("Earnings Calendar Integration",
             "Track upcoming earnings dates. High-scoring stocks about to "
             "report earnings are especially interesting (or risky)."),
        ]),
        ("MEDIUM PRIORITY", "yellow", [
            ("Web Dashboard",
             "Build a web UI with charts using Plotly/Dash or Streamlit. "
             "Visualize price charts with indicators overlaid. "
             "Interactive filtering and exploration."),
            ("Options Analysis",
             "Analyze options chains, implied volatility, unusual options "
             "activity. Options flow can signal institutional sentiment."),
            ("Machine Learning Models",
             "Train models on historical data to predict price direction. "
             "Could use random forests, LSTM networks, or gradient boosting. "
             "Feature engineering from existing indicators."),
            ("Export to CSV/Excel",
             "Export scan results for further analysis in spreadsheets "
             "or other tools."),
            ("Multi-Timeframe Analysis",
             "Analyze stocks on daily AND weekly AND monthly timeframes. "
             "Alignment across timeframes = stronger signal."),
        ]),
        ("NICE TO HAVE", "blue", [
            ("Insider Trading Tracker",
             "Monitor SEC filings for insider buying/selling. "
             "Insider buying is often a strong bullish signal."),
            ("Social Media Sentiment",
             "Track mentions on Reddit (r/wallstreetbets), Twitter/X, "
             "StockTwits. High social volume can precede moves."),
            ("Sector Rotation Model",
             "Track which sectors money is flowing into/out of. "
             "The business cycle tends to favor different sectors at "
             "different times."),
            ("Paper Trading Mode",
             "Simulated trading with virtual money. Practice strategies "
             "without risking real capital."),
            ("Crypto & Forex Support",
             "Extend to other markets. yfinance supports crypto pairs "
             "(BTC-USD) and forex."),
        ]),
    ]

    for priority, color, items in enhancements:
        lines = []
        for name, desc in items:
            lines.append(f"  [bold]{name}[/bold]")
            lines.append(f"  {desc}")
            lines.append("")

        console.print(Panel(
            "\n".join(lines),
            title=f"[bold {color}]{priority}[/bold {color}]",
            border_style=color,
            box=box.ROUNDED,
        ))

    console.print(Panel(
        "To implement any of these, just ask! Each enhancement can be built\n"
        "as a new module that plugs into the existing architecture.\n\n"
        "The system is designed to be modular - new analysis engines can be\n"
        "added without changing existing code.",
        title="Want to build one of these?",
        border_style="green",
    ))


# =============================================================================
# TOPIC: Missing
# =============================================================================
def _help_missing():
    console.print()
    console.print(Panel("[bold]Known Limitations & What's Missing[/bold]", border_style="cyan"))

    text = """
[bold red]IMPORTANT LIMITATIONS:[/bold red]

  1. [bold]No Backtesting[/bold]
     You cannot test strategies against historical data yet. This means
     you don't know if a strategy would have been profitable in the past.
     [dim]This is the biggest gap - build this before trading real money.[/dim]

  2. [bold]Free Data Limitations[/bold]
     - yfinance data can be delayed 15-30 minutes during market hours
     - Rate limits may slow down large scans
     - Data quality varies (some fields may be missing for smaller stocks)
     - Yahoo Finance is unofficial and could change at any time

  3. [bold]No Real-Time Streaming[/bold]
     The scanner runs on-demand. It doesn't continuously watch the market.
     For real-time alerts, you'd need to run it on a schedule (cron job).

  4. [bold]Pattern Detection is Basic[/bold]
     Candlestick patterns are detected using simple OHLC rules. Professional
     systems use more sophisticated pattern matching with ML models.

  5. [bold]No News or Events[/bold]
     The system doesn't know about earnings dates, FDA approvals, product
     launches, or breaking news. These can override any technical signal.

  6. [bold]Single-Stock Analysis Only[/bold]
     No portfolio-level optimization (Markowitz efficient frontier),
     no correlation analysis between positions, no beta hedging.

  7. [bold]US Stocks Only[/bold]
     Currently limited to NYSE and NASDAQ. No international markets,
     crypto, forex, or commodities (though yfinance supports these).

  8. [bold]No Intraday Strategies[/bold]
     The system is designed for daily timeframes. Intraday (day trading)
     would need tick-level data and much faster execution.

[bold yellow]DATA FRESHNESS:[/bold yellow]

  - Price data is cached for 24 hours by default (configurable)
  - Use [green]python -m src.main cache --clear[/green] to force fresh data
  - Fundamentals update quarterly (earnings reports)
  - Screener results are cached separately

[bold yellow]DISCLAIMER:[/bold yellow]

  This tool is for educational and informational purposes only.
  It does NOT constitute financial advice. Stock markets are inherently
  unpredictable. No algorithm, no matter how sophisticated, can
  guarantee profits. Always:
    - Do your own research (DYOR)
    - Never invest money you can't afford to lose
    - Consider consulting a licensed financial advisor
    - Start with paper trading before using real money
"""
    console.print(text)


# =============================================================================
# TOPIC: Commands
# =============================================================================
def _help_commands():
    console.print()
    console.print(Panel("[bold]All CLI Commands[/bold]", border_style="cyan"))

    table = Table(box=box.ROUNDED, show_lines=True)
    table.add_column("Command", style="bold cyan", width=50)
    table.add_column("Description", width=45)

    commands = [
        ("python -m src.main scan", "Full market scan with staged filtering"),
        ("python -m src.main scan --strategy short_term_momentum", "Scan using a specific strategy"),
        ("python -m src.main scan --theme artificial_intelligence", "Scan stocks in a theme"),
        ("python -m src.main scan --sector semiconductors", "Scan stocks in a sector"),
        ("python -m src.main scan --top 5", "Show only top 5 results"),
        ("python -m src.main scan --no-alert", "Scan without sending Telegram alerts"),
        ("", ""),
        ("python -m src.main analyze NVDA", "Deep analyze a single stock"),
        ("python -m src.main analyze NVDA AAPL TSLA AMD", "Analyze multiple stocks"),
        ("python -m src.main analyze NVDA -s value_investing", "Analyze with specific strategy"),
        ("", ""),
        ("python -m src.main watchlist", "Analyze all stocks in your watchlist"),
        ("python -m src.main trending", "Show trending sectors"),
        ("python -m src.main alert", "Scan + send Telegram alerts"),
        ("python -m src.main strategies", "List all available strategies"),
        ("", ""),
        ("python -m src.main cache --stats", "Show cache statistics"),
        ("python -m src.main cache --clear", "Clear all cached data"),
        ("", ""),
        ("python -m src.main help", "Show all help topics"),
        ("python -m src.main help strategies", "Learn about strategies"),
        ("python -m src.main help indicators", "Learn about indicators"),
        ("python -m src.main help risk", "Learn about risk management"),
    ]

    for cmd, desc in commands:
        if cmd == "":
            table.add_row("", "")
        else:
            table.add_row(cmd, desc)

    console.print(table)


# =============================================================================
# TOPIC: Glossary
# =============================================================================
def _help_glossary():
    console.print()
    console.print(Panel("[bold]Financial Terms Glossary[/bold]", border_style="cyan"))

    terms = [
        ("OHLCV", "Open, High, Low, Close, Volume - the 5 data points for each trading day"),
        ("P/E Ratio", "Price-to-Earnings ratio. Stock price divided by earnings per share. Lower = cheaper."),
        ("PEG Ratio", "P/E divided by growth rate. Under 1 = undervalued relative to growth."),
        ("P/B Ratio", "Price-to-Book. Stock price vs company's book value. Under 1 = selling below assets."),
        ("EV/EBITDA", "Enterprise Value to EBITDA. A valuation metric that accounts for debt."),
        ("ROE", "Return on Equity. How efficiently a company uses shareholder money. Higher = better."),
        ("Market Cap", "Total value of all shares. Large cap > $10B, Mid > $2B, Small > $300M."),
        ("Free Cash Flow", "Cash generated after expenses. Positive = company generates real cash."),
        ("Debt-to-Equity", "Total debt / shareholder equity. Lower = less leveraged. Under 1 = comfortable."),
        ("Dividend Yield", "Annual dividend / stock price. 3% means $3/year for every $100 invested."),
        ("Beta", "Volatility relative to market. Beta 1 = moves with market, >1 = more volatile."),
        ("Golden Cross", "SMA50 crosses above SMA200. Classic long-term bullish signal."),
        ("Death Cross", "SMA50 crosses below SMA200. Classic long-term bearish signal."),
        ("Support Level", "Price floor where buyers historically step in. Stock tends to bounce here."),
        ("Resistance Level", "Price ceiling where sellers historically appear. Stock tends to stall here."),
        ("Breakout", "When price moves above resistance or below support with strong volume."),
        ("Mean Reversion", "Theory that prices tend to return to their average over time."),
        ("Momentum", "Tendency for rising stocks to continue rising (and falling to continue falling)."),
        ("ATR", "Average True Range. Daily volatility measure in dollar terms."),
        ("R:R Ratio", "Risk-to-Reward ratio. 3:1 means potential gain is 3x the potential loss."),
        ("Stop-Loss", "Price level where you automatically sell to limit losses."),
        ("Take-Profit", "Price level where you automatically sell to lock in gains."),
    ]

    table = Table(box=box.ROUNDED, show_lines=True)
    table.add_column("Term", style="bold cyan", width=16)
    table.add_column("Meaning")

    for term, meaning in terms:
        table.add_row(term, meaning)

    console.print(table)


# =============================================================================
# Handler map
# =============================================================================
TOPIC_HANDLERS = {
    "overview": _help_overview,
    "strategies": _help_strategies,
    "scan": _help_scan,
    "setup": _help_setup,
    "indicators": _help_indicators,
    "scoring": _help_scoring,
    "risk": _help_risk,
    "config": _help_config,
    "enhance": _help_enhance,
    "missing": _help_missing,
    "commands": _help_commands,
    "glossary": _help_glossary,
}
