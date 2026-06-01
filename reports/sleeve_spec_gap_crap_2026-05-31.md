# Sleeve Spec — "Gap & Crap" Intraday Earnings-Rejection Fade

The **first candidate from the discovery search to pass a powered, controlled,
multi-regime, knife-edge-robust test.** Surfaced by the 3-model panel (#4). This is an
**intraday** strategy — it needs an execution path separate from the EOD factor pipeline.
NOT to be deployed before the live OOS paper run's 2026-08-27 review.

## 1. Thesis & scenario

In a complacent regime, an earnings **gap-up that is rejected in the first 30 minutes**
(price fails to hold the open on heavy volume) reveals institutional VWAP-distribution
algos using retail/headline-chasing liquidity to unwind blocks. Fade it intraday.
Structurally distinct from PEAD, which buys *confirmed* gaps — here we short *rejected*
ones. The control arms prove the distinction (below).

## 2. Trigger & execution (hardened)

- **Universe:** S&P-500 large-cap, 20d median $-volume > $50M, price > $5 (liquid, easy-to-borrow).
- **Regime filter:** SPY > 50d SMA **AND** VIX < 15 (complacent bull).
- **Gap:** earnings day (or day after), open/prior-close − 1 > **4%** (robust 3-5%, see §4).
- **Rejection (all required):** 30-min VWAP < open **AND** price@10:00 < open **AND**
  first-30min $-volume > 10% of 20d ADV.
- **Trade:** short at 10:01 (after the 10:00 decision bar completes — no lookahead),
  cover at 15:55. **Strictly intraday, no overnight.** Beta exposure ~0 (single-session).

## 3. Evidence (pooled 2018-2026, n=1167 events; gap=4%)

| Arm | n | mean intraday fade | t | win |
|---|---|---|---|---|
| **A — earnings gap-up + rejection (the trade)** | 252 | **+0.410%** | **+2.94** | 58% |
| B — earnings gap-up + held (PEAD continuation) | 358 | −0.109% | −0.92 | 50% |
| C — non-earnings gap-up + rejection (control) | 228 | −0.105% | −0.65 | 48% |

A beats the generic-gap-fade control C by **+0.52%** → the edge is the *earnings-rejection*
interaction, not generic opening-range mean-reversion (both controls are *negative*).

## 4. Robustness (the hardening)

- **Knife-edge check — PASS (plateau).** Gap threshold 3/4/5%: A = +0.538%/+0.410%/+0.386%,
  t = 3.96/2.94/2.15 — significant at all three; controls negative at all three.
- **Broad across years, not one-window.** Arm A positive 2017 (+0.24%), 2018 (+0.40%),
  2019 (+0.69%, t2.87), 2023 (+0.52%), 2024 (+0.19%). (2020 & 2025 are n=3, ignorable.)
- **Not outlier-driven.** Median (+0.51%) > mean (+0.41%); winsorized(5/95) +0.37%. Left-tail
  losers pull the mean down — the typical trade is solidly positive. (Top-5 of 252 = 34% of PnL.)
- **Survives costs.** Net +0.36%@5bps (t2.6) / +0.31%@10bps (t2.2). Fails ~20bps (t1.5) — so
  it needs tight large-cap execution, which the liquidity filter ensures.

## 5. Risk / return profile

- **~+9-11%/yr full-notional** (≈30 non-overlapping intraday trades/yr × +0.31-0.36% net),
  **trade-Sharpe ~0.8.** Capital recycles same-day, so notional turns ~30×/yr.
- **Fat tails:** worst single trade −6.55%, best +8.23%. Needs per-trade sizing / a hard
  intraday stop; a single −6% on full notional is the tail to bound.
- **Capacity:** modest — large-cap earnings gap-ups in complacent regimes, ~30/yr.

## 6. The one real risk: recency decay

Arm A weakens over time: 2019 +0.69% → 2023 +0.52% → **2024 +0.19% (t0.55)**. The pooled
t2.94 is real and broad, but the *recent* signal is fading — consistent with the
VWAP-distribution/gap-fade pattern becoming more widely traded. **This is the watch-item:**
the edge is historically robust but its live strength is declining. Forward-paper it and
gate on a rolling-window significance check before committing capital.

## 7. Open items before go-live (post-2026-08-27)

1. **Intraday execution path** — short locate/borrow + 10:01 entry / 15:55 exit on Alpaca;
   the EOD factor pipeline does not handle intraday. Separate build.
2. **Forward-monitor the decay** — pre-register a kill rule (e.g., trailing-50-trade mean < 0).
3. **Slippage realism** — validate fills near the 10:01 minute close on live quotes; the
   ≤10bps cost assumption is the profitability hinge.
4. **Per-trade sizing for the −6% tail** + intraday stop.

## 8. Honest verdict

The **first robustly-hardened, controlled, cost-surviving edge** of the entire discovery
search — and an *orthogonal* one (intraday earnings microstructure, independent of the
live PEAD+quality core). It passes every test I threw at it: powered, multi-regime, plateau
across the trigger, broad across years, not outlier-driven. **But** it's modest (~Sharpe
0.8, ~30 trades/yr, small capacity), and its live signal is **decaying** (2024 barely
positive). Verdict: a genuine, defensible **intraday satellite candidate** worth a
forward-paper test after the August review — *gated on the decay not having killed it* —
not a large-capacity core. It is the one concrete, positive result to carry forward.
