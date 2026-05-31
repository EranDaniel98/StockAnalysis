# Sleeve Spec — PEAD+Quality Beta-Neutral Long-Short (S&P-500)

Hardened candidate for a **post-2026-08-27 market-neutral sleeve** (NOT a core
replacement; NOT to be deployed before the live OOS paper run concludes its review).
All figures are phase-averaged Jensen's CAPM-α (9 rebalance offsets), net of the
stated costs incl. short borrow. Evidence: `reports/_ls_harden_sweep.log`,
`_ls_covid_tail.log`, and the long-short confirmation runs.

## 1. Thesis & scope

A dollar-/beta-neutral long-short of the existing **PEAD + quality** composite:
long the top decile, short the bottom decile, on the **PIT S&P-500 large-cap**
universe. The long-only book of these factors loads market beta (negative ungated
CAPM-α); hedging beta out via the short leg isolates the cross-sectional alpha. The
edge is the small, durable PEAD+quality signal the live system already trades —
**construction, not a new factor.**

**Scope is deliberate:** S&P-500 large-caps only. The signal is −10.7% on the
2000-name broad universe — but market-neutral construction *requires* liquidity and
cheap shortable borrow, which mid/small-caps lack, so large-cap scope is correct, not
a cherry-pick.

## 2. Hardened parameters (from the robustness sweep, 12 configs, bull+bear)

| Parameter | Value | Why |
|---|---|---|
| Universe | PIT S&P-500, re-resolved per rebalance | liquidity + borrow; fixes universe-freeze |
| Signal | PEAD + quality composite (sector-neutral quality) | the durable core |
| Legs | long top decile, short bottom decile, ½ capital each (gross ~1×, net ~0) | beta-neutral |
| **Decile width** | **0.15–0.20** | capacity + walk-forward stability (WF-pass 44% at 0.20 vs 0% at 0.10); accept lower α (+2.7–2.9%) for robustness |
| **Rebalance cadence** | **21 days** | dominates 63d on BOTH α and stability (+5.2%/+5.1%, tightest envelope std 0.7–0.8); PEAD drift decays in weeks |
| Hysteresis | 0.75 incumbent carry bonus | turnover control |
| Costs assumed | 30bps round-trip + 50bps/yr borrow | realistic; survives 50bps + 100bps borrow stress |
| Regime gate | **none** | gating made COVID *worse*; manage the tail by sizing, not timing |

## 3. Expected return / risk profile (phase-averaged, net of costs)

| Regime | CAPM-α (median) | notes |
|---|---|---|
| Bull (2024-26) | **+3.3%** (d0.10/63d) … **+5.2%** (21d) | 100% phases positive, ROBUST |
| Bear (2022-24) | **+6.5%** … +5.1% (21d) | 100% phases positive, ROBUST |
| **COVID crash (2020-22)** | **−4.5%, ~25% max drawdown** | the tail — un-timeable (see §4) |

Robust across decile width (0.05–0.20), cadence (21/63d), cost (5–50bps), and borrow
(50–100bps/yr): every one of 12 configs was ROBUST with 100% of phases positive in
both bull and bear. **This is a plateau, not a knife-edge.**

## 4. The COVID tail & the sizing rule (the binding risk)

The sleeve has an **intrinsic factor-crash tail**: in a fast liquidity crisis (COVID
2020) it loses ~4.5% CAPM-α with **~25% max drawdown** at gross-1×. This is **not
timing-fixable** — both a 200/75-SMA+VIX regime gate (made it −7.7%) and a VIX
exposure breaker (−5.0%) made it *worse* by de-risking into the V-shape rebound, and
faster (21d) cadence doesn't help either. This is the well-known "quant quake" family
behavior; the correct management is **size, don't time**:

> **Sizing rule:** allocate gross exposure G to the sleeve such that
> `G × 25% ≤ (acceptable worst-case sleeve contribution to portfolio drawdown)`.
> e.g. G = 10–20% → 2.5–5% worst-case portfolio hit from the factor crash.
> Run it as a **small satellite**, never at full book.

Optional secondary guard: a hard sleeve-level kill at −15% cumulative drawdown
(disable, revert that capital to core) — caps the tail without trying to time entry.

## 5. Open items before go-live (post-Aug-27)

1. **Longer-history validation.** All α figures are 2yr windows (±20-30pp phase
   envelope on the *level*; the *sign* is stable at 100% of phases, but magnitude is
   noisy). Re-validate on the $79 10yr history before sizing up.
2. **Walk-forward.** Low WF-pass at tight deciles is short-fold underpowering (d0.20
   hits 44%), corroborated by the tight phase envelope — but confirm on longer folds.
3. **Live execution is NOT wired.** Long-short on Alpaca needs margin/locate/borrow
   plumbing — a separate build, intentionally deferred.
4. **Borrow realism per-name.** 50–100bps/yr is right for liquid S&P names; verify no
   bottom-decile name is hard-to-borrow at rebalance (exclude if so).
5. **Capacity.** Decile 0.20 (~50 names/leg) is the capacity-friendly setting; size to
   ADV so the book is liquidatable in the COVID tail.

## 6. Honest verdict

A **real, robust, modest market-neutral alpha** (+3-5%/yr net in normal regimes,
cost- and borrow-survivable, plateau-stable) on S&P-500 large-caps, with a known
~25% factor-crash tail managed by sizing. It is the best-supported deployable artifact
from the discovery search — but it is a **satellite sleeve**, not a market-beating core,
and its magnitude is small enough that financing/operational frictions matter. Build
the execution + longer-history validation, deploy small after the August review.
