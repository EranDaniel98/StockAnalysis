# Morning Briefing — 2026-05-17

*Strategy:* `composite_d05_r63` (top 5% factor blend, quarterly rebalance)

## Account snapshot

- Paper equity: **$41,042.60** | cash: $-2,610.93 | positions: 23
- Unrealized P&L: $-861.39 (-2.10%)
- Per-position target size: $1,675.91 (4.2% of equity)

## Today's actions

| Action | Count | Notional |
|---|---|---|
| 🟢 NEW BUYS | 24 | ~$40,221.75 (post-sells) |
| 🟡 KEEP / RESIZE | 0 | $0.00 (mtm) |
| 🔴 EXIT | 23 | $43,653.53 (mtm) |

**EXIT list:** AAPL, ADI, ALAB, APH, ARM, AVGO, CCJ, DELL, DNN, LITE, LRCX, NKE, NXPI, NYT, PAYP, RCI, SNDK, SNPS, SPY, TER, TSLA, TXN, VZ
**NEW BUY list:** AES, APA, ATO, BK, CF, CFG, EOG, GILD, GS, HCA, HST, INCY, MO, MS, MTB, NEM, NTRS, OXY, RF, STT, SYF, TFC, USB, WDC

## Top 5 picks (strongest composite z)

| Rank | Ticker | z-score | Why |
|---|---|---|---|
| #1 | **APA** | +2.76 | MOM+VAL |
| #2 | **CF** | +2.28 | VAL |
| #3 | **NEM** | +2.20 | MOM |
| #4 | **SYF** | +1.98 | VAL |
| #5 | **MTB** | +1.93 | QUAL |

## Sector exposure

- Financial Services 11 (46%) | Energy 3 (12%) | Healthcare 3 (12%) | Basic Materials 2 (8%)
- ⚠️ **Financial Services concentration > 30%** — single-sector drawdown will hit harder than SPY

## Expected portfolio P&L (63 trading days, from backtest)

- **Base case (median):** $2,828.52 (+6.9%)
- Bull case (p75): $7,215.77 (+17.6%)
- Bear case (p25): $-630.89 (-1.5%)

**Honest caveat:** these are backtest per-pick distributions on a 63-day hold, scaled to the equity. Real-world drift is real. Backtest 3-window avg alpha vs SPY: **+1.88%/yr**.

## Insider activity flags (last 90 days)

**2 picks** show meaningful insider SELLING (net sales > 0.05% of market cap, with sells > 2× buys). This isn't disqualifying — the factor model still ranks these in the top 5% — but it's a yellow flag worth knowing:

- **2. CF — Basic Materials** — **BEARISH** — net $-72.18M; 36 sales ($72.18M), most recent 2026-04-28
- **4. SYF — Financial Services** — **BEARISH** — net $-35.05M; 19 sales ($35.05M), most recent 2026-05-01

## Stress-test range

- **Worst case (COVID-style -35% crash):** portfolio -46.5% ($-19,070)
- **Best case (SPY +10% rally):** portfolio +9.0% ($+3,703)
- Full detail: `reports/stress_test_2026_05_17.md`

## Drill-down

- **Per-stock plans:** `reports/portfolio_analysis_2026_05_17.md`
- **Exit plan:** `reports/exit_plan_2026_05_17.md`
- **Stress test:** `reports/stress_test_2026_05_17.md`
- **Watchlist:** `reports/watchlist_2026_05_17.md`
- **Position monitor:** `reports/position_monitor_2026_05_17.md`
- **Raw picks JSON:** `data/daily_picks/2026-05-17.json`
- **Strategy verdict:** `reports/factor_strategy_report_2026_05_16.md`
- **User guide:** `FACTOR_STRATEGY.md`

## Workflow today

1. Review this briefing
2. Read per-stock plans for new buys (24 names)
3. Check exit plan for the 23 sells — note any earnings-blackout delays
4. Adjust `config/settings.yaml` safety gates if needed (`max_open_positions`, `max_order_value_usd`)
5. Dry-run paper trade: `uv run python -m scripts.paper_trade_factor_picks --picks-date 2026-05-17`
6. Execute (after sanity-checking the plan): `... --execute`
