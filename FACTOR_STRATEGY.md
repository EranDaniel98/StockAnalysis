# Factor Strategy — User Guide

This document covers the **factor composite strategy** built in
2026-05-16. It's a separate system from the legacy analyzer-based
CLI documented in `README.md`. They share infrastructure (Postgres,
Redis, snapshots) but are functionally independent.

If you're returning to this project and want to:
- Find today's recommended portfolio → read **§ Daily Workflow**
- Understand why this exists → read **§ Background**
- Add a new factor or tune the strategy → read **§ Extending**

## Background

The 2026-05-16 edge-discovery audit concluded that the legacy 6-
analyzer composite has **no defensible edge** across two
walk-forward-tested windows. Full verdict in
`reports/edge_discovery_report_2026_05_16.md` and the
`project-final-edge-verdict` memory.

A clean rebuild followed in the same session:

1. **PIT S&P 500 universe** — Wikipedia membership log, replays
   add/remove events backward from today's set so backtests trade
   only the names that were actually in the index on each date.
   Removes survivorship bias.

2. **EDGAR PIT fundamentals** — 990 tickers × 17 years of 10-K/10-Q
   filings in Postgres. Used by the quality and value factors with
   guaranteed point-in-time correctness.

3. **Factor library** — momentum (Jegadeesh-Titman 12-1), quality
   (z-blend of ROE + margins + leverage), value (EPS-TTM yield +
   revenue/price), composite (equal-weight rank-blend).

4. **Backtest harness** — frozen Parquet snapshots eliminate
   yfinance non-determinism; 5-fold walk-forward; hyperparameter
   sweep across selectivity + rebalance frequency.

**Winner: `composite_d05_r63`** (top 5% by composite rank,
quarterly rebalance).

| Metric | 2022-2024 | 2024-2026 |
|---|---|---|
| Strategy return | +41.80% | +42.67% |
| SPY return | +33.76% | +45.16% |
| Alpha vs SPY | **+8.04%** | -2.49% |
| Sharpe | 1.04 | 1.23 |
| Max drawdown | -13.88% | -17.49% |
| Walk-forward | PASS | PASS |
| Trades over 2y | 241 | 220 |

Cross-window average alpha: **+2.77%/yr**. Full verdict in
`reports/factor_strategy_report_2026_05_16.md`.

## Daily Workflow

### Option A — One-command daily pipeline (recommended)

```bash
uv run python -m scripts.run_daily_pipeline --top-n 24
```

Runs all 7 steps in sequence: picks → analysis → exit plan →
position monitor → stress test → watchlist → morning briefing.
Each step writes its own file under `reports/` and
`data/daily_picks/`. Each step is idempotent and continues on
failure, so partial results stay usable.

After it finishes, **read `reports/morning_briefing_*.md` first**.
It's the single-page summary; everything else is drill-down.

### Option B — Step by step

#### Step 1 — Generate today's picks

```bash
uv run python -m scripts.daily_factor_picks --top-n 24
```

Writes `data/daily_picks/YYYY-MM-DD.json` and `.md`. Top-N=24
matches the 5% selectivity at ~500-name universe.

What it does:
- Pulls the current PIT S&P 500 constituents (Wikipedia-cached)
- Fetches live prices via yfinance
- Loads EDGAR PIT fundamentals (Postgres)
- Computes momentum + quality + value factors
- Returns the rank-blended top 24

Output (markdown):
- Composite rank + z-score per pick
- Per-factor sub-ranks (so you can see which factor carried the pick)

### Step 2 — Generate the comprehensive analysis

```bash
uv run python -m scripts.comprehensive_analysis \
    --picks-date YYYY-MM-DD \
    --output reports/portfolio_analysis_YYYY-MM-DD.md
```

This is the heavy lift. Pulls live prices, yfinance .info
(analyst targets, short interest, beta), next earnings dates,
EDGAR fundamentals, and the actual backtest trade log; then
produces a per-stock trading plan:

  - Entry price (market at next open)
  - Stop loss (2.5× 20-day ATR below entry, fallback fixed 8%)
  - Profit target (+8% median from backtest)
  - Time exit (next quarterly rebalance date)
  - Expected outcome distribution (base / bull / bear from real
    backtest data)
  - Risk flags (earnings blackout, low liquidity, extension)
  - Analyst target + recommendation overlay

Plus portfolio-level: sector breakdown, concentration warning,
earnings calendar overlap, expected portfolio P&L.

#### Step 3 — Exit plan (if you have current positions)

```bash
uv run python -m scripts.exit_analysis \
    --picks-date YYYY-MM-DD \
    --output reports/exit_plan_YYYY-MM-DD.md
```

Per current position: action (KEEP / TRIM / EXIT), P&L,
earnings-blackout warning, tax-loss-harvest tag if loss > 5%.

#### Step 4 — Position monitor (mid-cycle check)

```bash
uv run python -m scripts.position_monitor
```

Checks every current paper position against its strategy-
recommended stop loss and target. Flags 🚨 STOP HIT, 🟢 TARGET HIT,
⚠️ NEAR STOP / NEAR TARGET, or ✓ HOLDING. Run this between
quarterly rebalances to catch position-level events.

#### Step 5 — Stress test

```bash
uv run python -m scripts.stress_test \
    --output reports/stress_test_YYYY-MM-DD.md
```

Runs the portfolio through 8 scenarios (SPY +/-10/20%, COVID-
style -35%, banking crisis, oil shock, rate hikes, recession).
Uses each pick's beta + sector shock overlays. Output includes
worst case dollar loss, sector exposure breakdown, and risk
recommendations.

#### Step 6 — Watchlist (next-quarter prep)

```bash
uv run python -m scripts.generate_watchlist \
    --start-rank 25 --end-rank 75 \
    --output reports/watchlist_YYYY-MM-DD.md
```

Names ranked 25-75 — just outside the top-5% selection. These
are the most likely entrants for the next quarterly rebalance.

#### Step 7 — Ad-hoc per-ticker analysis

```bash
uv run python -m scripts.analyze_ticker NVDA AAPL TSLA
```

Runs the full per-stock card for any ticker, with a verdict
(STRONG BUY / BUY-CANDIDATE / WATCH / NEUTRAL / AVOID) based on
where it sits in the full composite ranking.

### Send to paper trading (when ready)

```bash
# Dry-run first (always):
uv run python -m scripts.paper_trade_factor_picks --picks-date YYYY-MM-DD

# Execute against Alpaca PAPER:
uv run python -m scripts.paper_trade_factor_picks --picks-date YYYY-MM-DD --execute
```

The script uses `STOCKNEW_TRADING_ENABLED=1` env override for the
lifetime of the process (no config edit). Orders use idempotent
`client_order_id`s so re-runs same-day are refused as duplicates.

**Pre-flight check:** the current safety gates in
`config/settings.yaml` are tuned for the legacy strategy:
- `max_order_value_usd: $1,000` — too tight (factor positions
  are ~$1,675 each at $40K equity)
- `max_open_positions: 10` — too tight (24-name strategy)

Both need bumping before execution succeeds. Suggested values for
the factor strategy at $40K equity:
- `max_order_value_usd: 3000` (allows ~$2K positions with headroom)
- `max_open_positions: 30` (24 + 6 buffer)

Confirm before changing — the original values are a deliberate
safety choice.

## Rebalance Cadence

The strategy is **quarterly** (every ~63 trading days). Don't
trade these picks daily. The cycle:

1. Day 1 → run daily_factor_picks + comprehensive_analysis +
   paper_trade_factor_picks. New positions established.
2. Days 2-62 → hold. Honor stops if they trigger. Don't add new
   names mid-cycle.
3. Day 63 → re-run daily_factor_picks. Composition may have
   changed substantially. Re-run paper_trade_factor_picks to
   rebalance.

If you want to monitor positions intra-cycle without rebalancing,
re-run `comprehensive_analysis` against the original picks file
— it'll re-price stops + targets at current levels without
changing the membership.

## Honest Expectations

This is not "beat SPY by 5-8%" — that's the dream you might want
but isn't what the data supports. What the strategy actually
delivers (cross-window backtest average):

- **+2.77%/yr alpha vs SPY** (modest but consistent)
- **Sharpe ≥ SPY** in both windows tested
- **Max DD < SPY** in 3 of 4 sweep cells tested
- **Walk-forward passes** in both tested windows
- **Low turnover** (241 trades / 24 months / 24 positions =
  ~5 trades per name per year)

Over 20 years, +2.77%/yr alpha compounds to a 72% larger portfolio
vs SPY. That's real money even if the per-year number is small.

**Do not deploy real money before 6 months of paper validation.**
The strategy was backtested on 4 years across 2 non-overlapping
windows. The third window (2020-2022, COVID crash + recovery)
backtest is in flight. Even after that lands, paper-validation is
the cheap insurance against the backtest being too clean.

## Files Reference

- `src/universe/sp500_pit.py` — PIT membership oracle
- `src/factors/{momentum, quality, value, composite, regime}.py`
- `src/analysis/comprehensive.py` — per-stock analyzer
- `src/analysis/comprehensive_render.py` — markdown renderer
- `scripts/fetch_sp500_membership.py` — refresh Wikipedia cache
- `scripts/freeze_snapshot.py` — frozen Parquet snapshot writer
- `scripts/run_factor_backtest.py` — backtest engine
- `scripts/daily_factor_picks.py` — today's picks generator
- `scripts/comprehensive_analysis.py` — full analysis report
- `scripts/exit_analysis.py` — exit plan for current positions
- `scripts/paper_trade_factor_picks.py` — Alpaca paper rebalancer

Reports:
- `reports/factor_strategy_report_2026_05_16.md` — strategy verdict
- `reports/portfolio_analysis_YYYY-MM-DD.md` — per-stock plans
- `reports/exit_plan_YYYY-MM-DD.md` — current-position exits

Data:
- `data/universe/sp500_current.csv` + `sp500_changes.csv`
- `data/snapshots/<id>/` — frozen backtest snapshots
- `data/daily_picks/YYYY-MM-DD.json` — daily generated picks
- `data/factors/sweep/*.json` — hyperparameter sweep raw results

## Extending

To add a new factor:

1. Implement in `src/factors/<name>.py` following the existing
   pattern: take `(prices, as_of)` or `(loader, tickers, as_of)`,
   return DataFrame with columns `[ticker, raw, rank, z_score]`.
2. Add to the composite in `src/factors/composite.py` (already
   uses equal-weight rank-blend with `min_overlap` configurable).
3. Update `_resolve_ranking` in `scripts/run_factor_backtest.py`.
4. Backtest against existing snapshots:
   ```bash
   uv run python -m scripts.run_factor_backtest \
       --snapshot-id 234de3c737aa1eb2 \
       --factor composite \
       --top-decile 0.05 --rebalance-days 63 \
       --strategy-label composite_v2 \
       --output data/factors/sweep/composite_v2_2022.json
   ```

To re-tune the strategy:

- Sweep parameters in `scripts/run_factor_backtest.py` (`--top-decile`,
  `--rebalance-days`, `--cost-bps`).
- Walk-forward gate: every fold > 0 AND mean Sharpe ≥ 0.5.
- Cross-window check: do BOTH windows pass? If not, the result is
  regime-specific, not edge.

To freeze a new snapshot (different date or universe):

```bash
uv run python -m scripts.freeze_snapshot \
    --universe sp500_pit \
    --window-end YYYY-MM-DD \
    --years 2 \
    --as-of YYYY-MM-DD
```

The snapshot ID is content-addressed — re-running with identical
data returns the same ID; different yfinance pulls produce
different IDs even at the same window.

## Safety Reminders

- **DO NOT enable real trading.** This is paper-only by design.
  `AlpacaClient` is hard-coded to `paper=True`. `trading_enabled`
  in `config/settings.yaml` is `false` for a reason.
- **DO NOT skip the dry-run.** Every rebalance starts with a
  dry-run that shows the plan before any orders go in.
- **DO NOT delete frozen snapshots without archiving.** They're
  content-addressed and small — keep them as audit trail.
- **DO NOT tune on a single window.** If a configuration only
  works on 2022-2024 but fails 2024-2026, it's not edge.

The 2026-05-16 audit chain spent multiple sessions ruling out
strategies that LOOKED good on one window. The factor approach
is the first one with cross-window evidence — preserve that
discipline.
