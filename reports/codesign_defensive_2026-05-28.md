# Strategy Debate — 2026-05-28

- **Opus model:** `claude-opus-4-7`
- **Gemini model:** `gemini-3.1-pro-preview`
- **Rounds:** 8 · **Opener:** Gemini
- **Format:** collaborative co-design of a new strategy
- **Seed:** `scripts/debate_seed_defensive.md`

---

### Gemini
This is a strong pivot. The previous iteration’s failure—high IC but negative CAPM-α—proves that simply picking "good" companies often just selects for high-beta growth during bull runs, which gets crushed in down regimes. To generate positive Jensen’s α, we need to exploit the **"Boring Quality" anomaly**: investors systematically overpay for lottery-like, high-volatility characteristics and underprice stable, cash-generating businesses with conservative financing. These boring stocks act as a beta-dampening anchor during market stress.

To bypass the known EDGAR EPS duration bug, we must avoid per-share metrics entirely and rely on raw, standardized accounting items (CFO, Net Income, Total Assets, Debt). 

Here is v0 of the **Defensive Cash-Flow Composite**. It consists of three PIT-observable fundamental signals, evaluated strictly cross-sectionally.

### 1. Accruals / Earnings Quality (The Anchor)
*   **Thesis**: High accruals (earnings driven by accounting rather than cash) predict lower future returns and signal fragility. Cash is real; earnings are an opinion.
*   **Formula**: `(CFO_ttm - NI_ttm) / Total_Assets_latest`. 
*   **Sign**: Positive (higher cash flow relative to net income = better rank).
*   **Data**: EDGAR PIT. `CFO` and `NI` aggregated over trailing 4 quarters; `Total_Assets` from the latest balance sheet.

### 2. Margin Durability (The Moat)
*   **Thesis**: Companies with low variance in operating margins have pricing power and predictable costs, making their equity less sensitive to macro shocks (lower beta).
*   **Formula**: Standard deviation of `Operating_Margin` over the last 8 available quarters.
*   **Sign**: Negative (lower variance = higher rank).
*   **Data**: EDGAR PIT filing history.

### 3. De-leveraging Trend (The Balance Sheet Buffer)
*   **Thesis**: In high-VIX or bear regimes, the market punishes debt. Companies actively paying down debt out-survive their peers. 
*   **Formula**: `Debt_to_Equity_latest - Debt_to_Equity_4_quarters_ago`.
*   **Sign**: Negative (decreasing debt ratio = higher rank).
*   **Data**: EDGAR PIT filing history.

### Execution & The Phase-Luck Reality
We combine these three signals into a rank-based composite. We hold the top 24 names, equal-weighted, with a 63-day rebalance. 

However, because these factors (especially debt and margins) are highly sector-dependent, a raw universe-wide rank might inadvertently turn this into a massive sector bet (e.g., long Utilities/Staples, short Tech), which just trades sector beta for market beta. 

**Opus**, I’ll hand this over to you for two critical additions:
1.  **Sector Neutralization**: How should we mathematically handle the z-scoring for these signals to prevent this from becoming a static sector tilt, given the `sector_neutralize.py` capability?
2.  **Validation Plan**: Define the precise permutation/null baseline and the phase-averaged hurdle we will use to prove this actually generates CAPM-α in the COVID/2022 cells, rather than just getting lucky in one 63-day offset.

### Opus 4.7
### Opus — locking down sector-neutralization, signal hygiene, and the falsification gate

Gemini's three signals are well-chosen and bug-routed around EPS. Let me close the loop on the two asks and patch three issues I see before this can ship.

### Patch 1 — Signal hygiene (must fix before sector-neutralizing)

- **Accruals denominator drift**: use *average* total assets `(TA_t + TA_{t-4Q})/2`, standard Sloan convention. Single-snapshot TA inflates the ratio for fast-growing balance sheets (the very growth/beta names we want to deprioritize). Sign confirmed: high CFO−NI = good.
- **Margin durability sample size**: require ≥6 of 8 quarters present; if fewer, signal is `NaN` (drop from rank, don't impute median — imputation = silent beta tilt). Also use **coefficient of variation** `stdev(op_margin)/|mean(op_margin)|` rather than raw stdev, so a 2%-margin grocer and a 30%-margin software co. are compared on stability, not scale.
- **De-leveraging needs a level gate**: a firm going from D/E 0.1→0.05 isn't meaningfully "de-levering." Use `ΔD/E` *only among firms with starting D/E > universe median*. For low-leverage firms, score = 0 (neutral). This prevents the signal from rewarding cash-rich megacaps for noise.

### Patch 2 — Sector neutralization (Gemini's Q1)

Two-stage z-score, implemented via existing `sector_neutralize.py`:

1. For each signal `s ∈ {accruals, margin_cv, deleverage}`, compute **within-GICS-sector z-score** at each rebalance: `z_s,i = (s_i − μ_sector) / σ_sector`. Sectors with <8 names fall back to universe z (avoid 1-stock sectors blowing up).
2. Rank-combine the three sector-z signals with **equal weights** (no optimization — we have ~8 rebalances of OOS, optimizing weights is overfitting theatre).
3. Apply existing **sector cap** (max 25% book per GICS sector) on top, so even after neutralization a residual tilt can't dominate.

This makes the signal a **within-sector "boring quality" tilt**, not a Staples-vs-Tech bet. Critical for CAPM-α: we want the *long leg's residual return after both market AND sector betas* to be positive.

### Patch 3 — Validation plan (Gemini's Q2): pre-registered, falsifiable

**Hurdle (pre-registered, written down before running):**
- Phase-averaged **Jensen's α ≥ +3%/yr** across all 9 rebalance offsets on the 2022-2024-26 snapshot (covers bull, slow-bear, COVID-echo).
- **%-positive-α phases ≥ 6/9** (binomial p≈0.09 under null of 50%).
- **COVID + 2022 sub-cells**: median α ≥ 0% (defensive thesis must not lose money in the regime it's designed for — relaxed bar because n is small).
- **Realized portfolio beta < 0.85** (proves it's actually defensive, not closet-momentum).

**Null baseline (the part that's usually skipped):**
- **Permutation null**: shuffle the composite-z across tickers within each sector, 200 draws, rebuild the top-24 portfolio per draw, compute phase-averaged α. Our real α must exceed the **95th percentile** of the null distribution. This controls for "any 24-name sector-neutral S&P basket has α in this window."
- **Factor-isolation check**: long-short decile (top 24 − bottom 24, dollar-neutral) over the same phases. If L/S Sharpe < 0.5 but long-only α > 3%, the "alpha" is just long-bias — kill it.

**Decision rule**: ship only if all four hurdles + permutation 95th-pct + L/S Sharpe ≥ 0.5 are met. Otherwise the composite is filed as falsified and we move to Theme B.

Gemini — agree on hurdles? One open call: do we run this **standalone** for the test, or **blended 50/50 with the live m/q/v composite** so the validation measures *incremental* α? I lean standalone first (cleaner falsification), blend second if it passes.

### Gemini
Opus, your patches are spot on. The denominator drift fix for accruals and the CV adjustment for margins are exactly the kind of signal hygiene that prevents silent beta tilts. 

I strongly agree with your open call: **Test standalone first.** If we blend it immediately, the existing momentum/PEAD engine will mask the defensive factor’s true CAPM-α. We must prove this factor generates alpha in isolation before allowing it near the live composite.

To finalize this specification for the data layer and execution engine, I am locking down the exact field mappings, adding a critical sizing enhancement to enforce our low-beta mandate, and defining the turnover logic.

### 1. Exact Data Mapping (EDGAR PIT & Polygon EOD)
To ensure there is zero ambiguity for the pipeline (`src/factors/fundamentals_pit_loader.py`):
*   **Accruals:** `CFO_ttm` = sum of `net_cash_provided_by_operating_activities` over trailing 4 quarters. `NI_ttm` = sum of `net_income`. `TA` = `assets`. Formula: `(CFO_ttm - NI_ttm) / ((assets_t + assets_{t-4Q}) / 2)`.
*   **Margin CV:** Compute quarterly `operating_margin` = `operating_income / revenue` for the last 8 quarters. Require ≥6 non-nulls. Formula: `stdev(margins) / abs(mean(margins))`.
*   **De-leveraging:** `D/E` = `(debt_current + debt_noncurrent) / stockholders_equity`. Gate: If `D/E_t` < cross-sectional median, score = 0. Else, `D/E_t - D/E_{t-4Q}`.

### 2. Sizing Enhancement: Inverse-Volatility (Enforcing Low Beta)
Equal-weighting the top 24 is dangerous here. Even with sector-neutralization, some sectors (like Tech or Consumer Discretionary) inherently contain high-beta names that might screen well on margins and cash flow. 
*   **Fix:** We will size the top 24 positions inversely proportional to their 63-day trailing realized volatility (calculated from Polygon EOD OHLCV). 
*   **Formula:** `Weight_i = (1 / Vol_i) / Sum(1 / Vol_all_24)`.
*   **Why:** This mathematically forces the portfolio to allocate more capital to the truly stable anchors within the top 24, structurally suppressing the portfolio beta to hit your `< 0.85` validation hurdle.

### 3. Execution & Hysteresis
*   **Cadence:** 63 trading days (matches the existing system for apples-to-apples phase offset testing).
*   **Turnover Control:** Apply the existing `0.75` hysteresis bonus to incumbent z-scores. Defensive fundamentals (margins, debt reduction) are slow-moving. Paying Alpaca slippage/spread to swap rank 24 for rank 25 is a deadweight loss. 

### 4. The Final Validation Gate (Phase 2)
If the standalone portfolio passes your strict 4-part hurdle (Jensen's α ≥ +3%, 6/9 phases positive, COVID/2022 median α ≥ 0%, L/S Sharpe > 0.5, and >95th percentile of the permutation null), there is one final test before we ship:
*   **Correlation Hurdle:** Compute the daily return correlation between this standalone Defensive composite and the *live* m/q/v composite over the 2022-2026 snapshot. 
*   **Rule:** If `Pearson r > 0.7`, kill it—it’s just a redundant quality factor. If `r < 0.5`, it is a true uncorrelated diversifier, and we proceed to test a 50/50 blended book.

The spec is complete, data-compliant, and the falsification gates are locked. We are ready to run `scripts/factor_lab.py` and `scripts/phase_envelope.py` against the null.

### Opus 4.7
### Opus — final spec lock + two non-negotiable fixes before we run

Gemini, the inverse-vol sizing and the correlation-hurdle are the right closers. I'm signing off on the spec with three patches: one data-layer correctness fix, one sizing safeguard, and one validation tightening. After this, we run.

### Patch A — Inverse-vol sizing needs a beta-aware floor

Inverse-vol is a **proxy** for low beta, not the thing itself. A stock can be low-σ but high-β (utilities in a rate shock) or high-σ but low-β (idiosyncratic biotech). Two refinements:

- **Use 126-day realized vol**, not 63-day. At 63 days we're estimating σ on the same window as the rebalance cadence — noisy, and worse, it back-loads weight to whatever just had a quiet quarter (a momentum-like artifact). 126d is the standard low-vol-anomaly window.
- **Cap weights at 2× equal-weight** (i.e., max 8.3% per name). Without a cap, inverse-vol can dump 25%+ into one anomalously calm name and the "portfolio" becomes a 3-stock bet. Floor at 0.5× equal-weight (2.1%) so the long tail isn't crushed to noise.
- **Then re-normalize.** This is a 4-line addition to the existing sizing layer; no new infra.

### Patch B — Data-layer correctness on the de-leveraging gate

`stockholders_equity` goes negative for buyback-heavy firms (MCD, SBUX, HD, AZO, BA — many of which screen well on margins). A negative-equity D/E is meaningless and will sort to extreme ranks.

- **Filter rule**: if `stockholders_equity ≤ 0` at either `t` or `t−4Q`, set de-leveraging score to `NaN` (drop from that factor's rank, but the firm still ranks on accruals + margin-CV — partial-credit averaging across the 2 remaining z-scores). This is the same NaN-drop convention as the margin-CV insufficient-data rule.
- **Also**: use `(short_term_debt + long_term_debt) / total_assets` as a **secondary tiebreaker**, not equity-denominated. Debt/Assets is well-defined for negative-equity firms. If the primary D/E gate NaN-drops, fall back to ΔDebt/Assets with the same level-gate (only firms above universe median).

### Patch C — Validation plan: add a regime-conditional hurdle and fix the permutation null

Two gaps in what we have:

1. **Permutation null leaks signal if shuffled within sector AND we already sector-neutralize.** The null then tests "are these specific tickers special vs other tickers in their sector" — too tight. Shuffle the composite z **across the full universe** (ignoring sector), then re-apply sector-neutralization + sector cap to the shuffled book. This null tests the *full pipeline*, which is what we actually want to falsify.
2. **Add a regime-conditional pre-registered hurdle**: phase-averaged α in `VIX > 25` sub-periods must be **≥ +5%/yr** (annualized from daily). If the defensive book doesn't pay in high-VIX, the whole thesis is wrong and "+3% blended α" is just bull-market noise we shouldn't trust.
3. **L/S Sharpe ≥ 0.5 stays, but compute it with the same sector-neutralization + inverse-vol sizing on both legs.** A raw-rank L/S would fail for cosmetic reasons.

### Final pre-registered decision tree (write this to `reports/defensive_v1_preregistration.md` before running)

1. Phase-averaged Jensen's α ≥ +3%/yr ✓
2. ≥6/9 phases positive α ✓
3. COVID + 2022 cell median α ≥ 0% ✓
4. High-VIX sub-period α ≥ +5%/yr ✓
5. Realized β < 0.85 ✓
6. L/S Sharpe ≥ 0.5 ✓
7. Real α > 95th pct of 200-draw full-universe permutation null ✓
8. Correlation with live m/q/v ∈ [−1.0, 0.7] ✓ → proceed to 50/50 blend test

**All 8 required.** Any fail → filed as falsified, move to Theme B. No p-hacking the hurdles after seeing results.

Spec locked. Ship it to `factor_lab.py` + `phase_envelope.py`.

### Gemini
Opus, your patches perfectly seal the leaks. The negative-equity catch on buyback-heavy names is a classic quant trap, and the 126-day vol cap/floor ensures we aren't inadvertently making 20% concentrated bets on a single anomalous ticker. The 8-part validation gate is ruthless and exactly what we need.

I am officially signing off on this spec, but to make it 100% implementable for the `src/factors/` pipeline and to prevent a massive logic collision with the existing system, I am adding three final execution-layer directives.

### 1. Unifying the Debt Factor (Vectorization Fix)
Your fallback logic for negative equity (D/E, else D/A) introduces conditional branching that produces two differently-scaled distributions. Z-scoring a mixed distribution of D/E and D/A within a sector will create ranking artifacts, especially for stocks with positive but near-zero equity (which produce massive D/E spikes). 

**The Fix:** We drop `Debt/Equity` entirely and use **`Debt / Total_Assets` for the entire universe**. 
*   **Formula:** `(short_term_debt + long_term_debt) / assets`.
*   **Why:** Total Assets is strictly positive and immune to buyback distortions. It vectorizes cleanly across the entire EDGAR PIT DataFrame without `NaN` fallbacks or split distributions. The gate remains the same: if current `D/A` is below the universe median, score = 0. Else, `D/A_t - D/A_{t-4Q}` (negative is better).

### 2. The Regime Gate Override (Critical Measurement Fix)
The live system employs a 200-SMA exit / 75-SMA re-entry trend filter. If we apply that gate to this Defensive Composite, it will park the book in cash during bear markets. If the book is in cash, the realized alpha in the `VIX > 25` and COVID/2022 cells will be exactly 0%, mechanically failing our pre-registered hurdles #3 and #4.

**The Fix:** This Defensive Composite must be explicitly flagged in `config/settings.yaml` to **bypass the SMA trend gate**. It is an "all-weather" ballast. It stays fully invested in the top 24 boring-quality names during market crashes. This is the only way to mathematically prove its beta-dampening CAPM-α in down regimes. 

### 3. "Lazy Rebalance" Weight Bands (Slippage Control)
We have a 0.75 hysteresis bonus on the *z-score* to keep incumbents in the top 24. However, because we are using 126-day inverse-vol sizing, a stock's target weight will drift every 63 days even if its rank doesn't change. We cannot afford to pay Alpaca spread/slippage to adjust a 4.1% position to a 4.3% position.

**The Fix:** Implement a **±15% relative weight band**. 
*   At the 63-day rebalance, calculate the new inverse-vol target weights.
*   If an incumbent stock's current portfolio weight is within ±15% of its new target weight (e.g., target is 5.0%, current is 4.5%), **do not trade it**. Pass the existing share count forward. 
*   Only execute trades for new entries, exits, or incumbents whose vol profile has radically shifted outside the band.

### Summary to Ship
The "Boring Quality" Defensive Composite is locked. 
*   **Signals:** Accruals (CFO-NI/avg TA), Margin CV (stdev/mean 8Q), De-leveraging (ΔD/A). 
*   **Processing:** Sector-neutral z-score, equal-weighted composite, rank top 24. 
*   **Sizing:** 126d inverse-vol (capped 2.1%-8.3%) with ±15% lazy rebalance bands.
*   **Execution:** 63-day cadence, bypasses SMA regime gate.

The `reports/defensive_v1_preregistration.md` is written. Let's run `scripts/factor_lab.py` and `scripts/phase_envelope.py` against the 2022-2024-26 snapshot. If it clears the 8 hurdles, we test the 50/50 blend.

### Opus 4.7
### Opus — final spec sign-off with one correctness fix and one validation tightening

Gemini, the Debt/Assets unification, regime-gate bypass, and lazy-rebalance bands are correct closers. I'm signing off with two patches: one bug-class fix on the rebalance band that would otherwise leak beta, and one hardening of the pre-registration to prevent a subtle phase-averaging artifact.

### Patch 1 — Lazy rebalance band has a beta-drift trap

Your ±15% relative band is right in spirit but, as written, lets the portfolio's *realized* weights diverge from target arbitrarily far over multiple rebalances. Concretely: if AAPL drifts up 14% relative to target three rebalances in a row (each below the trade threshold), the cumulative position is 1.14³ ≈ 1.48× target — a 12% concentrated bet inside an "8.3%-capped" book. This is exactly how Buffett-style low-vol books quietly turn into momentum books.

**Fix:** band is checked against **target weight at each rebalance**, with a hard absolute ceiling. Two-rule trigger:
- Trade if `|w_current − w_target| / w_target > 0.15` (relative band), **OR**
- Trade if `w_current > 1.25 × initial_target` (absolute drift ceiling), whichever fires first.

This caps cumulative drift at +25% above the cap-respecting target, preserves the slippage savings on small drifts, and prevents silent beta accretion. The 1.25 ceiling is tighter than the 1.15 band specifically because we want band-savings on noise but hard-stop on trending drift.

### Patch 2 — Regime-gate bypass needs an explicit cash-floor exception

Bypassing the SMA gate is correct for the alpha measurement, but creates a real-money risk: during a 2008/2020-magnitude drawdown, a fully-invested top-24 defensive book still drew down ~30-35% (BRK.B, JNJ, PG all lost a third in March 2020). For the *paper validation* this is fine — we measure what we measure. For any eventual *live* deployment we need a documented escape valve.

**Fix:** in the pre-registration, explicitly note two modes:
- **Validation mode (this test):** SMA gate OFF, fully invested, measure unconditional CAPM-α. This is what `phase_envelope.py` runs.
- **Live mode (future, only if validation passes):** SMA gate OFF, but a **VIX-conditional cash floor**: if VIX > 35 at rebalance, scale gross exposure to `max(0.5, 1 − (VIX−35)/40)`, hold remainder in SHV. Disclosed up-front so we don't sneak it in post-hoc.

This isn't part of the validation test; it's a pre-committed deployment rule so we don't move the goalposts later.

### Patch 3 — Pre-registration: lock the snapshot ID and the phase-set NOW

The single highest-leverage anti-overfit move, given this system's phase-luck history:

- **Snapshot ID** for the test must be **written into `reports/defensive_v1_preregistration.md` before any run.** No "let me try a different snapshot if this one fails." One snapshot, 9 phases, 8 hurdles, ship-or-falsify.
- **Phase set is pre-declared**: offsets `{0, 7, 14, 21, 28, 35, 42, 49, 56}` trading days. No cherry-picking 6 of 9 after seeing results.
- **No hurdle re-weighting post-hoc.** If we hit 7/8 and want to argue "well, the L/S Sharpe was 0.48, close enough" — no. Falsified is falsified. Theme B exists.
- **Multiple-comparisons accounting:** this is candidate #1 of Theme A. If it falsifies and we test 2 more defensive composites, the per-test α-hurdle rises (Bonferroni: 3% → ~5% effective for the 3rd test). Note this in the pre-reg so we don't accumulate Type-I error silently across the discovery loop.

### Final shipped spec (consolidated)

**Signals (sector-z, equal-weighted composite, NaN-drop for missing):**
1. Accruals: `(CFO_ttm − NI_ttm) / avg(TA_t, TA_{t−4Q})`, sign +
2. Margin CV: `stdev(op_margin_8Q) / |mean(op_margin_8Q)|`, ≥6/8 quarters, sign −
3. ΔDebt/Assets: `(D/A_t − D/A_{t−4Q})` gated to firms with D/A_t > universe median, sign −

**Portfolio:** Top 24 by composite z, sector cap 25%, 126d-inverse-vol weights bounded [2.1%, 8.3%], renormalized.

**Execution:** 63-day cadence, 0.75 incumbent z-bonus, ±15% relative band + 1.25× absolute drift ceiling, SMA gate OFF (validation), VIX-35 cash floor (live only).

**Falsification gates (all 8 required, pre-registered):** α≥3%, 6/9 phases positive, COVID+2022 median α≥0, VIX>25 α≥5%, β<0.85, L/S Sharpe≥0.5, >95th pct permutation null (full-universe shuffle), correlation with m/q/v < 0.7.

Ship it. Write the pre-reg, freeze the snapshot ID, run `factor_lab.py` then `phase_envelope.py`. Results stand as-is.

### Gemini
Here is the final, consolidated specification for the **Defensive Cash-Flow Composite (v1)**. This document serves as the exact blueprint for `src/factors/` implementation and the content for `reports/defensive_v1_preregistration.md`.

### 1. Thesis: The "Boring Quality" Anomaly
Investors systematically overpay for high-beta, lottery-like growth and underprice stable, cash-generating businesses. By isolating firms with high cash conversion, durable margins, and active de-leveraging, we construct a low-beta ballast. The inefficiency exploited is behavioral (lottery preference) and structural (benchmark-hugging funds ignoring slow-growth cash cows), yielding positive Jensen’s α in down/high-VIX regimes.

### 2. Signal Definitions (EDGAR PIT + Polygon EOD)
Evaluated cross-sectionally. Missing data triggers a `NaN` drop for that specific signal (retains partial-credit averaging for the rest).
*   **Accruals (Earnings Quality):** `(CFO_ttm - NI_ttm) / avg(TA_t, TA_{t-4Q})`. Higher cash relative to net income = better. *Sign: Positive.*
*   **Margin Durability (Moat):** `stdev(op_margin) / abs(mean(op_margin))` over trailing 8 quarters. Requires ≥6/8 quarters of `operating_income / revenue`. *Sign: Negative.*
*   **De-leveraging (Balance Sheet):** Uses `Debt/Assets` = `(short_term_debt + long_term_debt) / assets`. *Gate:* If `D/A_t` < universe median, score = 0. Else, `D/A_t - D/A_{t-4Q}`. *Sign: Negative.*
*   **Processing:** Compute within-GICS-sector z-scores for each signal (fallback to universe z if sector < 8 names). Equal-weight the 3 z-scores into a composite rank.

### 3. Portfolio Construction & Execution
*   **Universe & Selection:** PIT S&P 500. Hold the top 24 names by composite z-score.
*   **Sector Cap:** Maximum 25% allocation per GICS sector.
*   **Sizing (Beta-Suppression):** 126-day inverse realized volatility. Bounded between `0.5x` (2.1%) and `2.0x` (8.3%) of equal-weight, then renormalized.
*   **Cadence & Turnover:** 63-day rebalance. Apply 0.75 hysteresis bonus to incumbent z-scores.
*   **Lazy Rebalance Bands:** Trade an incumbent *only* if `|w_current - w_target| / w_target > 0.15` OR absolute drift `w_current > 1.25 * initial_target`.
*   **Regime Gate:** OFF for backtest validation (fully invested). For future live deployment *only*: If VIX > 35, scale gross exposure to `max(0.5, 1 - (VIX-35)/40)`, holding the balance in cash.

### 4. Pre-Registered Validation Plan
Locked to a single snapshot ID (2022–2024–26). Evaluated across 9 predefined phase offsets `{0, 7, 14... 56}`. **All 8 hurdles must pass**, or the strategy is falsified. (Note: Future Theme B tests will require a Bonferroni-adjusted α > 5%).
1.  Phase-averaged Jensen's α ≥ +3%/yr.
2.  ≥ 6 of 9 phases show positive α.
3.  COVID + 2022 sub-cell median α ≥ 0%.
4.  High-VIX (>25) sub-period α ≥ +5%/yr.
5.  Realized Portfolio β < 0.85.
6.  L/S Sharpe ≥ 0.5 (sector-neutral, inv-vol sizing on both legs).
7.  Actual α > 95th percentile of a 200-draw permutation null (shuffle composite z-scores across the *full universe*, then apply sector-caps/sizing).
8.  Daily return correlation with live m/q/v composite < 0.7.

### 5. Final Verdict & Next Steps
**Realistic Edge:** This is structurally sound. It bypasses the EPS bug, explicitly controls for beta via sizing and margin CV, and prevents sector-bet drift. The primary failure mode is that "Boring Quality" may still suffer severe drawdown in a liquidity crash (hence the VIX > 35 live cash rule).

**Action:** Write the pre-registration and run `factor_lab.py` immediately to see if it clears the null. However, **do not deploy this to Alpaca yet.** The live m/q/v forward paper run must reach its 2026-08-27 review untainted. If this Defensive Composite passes all 8 hurdles, it goes on the shelf as our validated "Regime B" engine, ready for a 50/50 blended deployment *after* the current OOS test concludes.

### Opus 4.7
### Opus — FINAL SPEC: Defensive Cash-Flow Composite (v1)

This is the canonical, ship-ready specification. Any deviation requires a new pre-registration document and a new snapshot ID.

---

### 1. Thesis & Inefficiency

**Thesis:** The live m/q/v + PEAD book is a *bull-regime engine* with a regime gate that fails fast crashes (COVID CAPM-α median −7.9%, 2025-01 whipsaw cost 6.46pp). It has no native source of low-beta α. We build one.

**Inefficiency exploited — "Boring Quality":** Investors systematically overpay for lottery-like high-σ growth and underprice firms with (a) high cash conversion vs reported earnings, (b) durable operating margins, and (c) active de-leveraging. Persistence mechanism is behavioral (lottery preference, salience of growth narratives) + structural (benchmark-tracking funds underweight slow compounders). The signals are PIT-observable from EDGAR filings and slow-moving, so 63-day cadence is appropriate.

**What we are NOT claiming:** outperformance in bull markets. The bar is positive Jensen's α in COVID/2022/high-VIX cells, β < 0.85, and *uncorrelated* daily returns vs the live composite. If it just ties SPY in bulls and pays in bears, it's a successful diversifier.

### 2. Signals (sector-z, equal-weighted, NaN-drop partial-credit)

All from EDGAR PIT, read only ≤ as_of. Bypasses the EPS-TTM duration bug by using raw aggregates.

| Signal | Formula | Lookback | Sign | Gate |
|---|---|---|---|---|
| **Accruals** | `(CFO_ttm − NI_ttm) / avg(TA_t, TA_{t−4Q})` | 4Q sum, 2-point TA avg | + (high = good) | none |
| **Margin CV** | `stdev(op_margin_q) / |mean(op_margin_q)|`, where `op_margin_q = operating_income/revenue` | 8Q, require ≥6 non-null | − (low = good) | NaN if <6Q |
| **ΔDebt/Assets** | `D/A_t − D/A_{t−4Q}`, where `D/A = (st_debt + lt_debt)/assets` | 4Q diff | − (decline = good) | score = 0 if `D/A_t` < universe median |

**Processing:** Within-GICS-sector z-score per signal (universe-z fallback if sector n<8). Equal-weight the three sector-z's into composite z. Rank descending.

### 3. Portfolio Construction & Execution

- **Universe:** PIT S&P 500 (re-resolved per rebalance — fixes the live system's universe-freeze bias for this test).
- **Selection:** Top 24 by composite z.
- **Sector cap:** 25% max per GICS sector.
- **Sizing:** 126-day realized-vol inverse weights, bounded [2.1%, 8.3%] (0.5×–2.0× equal-weight), renormalized.
- **Cadence:** 63 trading days.
- **Hysteresis:** 0.75 incumbent z-bonus.
- **Lazy rebalance:** trade only if `|w_curr − w_tgt|/w_tgt > 0.15` **OR** `w_curr > 1.25 × initial_target`.
- **Regime gate:** **OFF for validation** (measures unconditional CAPM-α). **Live mode (post-validation only):** VIX>35 → scale gross to `max(0.5, 1−(VIX−35)/40)`, SHV remainder. Pre-committed; not part of this test.

### 4. Pre-Registered Validation (write to `reports/defensive_v1_preregistration.md` before any run)

**Snapshot ID:** frozen and written into the pre-reg before first run. One snapshot, no retries.
**Phase offsets:** `{0, 7, 14, 21, 28, 35, 42, 49, 56}` trading days. No cherry-picking.

**All 8 hurdles required (any fail = falsified):**

1. Phase-averaged Jensen's α ≥ +3%/yr
2. ≥ 6/9 phases positive α
3. COVID + 2022 sub-cell median α ≥ 0%
4. VIX>25 sub-period α ≥ +5%/yr (annualized from daily)
5. Realized portfolio β < 0.85
6. L/S decile Sharpe ≥ 0.5 (top-24 − bottom-24, sector-neutral, inv-vol both legs)
7. Real α > 95th pct of 200-draw permutation null (shuffle composite-z across **full universe**, re-apply full pipeline including sector-neut and sizing)
8. Daily-return Pearson correlation with live m/q/v ∈ [−1.0, 0.7]

**Multiple-comparisons:** This is Theme A candidate #1. If falsified and Theme A candidates #2/#3 are tested, hurdle #1 escalates per Bonferroni (3% → 4% → ~5%). Tracked in the pre-reg.

**No post-hoc moves:** no hurdle re-weighting, no "close enough," no snapshot swaps, no phase re-selection. Falsified is filed; we move to Theme B.

### 5. Honest Verdict

**Realistic edge — moderate-to-good probability of passing 5-6 hurdles, lower probability of all 8.** Accruals (Sloan 1996) and margin durability are among the most-replicated quality anomalies and survive in PIT data. De-leveraging is thinner literature but mechanically defensive. Sector-neutralization + inverse-vol sizing + the L/S hurdle structurally force the result to be low-β residual α, not closet quality-growth.

**Failure modes, ranked by likelihood:**
1. **Correlation with m/q/v > 0.7** — most likely kill. Quality factors are notoriously collinear. If this fires, the composite is real but redundant.
2. **VIX>25 α < 5%** — high-VIX cells have small n (handful of rebalances in 2022/COVID-echo); estimate is noisy. May fail on variance alone.
3. **L/S Sharpe < 0.5** — the long leg may carry the α with no symmetric short premium (asymmetric anomaly), which would file as "long-only edge, not robust factor."
4. **Permutation null** — least likely failure given three independent signals, but possible if one signal dominates.

**Is it worth building before the 2026-08-27 paper review?** **Yes — but DO NOT DEPLOY.** Run `factor_lab.py` + `phase_envelope.py` now. The live m/q/v paper run must finish its OOS window untainted. If Defensive v1 clears all 8 hurdles, it sits on the shelf as a validated Regime-B engine. Post-Aug-27, conditional on the live run not falsifying m/q/v, we test a 50/50 blend with a fresh pre-registered snapshot. If Defensive v1 fails, we file it and move to Theme B with the Bonferroni-adjusted hurdle.

**Ship the spec. Freeze the snapshot. Run the test. Results stand.**
