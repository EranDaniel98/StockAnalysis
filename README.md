# Stock Market Scanner

A config-driven stock market analysis CLI that scans the US market, scores stocks using technical + fundamental + statistical models, and generates step-by-step broker-actionable recommendations with risk management.

## Features

- **Market Scanning** - Staged filtering from ~6,000 US stocks down to top opportunities
- **5 Analysis Engines** - Technical (RSI, MACD, Bollinger, SMA/EMA, Stochastic, Volume), Fundamental (P/E, PEG, ROE, growth, debt), Pattern Detection (10 candlestick patterns, support/resistance, RSI divergence), Statistical (momentum, mean reversion, seasonality, trend regression), Trend Detection (sector alignment, theme matching)
- **5 Built-in Strategies** - Long-Term Growth, Short-Term Momentum, Value Investing, Swing Trading, Dividend Income
- **Portfolio Tracking** - Import your holdings, see real-time P&L, get position-level ADD/HOLD/TRIM/SELL recommendations with concrete share counts
- **Budget Allocation** - Tell the system how much you want to invest and it splits your money across top picks with score-weighted sizing
- **Step-by-Step Broker Instructions** - Every recommendation includes numbered steps: which order type (Market/Limit/Stop), at what price, why that order type, stop-loss, take-profit, risk/reward in dollars
- **Risk Management** - ATR-based stop-loss, risk/reward targeting, position sizing (Fixed Fractional or Kelly Criterion), sector diversification limits
- **Market-Aware Caching** - 5-minute cache during market hours (prices change), 24-hour cache after close, `--fresh` flag for instant live data
- **Telegram Alerts** - Push notifications for high-scoring opportunities
- **100% Configurable** - Every threshold, weight, parameter, and filter lives in YAML config files. Zero hardcoded values.

## Quick Start

### Prerequisites

- Python 3.10+
- pip

### Installation

```bash
git clone https://github.com/EranDaniel98/stock-market-scanner.git
cd stock-market-scanner
pip install -r requirements.txt
```

### Optional: Telegram Alerts

```bash
cp .env.example .env
# Edit .env with your Telegram bot token and chat ID
```

### First Run

```bash
# Analyze a few stocks
python -m src.main analyze NVDA AAPL GOOGL

# Analyze with a budget (get step-by-step buy instructions)
python -m src.main analyze NVDA AAPL GOOGL --budget 10000

# View your portfolio
python -m src.main portfolio --analyze

# Full market scan
python -m src.main scan --strategy long_term_growth --budget 50000

# Get help on any topic
python -m src.main help
```

## Commands

| Command | Description |
|---------|-------------|
| `analyze TICKER [...]` | Deep analysis of specific stocks |
| `scan` | Full market scan with staged filtering |
| `watchlist` | Analyze stocks from your watchlist |
| `portfolio` | View portfolio P&L and position recommendations |
| `trending` | Show trending sectors |
| `alert` | Run scan and send Telegram alerts |
| `strategies` | List all available strategies |
| `help [topic]` | Detailed help on any topic |
| `cache --stats/--clear` | Manage data cache |

### Common Flags

| Flag | Description |
|------|-------------|
| `--strategy NAME` | Use a specific strategy (default: `long_term_growth`) |
| `--budget AMOUNT` | Get investment plan with dollar allocation and order instructions |
| `--fresh` | Bypass cache, fetch live market data |
| `--theme NAME` | Filter by theme (e.g., `artificial_intelligence`) |
| `--sector NAME` | Filter by sector (e.g., `semiconductors`) |
| `--top N` | Show only top N results |

## Output Examples

### Stock Analysis

```
NVDA - NVIDIA Corporation | BUY (68/100)

Score Breakdown:
  Technical    ||||||||||||--------  61.1  (weight: 20%)
  Fundamental  |||||||||||||-------  68.8  (weight: 35%)
  Pattern      ||||||||||----------  50.0  (weight: 5%)
  Statistical  |||||||||||---------  57.0  (weight: 25%)
  Trend        |||||||||||||||-----  76.7  (weight: 15%)

Key Signals:
  + SMA20/50/200: Price above all major moving averages
  + MACD: Bullish crossover
  + PEG: Undervalued at 0.66
  + Revenue: Strong growth 73.2%
  - Debt: High at 7.25x
  - RSI Divergence: Bearish (price up, RSI down)
```

### Step-by-Step Order Instructions

```
NVDA -- BUY -- 6 shares @ $215.52

  Step 1: Place a Buy Stop Order for 6 shares of NVDA at $219.83
  Step 2: Wait -- order only fills if price breaks above $219.83
  Step 3: Once filled, immediately set a Sell Stop Loss at $200.80
  Step 4: Set a Sell Limit (take profit) at $259.68
  Step 5: If price never reaches $219.83, you don't buy and lose nothing

  Why Stop Order: Near resistance at $216.83 -- buying at resistance risks
  a rejection. The Stop Order waits for a confirmed breakout above $219.83

  Risk: $88 | Reward: $265 | Ratio: 3:1
```

### Portfolio Tracking

```
Portfolio Overview
  Total Portfolio:   $41,879
  Invested:          $13,786
  Unrealized P&L:    +$603 (+4.57%)
  Cash Available:    $28,093

ADD -- AVGO (14.68 shares)
  Step 1: Buy 1 more share of AVGO
  Step 2: Order: Limit @ $416.62 (3% below current $429.50)
  Step 3: After fill, set stop-loss at $399.36 for ALL 15.68 shares
  Step 4: New avg price: ~$401.96 | New total value: ~$6,734
  Step 5: Risk: $473 | Target: $520.60 (+21.2%)
```

## Architecture

```
stock-market-scanner/
├── config/
│   ├── settings.yaml        # All thresholds, parameters, filters
│   ├── sectors.yaml         # Sector/theme definitions, watchlist
│   ├── strategies.yaml      # 5 strategies with custom weights
│   └── portfolio.yaml       # Your holdings for P&L tracking
├── src/
│   ├── main.py              # CLI entry point (argparse)
│   ├── config_loader.py     # YAML config with nested access
│   ├── portfolio.py         # Portfolio P&L and action recommendations
│   ├── help_system.py       # 12-topic help system
│   ├── data/
│   │   ├── fetcher.py       # yfinance OHLCV with caching
│   │   ├── fundamentals.py  # Financial metrics (P/E, ROE, growth, etc.)
│   │   ├── screener.py      # Stock discovery with staged filtering
│   │   └── cache.py         # SQLite cache, market-hours aware
│   ├── analysis/
│   │   ├── technical.py     # RSI, MACD, SMA/EMA, Bollinger, Stochastic, ATR
│   │   ├── fundamental.py   # Valuation, growth, profitability, health scoring
│   │   ├── patterns.py      # 10 candlestick patterns, support/resistance
│   │   ├── statistical.py   # Momentum, mean reversion, seasonality, regression
│   │   └── trend_detector.py# Sector trending, theme matching
│   ├── scoring/
│   │   ├── engine.py        # Weighted composite scoring
│   │   └── recommender.py   # Recommendations, allocation, order instructions
│   ├── display/
│   │   └── cli_output.py    # Rich terminal tables, panels, action cards
│   └── alerts/
│       └── telegram_bot.py  # Telegram notifications
├── data/
│   └── cache.db             # Auto-generated SQLite cache
├── .env.example             # Telegram credentials template
├── requirements.txt
└── .gitignore
```

### Data Flow

```
DISCOVER ──> FETCH ──> ANALYZE ──> SCORE ──> RECOMMEND ──> DISPLAY/ALERT
   │            │          │          │           │
   │            │          │          │           └─ Order type, steps,
   │            │          │          │              stop-loss, take-profit,
   │            │          │          │              position sizing
   │            │          │          │
   │            │          │          └─ Weighted composite (0-100)
   │            │          │             per strategy weights
   │            │          │
   │            │          ├─ Technical (RSI, MACD, MA, Bollinger, Volume)
   │            │          ├─ Fundamental (P/E, growth, ROE, debt)
   │            │          ├─ Patterns (candlestick, support/resistance)
   │            │          ├─ Statistical (momentum, mean reversion, seasonality)
   │            │          └─ Trend (sector alignment, theme matching)
   │            │
   │            ├─ Price data (yfinance, 5yr OHLCV)
   │            └─ Fundamentals (P/E, revenue, margins, etc.)
   │
   ├─ Finviz screener (sector, market cap, volume)
   ├─ Theme tickers (AI, cloud, cyber, EV)
   └─ Custom watchlist
```

## Configuration

Everything is configurable via YAML files in `config/`. No values are hardcoded.

### Key Config Files

**`config/settings.yaml`** - Global parameters:
- Data source, cache expiry, market filters
- All technical indicator periods and thresholds (RSI, MACD, Bollinger, etc.)
- Fundamental filters (max P/E, min growth, max debt, etc.)
- Scoring thresholds (what score = BUY vs HOLD vs SELL)
- Risk management (stop-loss method, position sizing, sector caps)
- Alert and display settings

**`config/strategies.yaml`** - Trading strategies:
- Each strategy defines its own analysis weights
- `long_term_growth`: Fundamentals 35%, Statistical 25%, Technical 20%
- `short_term_momentum`: Technical 45%, Pattern 25%, Statistical 15%
- `value_investing`: Fundamentals 45%, Statistical 30%, Technical 10%
- `swing_trading`: Technical 35%, Pattern 30%, Statistical 20%
- `dividend_income`: Fundamentals 40%, Statistical 30%, Trend 15%

**`config/sectors.yaml`** - Market universe:
- Sector definitions with industry mappings
- Cross-sector themes (AI, Cloud, Cybersecurity, EV, Robotics)
- Known tickers per theme
- Custom watchlist

**`config/portfolio.yaml`** - Your holdings:
- Current positions with shares and average price
- Available cash for new investments
- Action thresholds (when to ADD, HOLD, TRIM, SELL)

## Data Sources

| Source | Data | Cost | API Key |
|--------|------|------|---------|
| Yahoo Finance (yfinance) | Price data, fundamentals, analyst ratings | Free | Not required |
| Finviz (finvizfinance) | Stock screening, discovery | Free | Not required |
| Telegram Bot API | Push notifications | Free | Required for alerts |

## Strategies

| Strategy | Horizon | Risk | Focus |
|----------|---------|------|-------|
| Long-Term Growth | 6-24 months | Medium | Revenue growth, earnings, ROE |
| Short-Term Momentum | 1-30 days | High | RSI, MACD, volume spikes |
| Value Investing | 12-36 months | Low-Medium | Low P/E, low debt, cash flow |
| Swing Trading | 2-14 days | Medium-High | Bollinger, candlestick patterns |
| Dividend Income | 12+ months | Low | Dividend yield, payout ratio |

Run `python -m src.main help strategies` for detailed explanations of each.

## Help System

Built-in help covers 12 topics:

```bash
python -m src.main help overview      # System overview and readiness
python -m src.main help strategies    # All strategies explained
python -m src.main help scan          # How scanning works
python -m src.main help setup         # Installation and API setup
python -m src.main help indicators    # Technical indicators explained
python -m src.main help scoring       # How scoring works
python -m src.main help risk          # Risk management explained
python -m src.main help config        # Configuration guide
python -m src.main help enhance       # Enhancement roadmap
python -m src.main help missing       # Known limitations
python -m src.main help commands      # Full command reference
python -m src.main help glossary      # Financial terms dictionary
```

## Disclaimer

This tool is for **educational and informational purposes only**. It does not constitute financial advice. Stock markets are inherently unpredictable. No algorithm can guarantee profits. Always do your own research, never invest money you can't afford to lose, and consider consulting a licensed financial advisor.

## License

Private - All rights reserved.
