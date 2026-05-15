# MVTP Report — minimal_baseline

**Verdict (auto-gates only): FAIL**  (5/8 auto-gates passed)

> A PASS here means the auto-gates passed. Manual gates below still need eyeballing before risking capital.

## Run metadata

- **Strategy:** `minimal_baseline`
- **Universe:** `russell_1000`
- **Window:** 2024-05-13 → 2026-05-13 (2.0y)
- **Starting capital:** $10,000
- **Pipeline version:** `2026-05-15-survivorship-haircut`
- **PIT fundamentals:** `True`
- **Trades (full window):** 286

## OOS headline numbers

| Metric | Value (point estimate) | 95% CI |
|---|---|---|
| OOS Sharpe | 1.84 | — |
| OOS Sortino | 2.39 | — |
| OOS total return | 24.24% | — |
| SPY return (matched) | 13.04% | — |
| Alpha vs SPY (matched) | 11.2% | — |
| OOS max drawdown | -9.06% | — |
| OOS Calmar | 4.0 | — |
| OOS win rate | 44.4% | — |
| OOS trades | 99 | — |

## Walk-forward CV (review #5)

- Folds: 5, mean Sharpe = 1.86, min = 0.45, max = 2.63
- Threshold (mean Sharpe): 0.5
- **Gate:** PASS — all folds OK

| Fold | Range | Trades | Status | Sharpe | Return % | Max DD % |
|---|---|---|---|---|---|---|
| 0 | 2024-05-13→2024-10-06 | 38 | ok | 2.3 | 17.62 | -6.78 |
| 1 | 2024-10-06→2025-03-01 | 68 | ok | 1.81 | 12.32 | -5.15 |
| 2 | 2025-03-01→2025-07-25 | 46 | ok | 0.45 | 2.15 | -10.24 |
| 3 | 2025-07-25→2025-12-18 | 67 | ok | 2.12 | 14.81 | -5.72 |
| 4 | 2025-12-18→2026-05-13 | 67 | ok | 2.63 | 19.26 | -9.06 |

## Concentration sensitivity (top-5 winners removed)

_Not applicable: unknown._

## Acceptance gates (review item #7)

| # | Gate | Result | Detail |
|---|---|---|---|
| 1 | OOS Sharpe within [0.7, 1.5] | **FAIL** | Sharpe = 1.84 [CI: n/a]. Re-run backtest with the bootstrap-CI-emitting engine to get the CI gate. |
| 2 | Alpha vs SPY (matched, annualized) within [+2%, +8%] | **PASS** | OOS alpha = 11.2%, annualized = 5.6%/yr over 2.0y. Alpha > 8%/yr on retail long-only US is a red flag for survivorship / lookahead. |
| 3 | OOS max drawdown >= -20.0% | **PASS** | OOS max DD = -9.06%. |
| 4 | OOS trade count >= 200 | **FAIL** | OOS trades = 99. Below 200 = Sharpe CI is wide; consider extending the window or running on a denser universe. |
| 5 | Walk-forward CV passes (all folds > 0 + mean >= threshold) | **PASS** | folds=5, mean Sharpe=1.86, min Sharpe=0.45, reason: all folds OK |
| 6 | Pipeline version >= 2026-05-15 | **PASS** | pipeline_version='2026-05-15-survivorship-haircut'; required post-silent-50-fix (2026-05-15). |
| 7 | Survivorship-bias guard active (severity != bypassed) | **PASS** | survivorship_bias.severity='haircut_estimated'. 'haircut_estimated' is the strongest non-PIT signal; 'bypassed' would mean the operator opted out of the guard. |
| 8 | Top-5 trades removed: Sharpe drop <= 0.4 | **FAIL** | Cannot evaluate: concentration_sensitivity unavailable. With <10 trades the metric is noise; extend the window or accept that this gate cannot pass. |

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