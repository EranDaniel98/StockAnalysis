# Strategy Debate — 2026-05-28

- **Opus model:** `claude-opus-4-7`
- **Gemini model:** `gemini-3.1-pro-preview`
- **Rounds:** 6 · **Opener:** Gemini
- **Format:** collaborative co-design of a new strategy
- **Seed:** `scripts/debate_seed_riskmom.md`

---

### Gemini
This is a solid starting point. The live system’s vulnerability is clear: Momentum (12-1) is the strongest structural anomaly we have, but its left-tail crash risk (COVID, 2022) combined with phase-luck noise makes raw momentum un-tradeable as a standalone core. 

To fix this and build a defensible, breadth-robust strategy on the 2000-name universe, I propose the **Defensive Momentum & Drift Composite**. The core inefficiency is behavioral underreaction (to earnings and medium-term trends), bounded by limits to arbitrage (idiosyncratic risk is costly for hedge funds to short). 

Here is the v0 specification for the signals, strictly constrained to Polygon EOD, SPY, and yfinance earnings:

### 1. Risk-Managed Momentum (RM-MOM)
Standard momentum crashes when a high-volatility bear market suddenly reverses, causing high-beta "losers" to surge. We neutralize this by scaling each stock's momentum by its own trailing volatility (Barroso & Santa-Clara).
*   **Formula:** `(Close[t-21] / Close[t-252] - 1) / Annualized_Vol`
*   **Annualized_Vol:** `std(Daily_Returns[t-126 to t]) * sqrt(252)`
*   **Cross-Sectional:** Z-score of the ratio.

### 2. Idiosyncratic Volatility (IVOL)
The Ang-Hodrick-Xing-Zhang anomaly: low idiosyncratic volatility stocks systematically outperform. This also acts as a structural defense against "junk rallies."
*   **Formula:** Run an OLS regression of the stock's daily returns against SPY daily returns over a 63-day lookback: $R_{stock} = \alpha + \beta R_{spy} + \epsilon$. 
*   **Signal:** `-1 * std(residuals)`. (Inverted, because we want *low* IVOL).
*   **Cross-Sectional:** Z-score.

### 3. Short-Term Reversal (STR)
Since we are expanding to the 2000-name universe where breadth matters, 1-month reversal is highly effective at capturing liquidity provision and overreaction in smaller caps. 
*   **Formula:** `-1 * (Close[t] / Close[t-21] - 1)`
*   **Cross-Sectional:** Z-score.

### 4. Post-Earnings Announcement Drift (PEAD)
We retain the live system's PEAD signal as it is our only sign-stable, breadth-robust baseline.

### The Synthesis & The "Catch"
By combining RM-MOM, IVOL, STR, and PEAD, we are explicitly engineering a portfolio that buys high-quality, low-drama winners that recently beat earnings, while buying on short-term 1-month dips (STR). 

**Opus, over to you for the next critical layer:**
1. **Combination & Neutralization:** How exactly should we blend these? Given the mega-cap era tilt that previously hurt the broad universe, should we explicitly sector-neutralize the z-scores before summing them?
2. **The Validation Plan:** The dossier warns of a ±20-30pp phase-noise envelope. Please define the exact pre-registered decision rule and permutation/null baseline we will use in `scripts/factor_lab.py` to prove this composite isn't just another phase-luck artifact. 
3. **Sizing:** Should we move away from equal-weight top-24 and use inverse-volatility sizing to further suppress the momentum crash risk?

### Opus 4.7
### Opus — Locking down combination, sizing, and (most importantly) the falsifiability plan

Gemini's four legs are sound. Three concrete fixes + the validation contract.

### 1. Combination: sector-neutral rank-sum, with one orthogonalization

Simple sum of z-scores will double-count. RM-MOM and STR are mechanically anti-correlated (12-month winners are often 1-month winners), and IVOL correlates with momentum sign in bear regimes. Fix:

**Step A — sector-demean each raw signal** (GICS sector from EDGAR `sic` → GICS map we already have in `sector_neutralize.py`). For each signal `s` and sector `k`: `s_neutral = s - mean(s | sector=k)`, then cross-sectional z-score. This kills the mega-cap/era tilt that wrecked the broad-universe test.

**Step B — orthogonalize STR against RM-MOM**: regress STR_z on RMMOM_z cross-sectionally each rebalance, keep residual. Prevents the 1-month dip from cannibalizing the 12-1 winner signal.

**Step C — equal-weight rank-sum** of `{PEAD_z, RMMOM_z, IVOL_z, STR_resid_z}`. Rank-sum (not z-sum) caps outlier influence — already the live convention in `composite.py`.

Weights stay equal at 0.25 each. **No tuning knobs** beyond that — every free parameter is a phase-luck amplifier.

### 2. Sizing: inverse-IVOL, not inverse-vol

You're right to drop equal-weight, but inverse *total* vol just reloads the low-vol bet we already have in leg 2. Use **inverse-IVOL sizing** (reuse the residual std from leg 2): `w_i ∝ 1/σ_idio,i`, capped at 2× equal-weight, sector cap 25% (existing config). Top-30 (slight bump from 24 to absorb the broader universe without diluting). Rebalance cadence stays 63d; add a **monthly drift check** — if any name's weight drifts >1.5× target between rebalances, trim back. Costs: assume 10bps round-trip, validate sensitivity to 50bps as the live system already does.

### 3. Validation contract — pre-registered, write it BEFORE running

This is the part that determines whether we learn anything. Lock these in `scripts/factor_lab.py` as a JSON config committed before the first run:

**Datasets (8 cells):** {S&P500, broad-2000} × {2019-20 COVID, 2021-22 bull→bear, 2023-24 recovery, 2024-26 recent}.

**Per-cell metrics:**
- Phase-averaged Sharpe across all 63 rebalance offsets (0..62), report **median + IQR + %-positive-phases**, never offset-0.
- CAPM α (Jensen's, not raw excess) vs SPY — fixes the dossier's known measurement bug.
- Forward IC at 21d/63d horizons.

**Null baseline:** 200 permutations per cell where signal values are shuffled *within sector and date* (preserves sector/time structure, kills only the cross-sectional ranking). Report empirical p-value of realized IC vs null.

**Pre-registered ship rule (ALL must hold):**
1. Median phase-Sharpe > live PEAD+momentum baseline in ≥6/8 cells.
2. Permutation p<0.05 in ≥6/8 cells.
3. Sign-consistent CAPM α in ≥7/8 cells (allows one COVID-style miss).
4. Composite IC ≥ 1.3× best single leg on broad universe.
5. Worst-cell phase-Sharpe ≥ -0.3 (crash floor).

**Fail any → discard the composite, not tune-and-retry.** That discipline is the whole point.

**Gemini — two open items:** (a) confirm the within-sector-and-date permutation is the right null (vs full shuffle), and (b) should we add a tripwire that auto-flattens the book if realized 21d composite IC goes negative for 2 consecutive rebalances?

### Gemini
**Gemini — Refining the execution, fixing a duration mismatch, and answering the open questions**

Opus, your combination logic and validation contract are rock solid. You’ve successfully sealed off the phase-luck and era-tilt vulnerabilities. 

To answer your open items:
**1. The Permutation Null:** I strongly confirm the within-sector-and-date shuffle. A full cross-sectional shuffle destroys the market/sector covariance matrix, creating an artificially weak "strawman" null. By forcing the null to pick randomly *within the same sector on the exact same day*, we isolate whether our specific factor ranks actually drive the alpha, rather than just sector beta.

**2. The IC Tripwire:** **Reject.** Do not add the 21d negative-IC tripwire. Factor IC is notoriously noisy over short windows. Because IC requires forward returns, a 21d IC calculation means we are reacting to a signal that is already a month stale. This introduces a meta-timing layer that risks the exact same whipsaw that cost the live system -6.46% in 2024-26. We must rely on the *existing* 75-SMA/200-SMA SPY + VIX regime gate to handle macro crash protection.

### The Crucial Fix: The STR Duration Mismatch
We have a structural error in blending STR with a 63-day rebalance. A 1-month short-term reversal signal captures liquidity provision and micro-structure overreaction; its alpha decays in 10 to 15 days. If we rank-sum STR into a 63-day hold, we are carrying dead weight for 45+ days.

**The Solution:** Drop STR from the core 63-day rank-sum. Instead, we replace it by restoring the live system's **EDGAR PIT Quality** factor, which perfectly matches a 63-day holding period and provides fundamental downside protection. 

*   **Quality Formula:** `Gross Profit / Total Assets` (Novy-Marx), sourced strictly from `fundamentals_pit.json`. 
*   **Why this is elegant:** The dossier explicitly warns of a known bug in the Value factor (`compute_eps_ttm` mixing quarterly/YTD durations). By using Gross Profit / Total Assets and PEAD (standardized surprise), we completely bypass the EPS duration bug while retaining fundamental exposure.

### The Final Implementable Specification

We now have a complete, strictly defined system ready for `scripts/factor_lab.py`:

1.  **The 4-Leg Composite (63-day persistence):**
    *   `RMMOM`: `(Close[t-21] / Close[t-252] - 1) / (std(Returns[t-126:t]) * sqrt(252))`
    *   `IVOL`: `-1 * std(residuals)` from 63d OLS against SPY.
    *   `PEAD`: Standardized unexpected earnings (yfinance fallback, as live).
    *   `QUALITY`: `Gross Profit / Total Assets` (EDGAR PIT).
2.  **Transformation (`composite.py`):**
    *   Calculate raw values.
    *   Sector-demean each raw value using the EDGAR `sic` → GICS map.
    *   Cross-sectionally Z-score the demeaned values.
    *   Equal-weight Rank-Sum the four Z-scores.
3.  **Execution & Sizing:**
    *   Universe: Broad 2000.
    *   Filter: Gate via existing 75-SMA SPY + VIX check.
    *   Hold: Top 30 names.
    *   Sizing: Inverse-IVOL (`w_i ∝ 1/σ_idio,i`), max 2x equal-weight, sector cap 25%.
    *   Turnover Control: 63-day cadence + 0.75 hysteresis carry bonus to incumbents.

We have eliminated the EPS bug, neutralized the mega-cap era tilt, fixed the momentum crash risk via vol-scaling, and locked in a ruthless, pre-registered falsification plan. 

Unless you see a data-layer violation in the Quality replacement, this composite is ready to be locked into the JSON config and run against the 8 cells.

### Opus 4.7
### Opus — Final lockdown: closing three implementation gaps before we freeze the spec

Gemini, the swap of STR → Quality is the right call (duration match + sidesteps the EPS bug). No data-layer violations — `Gross Profit / Total Assets` is computable from EDGAR `Revenues - CostOfGoodsAndServicesSold` over `Assets`, all PIT-available. Locking it in. Three remaining gaps to close before we commit the JSON:

### 1. Quality factor — pin the exact EDGAR fields (the EPS bug lurks here too)

Generic "Gross Profit" is a trap on EDGAR — companies tag it inconsistently and the same period-mixing bug that broke value can break GP/A. Pin it:

- **Numerator:** `us-gaap:GrossProfit` (preferred, when tagged) ELSE `us-gaap:Revenues - us-gaap:CostOfGoodsAndServicesSold` (fallback). **Filter to `fp in {Q1,Q2,Q3,Q4}` only** — drop `FY` and any fact where `fp` is null. Sum trailing 4 quarters explicitly; reject names with <4 quarters in trailing 400d.
- **Denominator:** `us-gaap:Assets`, most recent balance-sheet snapshot ≤ as_of.
- **Staleness gate:** if the latest filing is >120 days old as_of, drop the name from the Quality leg (carry neutral z=0, don't fabricate).
- **Winsorize** GP/A at [1%, 99%] cross-sectionally before sector-demean — financials and REITs produce absurd outliers.

This must be implemented as a **standalone PIT unit test** (`test_quality_pit.py`) before the composite runs: assert no fact with `filed > as_of` enters; assert no `FY`+`Qx` mixing in trailing sum. Same test scaffold should be retrofitted to value later.

### 2. IVOL/RMMOM circular dependency

IVOL residuals come from a 63d window; RMMOM denominator uses 126d total vol. These overlap and IVOL sizing then re-uses the IVOL residual. To prevent stacking:

- **RMMOM denominator:** keep 126d total vol (Barroso original).
- **IVOL signal:** 63d residual std as specified.
- **Sizing weight:** use **a separate 252d idio-vol estimate** (longer window = more stable weight, decorrelated from the 63d signal). `σ_size = std(residuals over t-252:t)`. This breaks the signal/sizing circularity that would otherwise let one noisy 63d window drive both selection and sizing.

### 3. Validation contract — one addition, one clarification

**Addition: a "live baseline" cell.** The pre-registered ship rule (#1) compares against "live PEAD+momentum baseline" — define it concretely: rerun the current shipped m/q/v+PEAD composite on the **identical 8 cells with identical phase-averaging** and freeze those numbers as `baseline.json` before any candidate runs. Otherwise "beats baseline" is a moving target.

**Clarification on tripwire:** I accept your rejection of the 21d IC tripwire (whipsaw risk is real). Replace it with a **dispersion tripwire** instead: if cross-sectional std of the composite z-score collapses below 0.5 at a rebalance (signal has no view), hold cash for that cycle. Triggered by signal entropy, not forward returns — no look-ahead, no whipsaw.

### Frozen spec ready for `factor_lab.py`

Composite: `{RMMOM, IVOL, PEAD, QUALITY}`, each sector-demeaned → z-scored → equal-weight rank-summed. STR orthogonalization removed (STR dropped). Inverse-252d-IVOL sizing, top-30, sector cap 25%, hysteresis 0.75, 63d cadence, existing 75/200-SMA + VIX gate, dispersion tripwire. Validation: 8 cells × 63 phase offsets, within-sector-and-date permutation null (200 draws), 5 pre-registered ship gates against frozen baseline.

**Ship it to the lab.** If it fails ≥1 gate, we discard — no retuning.

### Gemini
Opus, your final lockdown is flawless. Separating the sizing IVOL from the signal IVOL perfectly kills the circular dependency, and pinning the EDGAR `fp` tags finally exorcises the duration-mixing bug that has plagued the value factor. 

Here is the final, consolidated specification for the **Defensive Momentum & Quality Composite (DMQC)**. 

### 1. Thesis & Inefficiency Exploited
**Thesis:** Standard momentum is a strong behavioral anomaly (underreaction) but structurally vulnerable to violent crashes during high-volatility regime shifts. We neutralize this left-tail risk by vol-scaling the momentum signal and demanding fundamental confirmation (Quality + PEAD).
**Inefficiency:** Behavioral underreaction to earnings and medium-term trends, bounded by limits to arbitrage (high idiosyncratic risk is costly to short, so low-IVOL names drift upward more cleanly).

### 2. Precise Signal Definitions
All signals evaluate at `t = as_of`, strictly using data $\le$ `as_of`.
*   **RM-MOM (Risk-Managed Momentum):** 
    *   *Formula:* `(Close[t-21] / Close[t-252] - 1) / (std(Returns[t-126:t]) * sqrt(252))`
    *   *Data:* Polygon EOD.
*   **IVOL (Idiosyncratic Volatility):** 
    *   *Formula:* `-1 * std(residuals)` from an OLS regression of daily stock returns vs SPY daily returns over `[t-63 : t]`.
    *   *Data:* Polygon EOD + SPY.
*   **PEAD (Post-Earnings Announcement Drift):** 
    *   *Formula:* Standardized Unexpected Earnings (SUE).
    *   *Data:* yfinance earnings fallback (as live).
*   **QUALITY (Gross Profitability):** 
    *   *Formula:* $\sum_{i=1}^4 GP_i / Assets$. 
    *   *Data (EDGAR PIT):* Numerator is `us-gaap:GrossProfit` (fallback: `Revenues` - `CostOfGoodsAndServicesSold`). **Strictly filter to `fp in {Q1, Q2, Q3, Q4}`**, rejecting `FY` or nulls. Reject if <4 quarters in trailing 400d. Denominator is `us-gaap:Assets` from the latest balance sheet.
    *   *Staleness Gate:* If latest filing > 120 days old, assign neutral raw value (0).
    *   *Winsorize:* Cross-sectionally at [1%, 99%].
*   **Transformation:** For each of the 4 signals $\rightarrow$ Sector-demean using EDGAR `sic` $\rightarrow$ GICS map $\rightarrow$ Cross-sectional Z-score $\rightarrow$ **Equal-Weight Rank-Sum**.

### 3. Mechanics, Sizing, & Execution
*   **Universe:** Broad 2000.
*   **Cadence:** 63 trading days.
*   **Entry/Exit:** Top 30 names by composite rank. Apply existing 0.75 hysteresis carry bonus to incumbents.
*   **Sizing:** Inverse-252d-IVOL (`w_i \propto 1/\sigma_{idio, 252d}`). Max weight 2x equal-weight. Sector cap 25%.
*   **Gates & Tripwires:** 
    *   *Macro Gate:* Existing 75-SMA/200-SMA SPY + VIX regime filter.
    *   *Dispersion Tripwire:* If cross-sectional std of the final composite z-score < 0.5 at rebalance, hold cash for that cycle.

### 4. Pre-Registered Validation Plan (The Falsifiability Contract)
Generate `baseline.json` by running the *current* live m/q/v+PEAD system across the exact grid below. Then run DMQC.
*   **Grid (8 cells):** {S&P500, Broad-2000} $\times$ {2019-20 COVID, 2021-22 Bull$\rightarrow$Bear, 2023-24 Recovery, 2024-26 Recent}.
*   **Evaluation:** Phase-averaged across all 63 offsets (report median + IQR). Null baseline is 200 permutations shuffling signal values *within sector and date*.
*   **Ship Rules (ALL must pass):**
    1. Median phase-Sharpe > `baseline.json` in $\ge$ 6/8 cells.
    2. Permutation p < 0.05 in $\ge$ 6/8 cells.
    3. Sign-consistent CAPM $\alpha$ (Jensen's) in $\ge$ 7/8 cells.
    4. Composite 63d forward IC $\ge$ 1.3x best single leg on the Broad universe.
    5. Worst-cell median phase-Sharpe $\ge$ -0.3.

### 5. Honest Verdict & Next Steps
**Realistic Edge:** High. By replacing raw momentum with RM-MOM and fixing the EPS duration bug via strict EDGAR `fp` filtering, we surgically address the live system's two biggest theoretical flaws. Neutralizing sector tilts prevents the mega-cap era from masquerading as alpha. 
**Failure Modes:** The 63-day cadence means we will still underperform in violent, V-shaped 3-week market recoveries. Inverse-IVOL sizing might concentrate us in "dead" low-volatility value traps if the Quality signal fails to filter them out.
**Recommendation:** Do **not** interrupt the live paper-trading run (ends 2026-08-27). That OOS data is sacred. However, **build this spec in `scripts/factor_lab.py` today**. If it clears the 5-gate validation contract, it becomes the definitive v2 system to deploy when the August review concludes. If it fails, we discard it and learn from the null. Ship it to the lab.

### Opus 4.7
### Opus — Final Consolidated Spec: Defensive Momentum & Quality Composite (DMQC)

---

### 1. Thesis & Inefficiency Exploited

**Core thesis:** Medium-term momentum is the strongest behavioral anomaly available on EOD data (underreaction to trends and earnings), but its left-tail crashes during volatility regime shifts make it un-tradeable raw. We surgically remove the crash risk by **vol-scaling the momentum signal**, **demanding fundamental confirmation** (Quality + PEAD), and **filtering on idiosyncratic risk** (limits-to-arbitrage proxy — low-IVOL names drift more cleanly because they're costlier to short).

**Inefficiencies stacked:**
- Underreaction to medium-term trends (RM-MOM) — Jegadeesh-Titman, risk-managed per Barroso & Santa-Clara 2015.
- Underreaction to earnings news (PEAD) — Bernard-Thomas; live system's only sign-stable broad-universe alpha.
- Profitability premium (Quality) — Novy-Marx 2013; long-horizon, matches 63d cadence.
- Idiosyncratic-vol anomaly (IVOL) — Ang-Hodrick-Xing-Zhang 2006; limits-to-arbitrage.

Each leg has a distinct economic mechanism — the composite is not a re-skin of one factor.

---

### 2. Signal Definitions (all evaluate at `t = as_of`, data ≤ `as_of`)

| Signal | Formula | Lookback | Data |
|---|---|---|---|
| **RM-MOM** | `(Close[t-21]/Close[t-252] - 1) / (std(Ret[t-126:t])·√252)` | 252d / 126d | Polygon EOD |
| **IVOL** | `−std(ε)` where `R_i = α + β·R_SPY + ε` (daily OLS) | 63d | Polygon EOD + SPY |
| **PEAD** | SUE = (actual − consensus) / σ(surprises trailing 8q) | latest ann. | yfinance earnings |
| **QUALITY** | `Σ_{i=1..4} GP_i / Assets` | TTM | EDGAR PIT |

**QUALITY EDGAR rules (locked):**
- Numerator: `us-gaap:GrossProfit` (preferred) ELSE `Revenues − CostOfGoodsAndServicesSold`.
- **Strict `fp ∈ {Q1,Q2,Q3,Q4}`**; drop `FY` and null `fp`. Reject names with <4 quarters in trailing 400d.
- Denominator: `us-gaap:Assets`, latest balance sheet ≤ as_of.
- Staleness gate: filing >120d old → assign raw=0 (neutral, don't fabricate).
- Winsorize cross-sectionally at [1%, 99%].
- **Required PIT unit test `test_quality_pit.py` before composite runs:** asserts no `filed > as_of`, no FY/Qx mixing in trailing sum.

**Transformation pipeline (per rebalance):**
1. Compute raw signal.
2. Sector-demean using EDGAR `sic` → GICS map (`sector_neutralize.py`).
3. Cross-sectional z-score.
4. Convert to rank.
5. **Equal-weight rank-sum** the four ranks (caps outlier influence; matches live `composite.py` convention).

---

### 3. Universe, Entry/Exit, Sizing, Cadence

- **Universe:** Broad ~2000 (re-resolved per rebalance — fixes the universe-freeze eligibility bias).
- **Cadence:** 63 trading days.
- **Selection:** Top 30 by composite rank. Hysteresis carry bonus 0.75 to incumbents.
- **Sizing:** `w_i ∝ 1/σ_idio,252d` (separate 252d IVOL window — breaks signal/sizing circularity with the 63d IVOL leg). Cap: 2× equal-weight per name; 25% per GICS sector.
- **Drift control:** monthly check; trim any name whose weight has drifted >1.5× target between rebalances.
- **Macro gate:** existing asymmetric 200-SMA exit / 75-SMA re-entry + VIX gate (untouched).
- **Dispersion tripwire:** if cross-sectional std of composite z < 0.5 at a rebalance (no view), hold cash that cycle. No look-ahead, no whipsaw.
- **Costs:** assume 10bps round-trip; sensitivity-test to 50bps as the live system does.

---

### 4. Pre-Registered Validation Contract

**Step 0 — Freeze baseline.** Run current live m/q/v+PEAD on the identical grid below, write `baseline.json`, commit before any candidate run. "Beats baseline" becomes immovable.

**Grid (8 cells):** {S&P500, Broad-2000} × {2019-20 COVID, 2021-22 Bull→Bear, 2023-24 Recovery, 2024-26 Recent}.

**Per-cell metrics:**
- Phase-averaged across all 63 rebalance offsets — report **median, IQR, %-positive phases**. Never offset-0.
- **Jensen's CAPM α** vs SPY (not raw excess — fixes the dossier-flagged measurement bug).
- Forward IC at 21d and 63d.

**Null:** 200 permutations per cell, signal values shuffled **within sector and date** (preserves sector/time covariance; isolates the cross-sectional ranking).

**Ship rule — ALL five must hold:**
1. Median phase-Sharpe > `baseline.json` in ≥6/8 cells.
2. Permutation p<0.05 in ≥6/8 cells.
3. Sign-consistent Jensen's α in ≥7/8 cells.
4. Composite 63d IC ≥ 1.3× best single leg on the broad universe.
5. Worst-cell median phase-Sharpe ≥ −0.3 (crash floor).

**Failure → discard, do not retune.** That discipline is the entire point.

---

### 5. Honest Verdict

**Realistic edge:** Moderate-to-high *conditional on validation*. Every change is documented in the literature and surgically targets a specific live-system failure: RM-MOM kills momentum crashes; strict `fp` filtering exorcises the EPS duration bug; sector-demeaning removes the mega-cap era tilt that wrecked the broad-universe test; inverse-IVOL sizing dampens left-tail variance. Four orthogonal mechanisms = harder to phase-luck through 5 ship gates than any single-factor candidate.

**Failure modes (named, not hidden):**
- 63d cadence still misses V-shaped 3-week recoveries — by design.
- Inverse-IVOL sizing could concentrate in low-vol value traps if Quality misclassifies (winsorization + staleness gate mitigate, don't eliminate).
- PEAD via yfinance has known coverage gaps on small caps — broad-universe PEAD leg may degrade to near-zero contribution there; composite must clear gate #4 *without* depending on it.
- The ship rule is severe enough that **the most likely outcome is failure**, and that is the correct prior — most factor candidates should fail an honest pre-registered test.

**Build before 2026-08-27 paper review?** **Yes — build in `factor_lab.py`, do not deploy.** The live paper run is sacred OOS data; touching it nukes its evidentiary value. But the lab is the right place to run DMQC against the 5 gates *now*, so that on August 27 we have either (a) a validated v2 ready to ship, or (b) a documented null result that sharpens the next iteration. Either outcome beats waiting.

**Ship it to the lab.**
