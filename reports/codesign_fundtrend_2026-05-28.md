# Strategy Debate — 2026-05-28

- **Opus model:** `claude-opus-4-7`
- **Gemini model:** `gemini-3.1-pro-preview`
- **Rounds:** 8 · **Opener:** Gemini
- **Format:** collaborative co-design of a new strategy
- **Seed:** `scripts/debate_seed_fundtrend.md`

---

### Gemini
Opus, let’s crack this. The mandate is clear: we need a price-orthogonal strategy that generates >+3% CAPM-$\alpha$ across regimes without mechanically loading market beta. Momentum failed the ungated CAPM-$\alpha$ test because it buys high-beta winners. 

To solve this, we will build **"Fundamental Catalyst Drift"**—a two-leg composite combining slow-moving structural profitability improvements (Theme C) with a PEAD catalyst. 

### The Core Inefficiency
Markets are "frogs in the pan" regarding structural business changes. Analysts anchor to historical operating profiles. When a company quietly improves its cash-generation efficiency over several quarters, the market underreacts until a catalyst (an earnings surprise) forces a repricing. Because we are buying fundamental trajectory rather than price trajectory, the portfolio avoids the high-beta/high-volatility trap of price momentum.

### Signal Specification (v0)
To avoid the known EDGAR `compute_eps_ttm` duration bug, we will bypass EPS entirely and use raw fundamental line items (Revenue, Operating Income, Net Income, CFO, Total Assets) to build two trailing-twelve-month (TTM) fundamental trend metrics, plus a PEAD anchor.

**Leg 1: Fundamental Acceleration (Price-Orthogonal)**
We combine two slow-moving trends, comparing the current TTM period ($t$) to the TTM period four quarters ago ($t-4$) to eliminate seasonality.
1.  **$\Delta$ Operating Margin:** The dossier noted this showed promise (4/8 S&P significance). 
    *   *Formula:* $OpMargin_{TTM} = \frac{OpInc_{TTM}}{Rev_{TTM}}$
    *   *Signal:* $OpMargin_{TTM, t} - OpMargin_{TTM, t-4}$
    *   *Sign:* Positive (expanding margins).
2.  **$\Delta$ Cash Conversion (Accruals Trend):** High accruals mean earnings aren't backed by cash. Improving (falling) accruals means cash generation is accelerating faster than accounting earnings—a massive quality signal.
    *   *Formula:* $Accruals = \frac{NI_{TTM} - CFO_{TTM}}{TotalAssets_t}$
    *   *Signal:* $Accruals_t - Accruals_{t-4}$
    *   *Sign:* Negative (shrinking accruals = better cash conversion).

*Leg 1 Construction:* Cross-sectionally rank both signals across the PIT S&P 500, average the ranks, and z-score.

**Leg 2: The Event Anchor (PEAD)**
Fundamental trends can be dead money without a catalyst. We use PEAD to time the entry.
*   *Signal:* Standardized Unexpected Earnings (SUE) via yfinance earnings dates/surprises, OR short-term post-earnings price drift (e.g., 3-day abnormal return post-filing). 

**Composite Construction**
Rank-combine Leg 1 and Leg 2 (50/50 weight). Hold the top 24 names, equal-weighted, rebalanced every 63 days.

### Validation Plan (Falsifiability)
1.  **Phase-Averaged CAPM-$\alpha$:** Run `--rebal-offset` sweep (all 9 phases). The median phase-averaged Jensen's $\alpha$ must be > +3%, with a beta close to 1.0 (or lower). 
2.  **Permutation Null:** Randomize the ticker mappings of our composite z-score 500 times per rebalance to generate a null distribution of returns. Our actual strategy must clear the 95th percentile of the null.

**Over to you, Opus:** 
1. How should we precisely define the PEAD anchor using our available yfinance/Polygon data to avoid lookahead bias? 
2. Equal-weighting the top 24 might still expose us to sector-level beta spikes. How can we implement a covariance/vol-aware sizing mechanism using only our EOD Polygon data to strictly enforce the low-beta mandate?

### Opus 4.7
### Opus — locking down PEAD anchor + beta-aware sizing

Gemini, the dual-trend Leg 1 is solid. Two refinements before answering your questions: (a) the **accruals denominator** should be average total assets `(TA_t + TA_{t-4})/2` to avoid distortion from recent M&A/buybacks, and (b) require **≥6 quarterly filings of history** per name (else drop from Leg 1 ranking) so the YoY-of-TTM is well-defined.

### 1. PEAD anchor — lookahead-safe definition

yfinance `get_earnings_dates()` gives `reportedEPS` and `epsEstimate`. Two problems: estimates are revised post-hoc, and the announcement timestamp is the date row — we don't know pre/post-market reliably. Fix:

**SUE-lite (analyst-free, EDGAR-native):**
- Earnings surprise = `(EPS_actual_q − EPS_q-4) / σ(ΔEPS_q, q-4..q-12)` using EDGAR quarterly EPS *as-filed* (8-quarter rolling stdev of YoY EPS changes).
- This sidesteps the TTM duration bug because we use **single-quarter** EPS facts from EDGAR (which DO have a clean `period` tag — the bug is in the TTM aggregation, not the raw facts).

**Drift confirmation leg (price-based, lookahead-safe):**
- `AR_[+2,+4]` = cumulative abnormal return (vs SPY) on days t+2 through t+4 after the EDGAR filing date (not the yfinance announcement date — filing date is unambiguous and PIT-clean).
- Skip day t+1 to avoid the announcement-day gap (which loads beta).

**PEAD score** = rank-average of (SUE-lite, AR_[+2,+4]), using only the most recent earnings event within the last **45 calendar days** of `as_of`. Names with no event in that window get a neutral rank (0.5) — this preserves Leg 1's full universe rather than collapsing the book to ~30 recent reporters.

### 2. Beta-aware sizing within EOD-only constraint

Equal-weight top-24 will absolutely leak beta. Three-step fix using only Polygon EOD:

**Step A — pre-screen for beta cap:** Compute 252-day rolling β vs SPY for each candidate. **Drop any name with β > 1.3** from the top-24 selection (replace with the next-ranked name). This alone kills the worst beta-loaders.

**Step B — inverse-vol weighting:** Weight `w_i ∝ 1/σ_i` where `σ_i` = 63-day realized vol. Caps single-name risk and tilts toward lower-vol names without optimization machinery.

**Step C — explicit beta-neutralization at portfolio level:** After Step B, compute portfolio β = Σ w_i β_i. If β_p > 0.9, **scale the book down** (hold residual as cash) until β_p ≤ 0.9. This is crude but uses no covariance matrix (which is unstable at N=24 on 252 days). We're trading some gross exposure for a hard beta cap — exactly the trade the mandate requires.

No Ledoit-Wolf, no risk model. Just: cap β, weight by 1/σ, gross-scale to enforce β_p ≤ 0.9.

### 3. Validation gap to repair

Your permutation null randomizes ticker→z-score mappings. **Stronger null:** randomize the **filing-date timing** of each fundamental signal (shift each company's filing history by a random ±N quarters). This preserves the cross-sectional distribution and tests whether the *temporal alignment* of fundamental trends to forward returns is real — the exact thing we're claiming.

**Pre-registered decision rule:** ship to paper iff (i) phase-median CAPM-α ≥ +3%, (ii) ≥6/9 phases positive α, (iii) phase-median β_p ≤ 0.9, (iv) actual α clears 95th pct of filing-shift null. Else: kill.

Your move: weights between Leg 1 and PEAD given PEAD's sparse coverage, and whether we sector-neutralize Leg 1 before combining.

### Gemini
Opus, the filing-shift null is a massive upgrade. It directly tests the temporal causality of our thesis rather than just the cross-sectional distribution. Your lookahead-safe SUE-lite and the EOD-only beta-scaling are exactly the kind of constraint-aware engineering this system needs. 

Here is the final resolution on weights, sector neutralization, and the complete implementable specification.

### 1. Sector Neutralization (Leg 1)
We **must** sector-neutralize Leg 1. Operating margins and accrual baselines are structurally dictated by industry (e.g., Software vs. Utilities). If we don't neutralize, the cross-sectional rank will just structurally long high-margin sectors, turning into a disguised sector-beta bet. 
*   **Fix:** Rank $\Delta$ OpMargin and $\Delta$ Cash Conversion *within* each GICS sector first. Convert these intra-sector ranks to uniform percentiles (0 to 1), average them, and then compute the global Leg 1 z-score. 

### 2. Composite Weighting & Sparsity
Because PEAD is restricted to a 45-day event window, roughly 50% of the universe will default to a 0.5 rank at any given 63-day rebalance. 
*   **Fix:** We weight the composite **70% Leg 1 / 30% PEAD**. 
*   *Why:* A 50/50 split would excessively dilute strong fundamental trends in off-cycle stocks. At 70/30, the structural fundamental trend drives the core portfolio, while the PEAD score acts as an asymmetric "catalyst kicker," dynamically bumping up names that just confirmed their fundamental trajectory with an earnings beat.

### 3. Turnover Management
Fundamental trends unfold over quarters, not weeks. To prevent the 63-day rebalance from churning names whose trends are intact but just drifted slightly in rank, we will retain the live system's **0.75 turnover hysteresis bonus**. If a stock is currently in the top 24, its combined z-score gets a 0.75 standard deviation artificial bump during the next ranking.

### THE FINAL SPECIFICATION (Ready for `src/factors/`)

**Universe:** PIT S&P 500, $\ge 6$ quarters of EDGAR filing history.
**Rebalance:** 63 trading days.
**Regime Gate:** Existing 75/200-SMA + VIX gate remains active (protects against slow bears).

**Step 1: Fundamental Drift (70% Weight)**
*   Compute TTM OpMargin and TTM Accruals (using average total assets). 
*   Calculate YoY change: $\Delta_{t} - \Delta_{t-4}$.
*   Rank within GICS sectors, average the two percentiles, and z-score ($Z_{fund}$).

**Step 2: Event Anchor (30% Weight)**
*   Identify latest EDGAR filing $\le 45$ days from `as_of`. (If none, score = 0.5).
*   Compute SUE-lite: `(EPS_q - EPS_q-4) / max(σ(ΔEPS_8q), 0.01)`.
*   Compute Drift: Cumulative abnormal return vs SPY from $t+2$ to $t+4$ post-filing.
*   Rank-average SUE-lite and Drift, and z-score ($Z_{pead}$).

**Step 3: Composite & Selection**
*   $Z_{total} = (0.7 \times Z_{fund}) + (0.3 \times Z_{pead}) + (\text{Hysteresis Bump})$.
*   Sort descending. Drop any name with 252-day SPY $\beta > 1.3$.
*   Select the top 24 remaining names.

**Step 4: Beta-Aware Sizing**
*   Assign initial weights: $w_i \propto 1 / \sigma_{i, \text{63d}}$.
*   Compute Portfolio Beta ($\beta_p = \sum w_i \beta_i$).
*   If $\beta_p > 0.9$, scale all weights by $0.9 / \beta_p$, holding the residual in cash.

**Validation Lock:** We run the `--rebal-offset` sweep. If phase-median CAPM-$\alpha \ge +3\%$, $\beta_p \le 0.9$, and actual $\alpha$ clears the 95th percentile of your filing-shift null, we ship to paper. Otherwise, the thesis is falsified. 

We have a complete, constraint-compliant, low-beta fundamental model.

### Opus 4.7
### Opus — final implementation gaps to close

Gemini, spec is 90% there. Three remaining holes will bite us during implementation. Closing them now.

### 1. Data-layer violation in the SUE-lite definition (must fix)

I wrote SUE-lite using "EDGAR quarterly EPS as-filed." Re-reading the dossier: **the EPS duration bug is exactly that quarterly vs YTD periods aren't disambiguated in the current loader.** Using raw EPS facts means we inherit the bug we were trying to bypass.

**Fix — bypass EPS entirely in SUE-lite:**
- Use **quarterly Net Income** from EDGAR (cleaner `period` tags than EPS; loader already handles for accruals) divided by **shares outstanding at filing date** (Polygon `weighted_shares_outstanding` or EDGAR `CommonStockSharesOutstanding`).
- `NI_per_share_q = NI_q / shares_q`
- SUE-lite = `(NI_per_share_q − NI_per_share_q-4) / σ(ΔNI_per_share, 8q rolling)`
- Require **single-quarter** period tag (≤95 days) — drop any fact with period >95d. This is the durable fix; we should land it in the loader as `compute_ni_quarterly()` and reuse for the YoY-of-TTM in Leg 1 too.

### 2. Beta-cap creates a selection bias we need to bound

Pre-screening β>1.3 names before top-24 selection means in a high-vol regime (post-shock), most candidates fail the cap and we select deep into the ranking tail. **Guardrail:** if >40% of the top-50 ranked names get β-rejected, **widen the candidate pool to top-75** before selecting 24. If still <24 names pass, **hold cash for the shortfall** rather than reaching further down the rank. This makes the beta cap a binding constraint, not a silent quality compromise.

### 3. Validation plan is missing a regime decomposition

Phase-median CAPM-α ≥+3% across 9 phases is necessary but conflates regimes. The brief shows the existing system is +8.8% bull / +6.1% slow-bear / **−7.9% COVID**. We need to know if Fundamental Catalyst Drift fixes the crash hole or just shifts where it fails.

**Add to pre-registered decision rule:**
- (v) Compute phase-median α **per cross-window regime** (bull / slow-bear / COVID-shock) using the existing 5-year backtest split.
- Ship requires: **no single regime worse than −2% phase-median α.** A strategy that's +6% bull / +5% bear / −10% crash still loses the mandate (we already have that profile).
- If COVID-window fails but bull+bear pass: ship **only with regime gate active** and document the crash hole explicitly. Don't pretend it's solved.

### 4. One entry/exit detail still ambiguous

What happens when a held name's β drifts above 1.3 mid-quarter (between rebalances)? Options:
- **(a)** Ignore until next rebalance — preserves low turnover, accepts intra-quarter β leak.
- **(b)** Daily β check, force-exit if β>1.5 (hard cap, wider than entry to avoid churn).

**Pick (b).** Mandate is hard-low-beta; a single mega-cap re-rating shouldn't blow the portfolio β cap for 60 days. Exit triggers liquidation to cash (no replacement until rebalance).

### Final shippable acceptance gate
(i) phase-median CAPM-α ≥+3%, (ii) ≥6/9 phases positive, (iii) phase-median β_p ≤0.9, (iv) clears 95th pct of filing-shift null, (v) no regime worse than −2% phase-median α, (vi) turnover ≤40%/quarter (sanity check the hysteresis is working).

I think we converge here. Build it.

### Gemini
Opus, we are perfectly aligned. The `NI_per_share_q` pivot elegantly sidesteps the EDGAR duration bug, and the strict regime-decomposition validation ensures we aren't just trading one flavor of beta for another. 

To make this 100% ready for the engineer to drop into `src/factors/` and `scripts/run_daily_pipeline.py`, I will lock down the final data-layer execution mechanics. We must resolve how the two cash-generating rules interact, how daily exits function in the current architecture, and how we handle filing timestamps.

### 1. Hardening the Data Layer: TTM & Timestamps
*   **TTM Construction (Leg 1):** Because we are strictly filtering EDGAR facts for `period <= 95d` to enforce quarterly data, $TTM$ values for Revenue, Net Income, and CFO must be constructed by summing the last 4 valid quarterly filings prior to `as_of`. This permanently bypasses the buggy `compute_eps_ttm` aggregation.
*   **Drift Timing ($t+2$ to $t+4$):** EDGAR filing timestamps vary (pre-market vs. post-market). We define $t=0$ as the *first trading day* where the filing is public before the open (e.g., filed 6:00 PM Tuesday $\rightarrow t=0$ is Wednesday). The abnormal return window $AR_{[+2,+4]}$ strictly uses Polygon trading days. If the filing occurred within 4 trading days of our `as_of` rebalance, it is excluded from Leg 2 (reverts to 0.5 rank) to prevent lookahead bias.

### 2. Resolving the Cash & Sizing Mechanics
We have two rules that create cash: the beta-cap shortfall and the portfolio beta scaling. They must be applied sequentially to avoid double-penalizing:
1.  **Selection:** Filter universe for $\beta_{252d} \le 1.3$. Take the top 24. If we exhaust the top 75 and only find $N < 24$ names, we only select $N$. 
2.  **Initial Weighting:** Apply inverse-volatility weights to the $N$ selected names such that $\sum_{i=1}^{N} w_i = 1.0$. 
3.  **Beta Scaling:** Compute portfolio beta $\beta_p = \sum w_i \beta_i$. If $\beta_p > 0.9$, multiply all weights by the scalar $(0.9 / \beta_p)$. 
4.  **Cash Allocation:** The unallocated weight $(1.0 - \sum w_{\text{final}})$ is held as cash. This cleanly handles both a lack of qualifying names and excessive portfolio beta.

### 3. Executing the Mid-Quarter Beta Exit
The existing `scripts/run_daily_pipeline.py` already includes a daily exit/monitor phase. We will implement the mid-quarter $\beta > 1.5$ hard cap there. 
*   **Logic:** Every evening, compute the 252-day SPY beta for current holdings using Polygon EOD data. 
*   **Action:** If a holding breaches 1.5, the script generates a Market-On-Close (MOC) sell order for the next trading day via Alpaca. The proceeds are swept into the cash balance and **not reallocated** until the next 63-day cycle. This strictly enforces the low-beta mandate without requiring complex intra-quarter re-weighting.

### Final Sign-Off
We have a unified, constraint-compliant strategy: **Fundamental Catalyst Drift**. It extracts orthogonal alpha from slow-moving cash conversion and margin trends, timed by an analyst-free PEAD anchor, and strictly bounded by EOD beta caps. 

The validation rule is locked: Phase-median CAPM-$\alpha \ge +3\%$, $\ge 6/9$ phases positive, $\beta_p \le 0.9$, beats the 95th percentile of the filing-shift null, and NO cross-window regime worse than $-2\%$ median $\alpha$. 

This spec is complete and ready for backtest serialization.

### Opus 4.7
### Opus — final sign-off + two implementation traps to defuse before backtest

Gemini, agreed on the spec. Before we hand to the engineer, two things will silently corrupt the backtest if we don't nail them now, plus a tightening of the validation arithmetic.

### 1. Filing-date timestamping has a known EDGAR gotcha

We defined t=0 as "first trading day where filing is public before the open." Two failure modes the loader must handle:

- **EDGAR `acceptedDate` vs `filedDate` divergence:** `filedDate` is the SEC's date-of-record; `acceptedDate` is the actual submission timestamp (often 5:30pm same day or after-hours). Use **`acceptedDate`** for t=0 determination. Rule: if `acceptedDate` time ≥ 16:00 ET, t=0 is next trading day; else same day if it's a trading day, else next.
- **10-K/10-Q vs 8-K race:** Earnings are typically pre-announced in 8-K (with financial exhibits) days before the 10-Q filing. For SUE-lite + AR window, we want the **8-K with Item 2.02 (Results of Operations)** as the anchor, not the 10-Q. If the loader only indexes 10-Q/10-K, we're systematically 5-15 days late and our AR_[+2,+4] window misses the actual drift. **Action:** confirm the EDGAR loader pulls 8-K Item 2.02 dates; if not, this is a blocking prerequisite.

For Leg 1 (TTM fundamental trends), keep using 10-Q/10-K `acceptedDate` — those are the official numbers.

### 2. Sector neutralization needs a minimum-bucket guard

GICS Level-1 has 11 sectors; S&P 500 distribution is uneven (Real Estate ~30 names, Tech ~75). Within-sector percentile ranking on a 30-name bucket is noisy and on a <15-name bucket (some sub-industries if we go finer) is meaningless.

**Fix:** Neutralize at **GICS sector (Level-1) only**, and require **≥15 names per sector** post-eligibility-filter. If a sector has <15 qualifying names, those names get **global** (un-neutralized) percentile rank for that rebalance. Document this as a known minor leak into sector beta for thin sectors — acceptable, and the portfolio β cap catches it downstream.

### 3. Validation arithmetic — fix the multiple-comparisons exposure

The 5-criterion acceptance gate (α, %-positive, β, null, regime-floor) is a conjunction of independent-ish tests. With 9 phases × 3 regimes × null test, we're doing ~30 implicit comparisons. The brief is explicit that this system has burned itself on phase-luck before.

**Tighten:**
- **Pre-register the snapshot IDs and offset grid BEFORE running.** Write them into a `validation_plan.yaml` committed to git. No post-hoc snapshot selection.
- **Bootstrap CI on phase-median α, not point estimate.** Phase-median CAPM-α ≥+3% becomes: lower bound of 80% bootstrap CI across 9 phases ≥ +1%. This converts "is the median above 3" into "is the *distribution* meaningfully above zero" — the right question given our ±20-30pp envelope.
- **Filing-shift null: 500 permutations minimum**, each shift drawn uniformly from {±1, ±2, ±3, ±4} quarters per company independently. Report the actual α's percentile, not just pass/fail at 95.

### 4. One sizing edge case

When β-scaling pushes us to, say, 60% gross with 40% cash, our **realized CAPM-α denominator** (portfolio return) shrinks proportionally. A +5% α on 60% gross looks like +3% on the book. Report α two ways: **on deployed capital** (true signal quality) and **on total book** (what we actually earn). Ship decision uses *total book*; diagnostic uses *deployed*.

### Locked spec — ready to build

`src/factors/fundamental_catalyst_drift.py`: Leg 1 (Δ-OpMargin + Δ-Accruals, sector-neutralized with min-bucket guard, 70%) + Leg 2 (SUE-lite via NI/share + AR_[+2,+4] off 8-K Item 2.02, 30%) + hysteresis 0.75. Selection: β≤1.3 filter, expand to top-75 candidate pool, top-24 or fewer. Sizing: 1/σ → β-scale to β_p≤0.9 → cash residual. Mid-quarter: daily β>1.5 force-exit to cash. Regime gate: existing 75/200-SMA + VIX. Validation: phase grid + bootstrap CI + filing-shift null + per-regime floor, all pre-registered.

Ship to paper iff all five criteria pass on the locked validation_plan.yaml. Build it.

### Gemini
Here is the final, implementable specification for **Fundamental Catalyst Drift**. This consolidates our constraints, fixes, and validation logic into a single blueprint ready for `src/factors/`.

### 1. Thesis & The Inefficiency
Markets are "frogs in the pan" regarding structural business changes, anchoring to historical operating profiles. When a company quietly improves its cash-generation efficiency and operating margins over several quarters, the market underreacts. We exploit this by buying the **Price-Orthogonal Fundamental Drift** (structural improvement) timed by an **Event Anchor** (an earnings surprise that forces a repricing). By explicitly constraining beta and sizing via inverse volatility, we extract the fundamental premium without mechanically loading the high-beta/high-volatility risk that plagues standard momentum.

### 2. Precise Signal Definitions
**Data Layer:** EDGAR PIT (fundamentals/dates), Polygon EOD (prices/shares). 
*Note: Bypass the `compute_eps_ttm` bug by strictly summing single-quarter EDGAR facts (`period <= 95d`).*

**Leg 1: Fundamental Drift (70% Weight)**
*   **Metrics:** 
    *   $OpMargin_{TTM} = OpInc_{TTM} / Rev_{TTM}$
    *   $Accruals = (NI_{TTM} - CFO_{TTM}) / \text{AvgTotalAssets}_{t, t-4}$
*   **Signal:** YoY change in TTM metrics: $\Delta OpMargin$ (higher is better) and $\Delta Accruals$ (lower is better).
*   **Ranking:** Rank within GICS Level-1 sectors. *(Guard: If a sector has <15 eligible names, those names use a global rank).* Average the two percentiles, then z-score $\rightarrow Z_{fund}$.

**Leg 2: Event Anchor / PEAD (30% Weight)**
*   **Timing:** Anchor to the EDGAR 8-K Item 2.02 (Results of Operations) `acceptedDate`. If time $\ge$ 16:00 ET, $t=0$ is the next trading day. Only apply to filings $\le 45$ days from `as_of`. If older, score defaults to 0.5. If within 4 days of `as_of`, exclude (lookahead safety).
*   **SUE-lite:** $(NI\_per\_share_q - NI\_per\_share_{q-4}) / \max(\sigma(\Delta NI\_per\_share, 8q), 0.01)$. Uses EDGAR Net Income / Polygon shares at filing.
*   **Drift:** Cumulative abnormal return vs SPY from $t+2$ to $t+4$ post-filing.
*   **Ranking:** Rank-average SUE-lite and Drift, then z-score $\rightarrow Z_{pead}$.

**Composite:** $Z_{total} = (0.7 \times Z_{fund}) + (0.3 \times Z_{pead}) + \text{Hysteresis Bump (0.75 for incumbents)}$.

### 3. Universe, Entry/Exit, Sizing & Rebalance
*   **Universe:** PIT S&P 500, $\ge 6$ quarters of EDGAR filing history.
*   **Rebalance:** 63 trading days, gated by the existing 75/200-SMA + VIX regime filter.
*   **Selection & Beta Cap:** Sort $Z_{total}$ descending. Drop any name with 252-day SPY $\beta > 1.3$. Select the top 24. *(Guard: If we exhaust the top 75 and find $N < 24$ names, select $N$ and hold the shortfall weight in cash).*
*   **Sizing:** 
    1. Initial weights: $w_i \propto 1 / \sigma_{i, 63d}$.
    2. Compute Portfolio Beta: $\beta_p = \sum w_i \beta_i$.
    3. If $\beta_p > 0.9$, scale all weights by $(0.9 / \beta_p)$. Unallocated weight is held as cash.
*   **Mid-Quarter Exit:** Daily monitor. If a holding's 252-day $\beta$ breaches 1.5, trigger a Market-On-Close (MOC) sell for the next day. Proceeds go to cash; no intra-quarter reallocation.

### 4. Pre-Registered Validation Plan
Before running, commit `validation_plan.yaml` with locked snapshot IDs and offset grid. The strategy is falsified and killed unless it meets ALL criteria:
1.  **Phase-Averaged Edge:** Lower bound of the 80% bootstrap CI for phase-median CAPM-$\alpha$ (measured on *total book*) $\ge +1\%$, with the absolute phase-median $\ge +3\%$.
2.  **Consistency:** $\ge 6/9$ phases positive.
3.  **Risk Mandate:** Phase-median $\beta_p \le 0.9$. Turnover $\le 40\%$ per quarter.
4.  **Causality (Filing-Shift Null):** Randomize filing histories independently by $\pm 1$ to $4$ quarters (500 permutations). The actual $\alpha$ must clear the 95th percentile of this null distribution.
5.  **Regime Floor:** Compute phase-median $\alpha$ per cross-window regime (bull, slow-bear, COVID-shock). NO single regime can be worse than $-2\%$ median $\alpha$.

### 5. Honest Verdict
**Is there a realistic edge?** Yes. By isolating fundamental trajectory from price trajectory, we strip out the mechanical beta-loading that doomed standard momentum. The `NI_per_share` and strict 8-K timestamping completely bypass the known EDGAR duration bug and lookahead traps.

**Failure Modes:** The primary risk is cash drag. In a raging, low-breadth bull market (like 2023-2024), the strict $\beta \le 0.9$ scaling and $\beta > 1.3$ exclusion will force the book into cash and low-beta laggards, causing it to underperform SPY on a raw return basis. The 8-K Item 2.02 parsing also requires strict data-layer hygiene.

**Action Plan:** Code and run the backtest validation *now* to see if the alpha survives the null tests. However, **do not deploy to the live paper account yet.** The live system is mid-validation (until 2026-08-27). Swapping the engine mid-run destroys the integrity of the out-of-sample forward test. Validate offline, queue it up, and if it passes, it becomes the v2 candidate for Q3.

### Opus 4.7
### Opus — FINAL SPEC: Fundamental Catalyst Drift (FCD)

Gemini's consolidation is clean. Locking it down with one structural addition (a coverage sanity check) and the final go/no-go framing.

---

### 1. Thesis & Inefficiency

Markets anchor to historical operating profiles and underreact to **slow-moving structural improvements in cash-conversion efficiency and operating margins.** Standard momentum captures the price re-rating but mechanically loads beta. FCD buys the **fundamental trajectory** itself (price-orthogonal), times the entry with a **PEAD event anchor** (the catalyst that forces repricing), and enforces a **hard portfolio β cap** so the alpha can't be a disguised market bet. The edge is *temporal alignment*: we own names where fundamentals are accelerating *before* the market fully prices it, and we exit before the trade becomes a momentum trade.

### 2. Signal Definitions

**Data:** EDGAR PIT (10-Q/10-K acceptedDate, 8-K Item 2.02 acceptedDate, NI/Rev/OpInc/CFO/TotalAssets quarterly with `period ≤ 95d`), Polygon EOD (prices, shares outstanding), existing regime/VIX gates.

**Leg 1 — Fundamental Drift (70%)**
- TTM constructed as sum of last 4 single-quarter EDGAR facts (bypasses the EPS TTM bug entirely).
- ΔOpMargin = OpMargin_TTM(t) − OpMargin_TTM(t−4) [higher better]
- ΔAccruals = [(NI−CFO)/AvgTA]_t − [(NI−CFO)/AvgTA]_{t−4} [lower better]
- Rank within GICS L1 sector (min 15 names/bucket, else global rank); average percentiles; z-score → **Z_fund**.

**Leg 2 — Event Anchor (30%)**
- Anchor: 8-K Item 2.02 acceptedDate (t=0 = next trading day if ≥16:00 ET).
- SUE-lite = (NI/sh_q − NI/sh_{q−4}) / max(σ(ΔNI/sh, 8q), 0.01)
- Drift = cumulative AR vs SPY over [t+2, t+4].
- Apply only if filing within 45d of as_of AND ≥4 trading days before as_of; else neutral 0.5.
- Rank-average, z-score → **Z_pead**.

**Composite:** Z_total = 0.7·Z_fund + 0.3·Z_pead + 0.75 incumbent hysteresis bump.

### 3. Universe, Selection, Sizing, Rebalance

- **Universe:** PIT S&P 500, ≥6 quarters of clean filings, re-resolved per rebalance (fixes the universe-freeze bias noted in the dossier).
- **Rebalance:** 63 trading days, regime-gated (existing 75/200-SMA + VIX).
- **Selection:** Drop names with 252d β > 1.3; take top 24 from Z_total. If fewer than 24 qualify within top-75 candidates, hold N<24 and let cash absorb shortfall.
- **Sizing:** w_i ∝ 1/σ_{63d} → if β_p > 0.9, scale all weights by 0.9/β_p → residual to cash.
- **Mid-quarter exit:** Daily β check; force-exit MOC if any holding's β > 1.5; proceeds to cash, no replacement until rebalance.

### 4. Pre-Registered Validation (committed to `validation_plan.yaml` before any run)

Locked snapshot IDs + offset grid {0..8} + filing-shift null seed. Ship iff **all** pass:

1. **Edge:** 80% bootstrap CI lower bound of phase-median CAPM-α (on total book) ≥ +1%, point estimate ≥ +3%.
2. **Consistency:** ≥6/9 phases positive α.
3. **Risk:** Phase-median β_p ≤ 0.9; quarterly turnover ≤ 40%.
4. **Causality:** Actual α ≥ 95th pct of 500-perm filing-shift null (independent ±1..4 quarter shifts per company).
5. **Regime floor:** No cross-window regime (bull / slow-bear / COVID) with phase-median α worse than −2%.
6. **NEW — Coverage sanity:** Median monthly deployed gross ≥ 50%. If the β-cap + scaling routinely parks >50% in cash, the strategy isn't trading the thesis — it's a cash fund with a tilt. Kill and redesign.

Report α both **on deployed capital** (signal quality) and **on total book** (what we earn). Decision uses total book.

### 5. Honest Verdict

**Is there a realistic edge?** Plausibly yes, ~+2-4% CAPM-α on total book in a fair regime. The two legs are genuinely price-orthogonal, the EPS bug is bypassed, the temporal causality null is the strongest validation we've designed, and the β architecture mechanically prevents the failure mode that killed PEAD+RM-MOM in iter 1.

**Failure modes, ranked:**
1. **Cash drag in narrow bull markets** (2023-style mega-cap melt-up): β cap forces cash, raw return lags SPY even if α is positive. Acceptable — mandate is α, not return.
2. **8-K Item 2.02 parsing is a hard data-layer prerequisite.** If the EDGAR loader doesn't index 8-K Item 2.02, Leg 2 collapses to using 10-Q dates and we're systematically 5-15 days late — drift window misses the event. **Blocking task: confirm or build 8-K indexing before backtest.**
3. **Sector-neutralization on thin buckets** (Real Estate, Materials) leaks residual sector beta — β cap catches it, but expect noisier per-rebalance composition.
4. **Filing-shift null may be too easy a bar** — if the strategy clears 95th pct only by 1-2pp, treat as marginal, not confirmed.

**Worth building before 2026-08-27 paper review?**

**Yes — build and validate offline. Do NOT deploy.** Gemini is right: swapping engines mid-OOS-run destroys the integrity of the forward test that is the system's only un-overfittable signal. Path: (a) implement 8-K indexing if missing, (b) ship `src/factors/fundamental_catalyst_drift.py`, (c) commit `validation_plan.yaml`, (d) run the full pre-registered gate, (e) if it passes, queue as v2 candidate for post-2026-08-27 review. If the current paper run shows the live composite has real forward α, FCD becomes an additive sleeve, not a replacement. If the live run fails, FCD is the queued successor with validation already done.

**Ship the spec to engineering. Hands off the live book until August.**
