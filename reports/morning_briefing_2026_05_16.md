# Morning Briefing — 2026-05-16

*Strategy:* `composite_d05_r63` (top 5% factor blend, quarterly rebalance)

## Account snapshot

- Paper equity: **$41,042.60** | cash: $-2,610.93 | positions: 23
- Unrealized P&L: $-861.39 (-2.10%)
- Per-position target size: $1,675.91 (4.2% of equity)

## Today's actions

| Action | Count | Notional |
|---|---|---|
| 🟢 NEW BUYS | 23 | ~$38,527.82 (post-sells) |
| 🟡 KEEP / RESIZE | 1 | $1,693.93 (mtm) |
| 🔴 EXIT | 22 | $41,959.60 (mtm) |

**EXIT list:** AAPL, ADI, ALAB, APH, ARM, AVGO, CCJ, DNN, LITE, LRCX, NKE, NXPI, NYT, PAYP, RCI, SNDK, SNPS, SPY, TER, TSLA, TXN, VZ
**NEW BUY list:** AES, APA, BK, C, CF, DOW, GOOG, GOOGL, GS, HCA, HST, INCY, MO, MS, MTB, NEM, OXY, RF, STT, SYF, TFC, USB, VTRS
**KEEP:** DELL

## Top 5 picks (strongest composite z)

| Rank | Ticker | z-score | Why |
|---|---|---|---|
| #1 | **APA** | +2.90 | MOM+VAL |
| #2 | **VTRS** | +2.38 | MOM |
| #3 | **GOOG** | +2.24 | MOM+QUAL |
| #4 | **GOOGL** | +2.24 | MOM+QUAL |
| #5 | **DELL** | +2.21 | MOM |

## Sector exposure

- Financial Services 10 (42%) | Healthcare 3 (12%) | Basic Materials 3 (12%) | Energy 2 (8%)
- ⚠️ **Financial Services concentration > 30%** — single-sector drawdown will hit harder than SPY

## Earnings calendar overlap

- Within 2 weeks: DELL(12d)

## Expected portfolio P&L (63 trading days, from backtest)

- **Base case (median):** $2,828.52 (+6.9%)
- Bull case (p75): $7,215.77 (+17.6%)
- Bear case (p25): $-630.89 (-1.5%)

**Honest caveat:** these are backtest per-pick distributions on a 63-day hold, scaled to the equity. Real-world drift is real. Backtest 3-window avg alpha vs SPY: **+1.88%/yr**.

## Stress-test range

- **Worst case (COVID-style -35% crash):** portfolio -46.2% ($-18,963)
- **Best case (SPY +10% rally):** portfolio +9.1% ($+3,754)
- Full detail: `reports/stress_test_2026_05_16.md`

## Drill-down

- **Per-stock plans:** `reports/portfolio_analysis_2026_05_16.md`
- **Exit plan:** `reports/exit_plan_2026_05_16.md`
- **Stress test:** `reports/stress_test_2026_05_16.md`
- **Watchlist:** `reports/watchlist_2026_05_16.md`
- **Position monitor:** `reports/position_monitor_2026_05_16.md`
- **Raw picks JSON:** `data/daily_picks/2026-05-16.json`
- **Strategy verdict:** `reports/factor_strategy_report_2026_05_16.md`
- **User guide:** `FACTOR_STRATEGY.md`

## Workflow today

1. Review this briefing
2. Read per-stock plans for new buys (23 names)
3. Check exit plan for the 22 sells — note any earnings-blackout delays
4. Adjust `config/settings.yaml` safety gates if needed (`max_open_positions`, `max_order_value_usd`)
5. Dry-run paper trade: `uv run python -m scripts.paper_trade_factor_picks --picks-date 2026-05-16`
6. Execute (after sanity-checking the plan): `... --execute`
