# MVTP Report — minimal_baseline

**Verdict (auto-gates only): FAIL**  (3/8 auto-gates passed)

> A PASS here means the auto-gates passed. Manual gates below still need eyeballing before risking capital.

## Run metadata

- **Strategy:** `minimal_baseline`
- **Universe:** `russell_1000`
- **Window:** 2024-05-13 → 2026-05-13 (2.0y)
- **Starting capital:** $10,000
- **Pipeline version:** `2026-05-15-survivorship-haircut`
- **PIT fundamentals:** `True`
- **Trades (full window):** 254

## OOS headline numbers

| Metric | Value (point estimate) | 95% CI |
|---|---|---|
| OOS Sharpe | 2.89 | [0.66, 5.93] |
| OOS Sortino | 5.63 | — |
| OOS total return | 31.83% | [6.58, 83.11] |
| SPY return (matched) | 13.21% | — |
| Alpha vs SPY (matched) | 18.62% | — |
| OOS max drawdown | -4.39% | — |
| OOS Calmar | 10.09 | — |
| OOS win rate | 46.9% | [33.33, 60.42] |
| OOS trades | 96 | — |

_CIs from 500 block-bootstrap resamples on the OOS window (block_size=5). The Sharpe gate now uses both CI bounds, not the point estimate._

## Walk-forward CV (review #5)

- Folds: 5, mean Sharpe = 2.28, min = -0.61, max = 4.38
- Threshold (mean Sharpe): 0.5
- **Gate:** FAIL — min fold Sharpe -0.61 <= 0 — at least one fold lost money

| Fold | Range | Trades | Status | Sharpe | Return % | Max DD % |
|---|---|---|---|---|---|---|
| 0 | 2024-05-13→2024-10-06 | 39 | ok | 1.57 | 12.51 | -7.37 |
| 1 | 2024-10-06→2025-03-01 | 46 | ok | 2.72 | 19.58 | -4.91 |
| 2 | 2025-03-01→2025-07-25 | 51 | ok | -0.61 | -4.92 | -13.06 |
| 3 | 2025-07-25→2025-12-18 | 56 | ok | 3.34 | 16.96 | -3.36 |
| 4 | 2025-12-18→2026-05-13 | 62 | ok | 4.38 | 25.62 | -4.39 |

## Concentration sensitivity (top-5 winners removed)

- **Window:** OOS (96 trades)
- **Headline Sharpe:** 2.89  → **Stripped Sharpe:** 1.96  = **drop 0.93**
- **Top-5 contribution:** 45.73% of total P&L ($1,851 of $4,047)
- **Gate (drop <= 0.4):** **FAIL**

| # | Ticker | Entry | Exit | P&L | P&L % |
|---|---|---|---|---|---|
| 1 | CIEN | 2026-03-09 | 2026-03-25 | $439.31 | +50.56% |
| 2 | SNDK | 2026-04-13 | 2026-05-04 | $372.83 | +42.98% |
| 3 | ECG | 2026-03-02 | 2026-05-05 | $372.78 | +39.12% |
| 4 | CIEN | 2026-03-30 | 2026-05-11 | $360.19 | +43.80% |
| 5 | MU | 2026-03-30 | 2026-04-27 | $305.89 | +42.15% |

## Acceptance gates (review item #7)

| # | Gate | Result | Detail |
|---|---|---|---|
| 1 | OOS Sharpe within [0.7, 1.5] | **FAIL** | Sharpe = 2.89 [95% CI 0.66, 5.93]. Gate now uses the CI: both bounds must lie in [0.7, 1.5]. Lower bound < 0.7 = no edge; upper bound > 1.5 = suspect (likely leakage). |
| 2 | Alpha vs SPY (matched, annualized) within [+2%, +8%] | **FAIL** | OOS alpha = 18.62%, annualized = 9.31%/yr over 2.0y. Alpha > 8%/yr on retail long-only US is a red flag for survivorship / lookahead. |
| 3 | OOS max drawdown >= -20.0% | **PASS** | OOS max DD = -4.39%. |
| 4 | OOS trade count >= 200 | **FAIL** | OOS trades = 96. Below 200 = Sharpe CI is wide; consider extending the window or running on a denser universe. |
| 5 | Walk-forward CV passes (all folds > 0 + mean >= threshold) | **FAIL** | folds=5, mean Sharpe=2.28, min Sharpe=-0.61, reason: min fold Sharpe -0.61 <= 0 — at least one fold lost money |
| 6 | Pipeline version >= 2026-05-15 | **PASS** | pipeline_version='2026-05-15-survivorship-haircut'; required post-silent-50-fix (2026-05-15). |
| 7 | Survivorship-bias guard active (severity != bypassed) | **PASS** | survivorship_bias.severity='haircut_estimated'. 'haircut_estimated' is the strongest non-PIT signal; 'bypassed' would mean the operator opted out of the guard. |
| 8 | Top-5 trades removed: Sharpe drop <= 0.4 | **FAIL** | Headline OOS Sharpe = 2.89, stripped (top-5 winners removed) = 1.96, drop = 0.93. Top-5 trades accounted for 45.73% of total P&L. Threshold: drop <= 0.4. Drop > 0.4 = edge is concentrated in a few lucky trades; live performance is unlikely to replicate. |

### Manual gates (review qualitatively)

- [ ] **MANUAL: Sharpe stability across ±10% on min_score / atr_stop** — Run two extra sweeps with min_score ±10% and atr_stop ±10%; spread must be < 0.5 Sharpe. Auto-check pending.
- [ ] **MANUAL: bear-regime trades (n, win rate, mean return)** — See regimes block in the JSON; review qualitatively.

## Operator gates (review #7, must all be checked)

- [ ] Kill switch implemented + tested (`trading.trading_enabled`)
- [ ] Max-daily-loss limit enforced (`trading.circuit_breakers.max_daily_loss_pct`)
- [ ] Max-drawdown halt enforced (`trading.circuit_breakers.max_drawdown_halt_pct`)
- [ ] Earnings blackout enforced (fail-loud)
- [ ] Reconciliation orphan-alert wired
- [ ] Stream-bus is_healthy monitored
- [ ] score_valid=False refusal applies to entries AND exits
- [ ] Bracket SL/TP atomically submitted at entry
- [ ] Survivorship-bias guard active on universe
- [ ] Walk-forward CV report present

## Warnings emitted by the backtest

- PIT fundamentals active: loader covers 98% of universe. Fundamental weight 30% scored against EDGAR PIT rows.
- Survivorship bias: universe is built from current-snapshot ticker lists. Stocks that delisted, went bankrupt, or were acquired before today are excluded entirely — results are biased upward by an unknown amount (typically 1-3%/yr for large-cap windows, more for small-cap or longer windows).

---

If every auto-gate PASSes AND every manual + operator checkbox is ticked, the strategy is cleared for the **Phase 2 ($500 / $50 per position)** rung of the capital safety ladder. Larger sizing requires Phase 3 evidence.