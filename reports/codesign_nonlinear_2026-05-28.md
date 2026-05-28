# Strategy Debate — 2026-05-28

- **Opus model:** `claude-opus-4-7`
- **Gemini model:** `gemini-3.1-pro-preview`
- **Rounds:** 8 · **Opener:** Gemini
- **Format:** collaborative co-design of a new strategy
- **Seed:** `scripts/debate_seed_nonlinear_unique.md`

---

### Gemini
To kick off, let’s lean directly into this system’s true moat: **EDGAR Point-In-Time (PIT) filings**. Standard linear models buy the headline earnings beat and short the miss (PEAD). This is heavily arbed. But what if we condition the price reaction on the *accounting reality* buried in the cash flow statement? 

I propose the **Mirage Reversal (PEAD × PIT Accruals)**. 

### The Core Inefficiency & Persistence Mechanism
**Mechanism:** *Attention Scarcity & "Functional Fixation."* 
When earnings drop, algos and retail trade the headline EPS beat instantly, causing the initial price jump. However, the actual 10-Q detailing the cash flow statement often drops concurrently or slightly later on EDGAR. The market takes weeks to digest whether an EPS beat was driven by real cash flow or aggressive accounting (e.g., pulled-forward receivables, inventory buildup). 
Arbitrageurs don't instantly close this gap because aggressively shorting a headline EPS beat in the first 5 days carries massive career and margin risk (squeeze danger).

### The Nonlinear Interaction: $Signal = f(A, B)$
We interact a price-momentum signal ($A$) with a fundamental quality gate ($B$), where the sign of $A$ *flips* conditional on the extremes of $B$.

*   **Signal A (Headline Reaction):** 3-day abnormal return around the earnings date (using `yfinance` earnings dates + `Polygon` EOD). 
*   **Signal B (The Truth):** Operating Accruals from EDGAR PIT. 
    *Formula:* $(Net\ Income - Operating\ Cash\ Flow) / Total\ Assets$. High accruals = low quality (earnings are an accounting mirage).

**The Conditional Logic:**
Instead of a linear $Z_{PEAD} + Z_{Accruals}$, we apply a non-monotonic mapping:
1. Rank the universe into Accrual Deciles ($D_{Accruals}$, 1 = lowest/best cash conversion, 10 = highest/worst).
2. Calculate cross-sectional $Z_{PEAD}$.
3. **The Interaction:**
   * If $D_{Accruals} \le 3$ (High Quality): $Final\_Score = +Z_{PEAD}$. The beat is real; follow the drift.
   * If $D_{Accruals} \ge 8$ (Low Quality): $Final\_Score = -Z_{PEAD}$. The beat is a mirage; **fade** the drift.
   * If $4 \le D_{Accruals} \le 7$: $Final\_Score = 0$. (Ignore; no edge).

A linear model averages the PEAD effect across all accrual regimes and sees a positive slope. It completely misses the structural reversal hidden in the $D_{Accruals} \ge 8$ bucket.

### Hooks for You (Opus)
1. **The EDGAR Data Trap:** The dossier notes a known bug in EPS period disambiguation (quarterly vs YTD). To avoid this, how exactly should we construct the $(Net\ Income - Operating\ Cash\ Flow)$ proxy using the raw `fundamentals_pit.json` facts to ensure we don't mix durations?
2. **Execution Timing:** PEAD decays. Our system rebalances every 63 days. Is a 63-day hold too long for an accrual-reversal? Should we trigger this asynchronously, or can we adapt the lookback to fit the 63-day cross-section?
3. **Validation Plan:** Sketch the exact permutation-null baseline we will use to prove this conditional interaction beats a linear sum in the phase-averaged backtest.

### Opus 4.7
### Opus

Strong setup, Gemini. The Mirage Reversal has the right *shape* — non-monotonic in accruals, exploits the EDGAR latency moat, and a linear PEAD+accrual model genuinely averages this to mush. Let me harden it into something buildable.

### Fix 1: The EDGAR construction (sidestepping the EPS bug)

The EPS-period bug comes from mixing quarterly vs YTD `EarningsPerShareDiluted` facts. We avoid it entirely by working in **dollars from balance-sheet/cash-flow line items**, which EDGAR tags cleanly with `fp` (FY/Q1/Q2/Q3) and `form` (10-Q/10-K):

**Quarterly accruals (Sloan, scaled):**
$$\text{Accrual}_q = \frac{NI_q - CFO_q}{(TA_{q} + TA_{q-1})/2}$$

- `NI_q` = `NetIncomeLoss` for `fp ∈ {Q1,Q2,Q3}` from 10-Q, OR `FY − (Q1+Q2+Q3)` for the Q4 stub from the 10-K. Same recipe for `CFO_q` = `NetCashProvidedByOperatingActivities`. *Never* use a YTD fact as quarterly.
- `TA` = `Assets` (point-in-time, no period issue).
- Filter: require `filed` date ≤ `as_of − 2 trading days` (PIT discipline + a small safety buffer for filing-time uncertainty).
- Universe pre-filter: drop financials (SIC 6000-6799) — accruals are meaningless for banks.

### Fix 2: Cadence mismatch — this can't be a 63-day cross-section

PEAD decays in 30-60 days; a 63-day hold catches the tail end at best, and the *reversal* leg (high-accrual fades) decays faster still. Two repairs:

**Option A (preferred): event-driven sleeve, not a rebalance factor.**
- Scan daily for tickers where: (i) earnings filed in last **5 trading days**, (ii) 10-Q with CFO already on EDGAR, (iii) `|Z_PEAD| > 1`.
- Enter at next open, hold **30 trading days**, exit on time-stop or ±2σ move.
- Carve out ~15-20% of book; remaining ~80% stays in the existing m/q/v composite. This avoids fighting the 63-day cadence.

**Option B (if we insist on integration):** add `MirageScore` as a 4th factor in the 63-day composite, but only for names whose last earnings filing was within the *current* 63-day window. Most names get 0; sparse signal but fits existing infra.

I'd ship A.

### Fix 3: Signal construction (smoothing the cliff)

Hard decile cutoffs (≤3, ≥8) are knife-edge and will whipsaw at boundaries. Use a smooth interaction:

$$\text{Mirage} = Z_{PEAD} \cdot \tanh\!\left(-\,Z_{\text{Accrual}}\right)$$

where `Z_Accrual` is cross-sectionally z-scored within sector. This naturally flips sign at the median, saturates at extremes, and is continuous. The non-monotonicity is preserved: a linear PEAD+Accrual model can't reproduce a product term.

### Fix 4: Sizing & risk

Equal-weight long the top-decile `Mirage`, equal-weight short the bottom-decile (or long-only: skip shorts, hold cash). Cap single name at 2% of book. Sector-neutralize the sleeve (this is a fundamentals signal — don't accidentally bet on energy).

### Fix 5: Validation plan — proving the *interaction*, not the parts

This is the crux. Three nested nulls, phase-averaged across 9 offsets:

1. **Linear null:** backtest `Z_PEAD + Z_Accrual` (additive). Mirage must beat this on phase-median Sharpe by >0.3, else the interaction adds nothing.
2. **Permutation null:** shuffle the accrual ranks *across tickers within each rebalance* 200×, recompute Mirage, build the null distribution of phase-median α. Real signal must exceed 95th percentile.
3. **Placebo gate:** replace `Z_Accrual` with `Z_AssetGrowth` (a known-priced quality proxy). If placebo also "works," the accrual story is just quality-in-disguise — kill it.

Pre-register: ship only if (1) AND (2) AND NOT (3). 

**Your turn:** can you nail down the exact `NetCashProvidedByOperatingActivities` tag fallbacks (some filers use `NetCashProvidedByUsedInOperatingActivities`)? And: do we need a minimum-ADV filter to keep the event sleeve tradeable?

### Gemini
Opus, excellent catch on the EPS bug, but we have a critical math flaw in the interaction and a landmine in the EDGAR cash flow reporting that we must fix before writing a line of code.

### Fix 1: The Double-Negative Math Flaw
Your proposed formula, $\text{Mirage} = Z_{PEAD} \cdot \tanh(-Z_{\text{Accrual}})$, breaks down on earnings *misses*. 
If a company misses earnings ($Z_{PEAD} < 0$) and has terrible accruals ($Z_{\text{Accrual}} > 0$, so $\tanh$ is negative), the product becomes **positive** (Long). We would be buying companies with bad earnings *and* bad accounting!

The true interaction we want is that **the headline shock ($PEAD$) creates the mispricing, but the fundamental truth ($Accruals$) dictates the direction.** 
The correct conditional math is:
$$\text{Mirage} = -Z_{\text{Accrual}} \cdot |Z_{PEAD}|$$

*   **Beat (+2) & Bad Accruals (+2):** $-2 \cdot |-2| = -4$ (Strong Short — fade the mirage).
*   **Beat (+2) & Good Accruals (-2):** $-(-2) \cdot |2| = +4$ (Strong Long — follow the real cash).
*   **Miss (-2) & Bad Accruals (+2):** $-2 \cdot |-2| = -4$ (Strong Short — follow the truth downward).
*   **Miss (-2) & Good Accruals (-2):** $-(-2) \cdot |-2| = +4$ (Strong Long — buy the unwarranted dip).

This perfectly scales the accrual signal by the magnitude of the market's recent attention/overreaction ($|Z_{PEAD}|$).

### Fix 2: The EDGAR YTD Trap (Crucial)
You suggested pulling `NetCashProvidedByOperatingActivities` directly for Q1/Q2/Q3. **This will fail.** Unlike the income statement, EDGAR cash flow statements in 10-Qs are almost universally reported on a **Year-To-Date (YTD)** basis. 
To get discrete quarterly $CFO_q$, we *must* subtract the prior period's YTD value:
*   Q1 CFO = Q1 YTD
*   Q2 CFO = Q2 YTD − Q1 YTD
*   Q3 CFO = Q3 YTD − Q2 YTD
*   Q4 CFO = FY − Q3 YTD

**Tag Fallbacks:** Use `NetCashProvidedByOperatingActivities`. If null, fallback to `NetCashProvidedByUsedInOperatingActivities`, then `NetCashProvidedByOperatingActivitiesContinuingOperations`. 

### Fix 3: Integrating into the 63-Day Architecture (Option B)
Option A (an asynchronous event-driven sleeve) violates the system's hard architectural constraint: the pipeline relies on frozen 63-day snapshots (`scripts/build_snapshot.py`) and a cross-sectional composite. We cannot easily bolt on a rolling 30-day async execution loop without rewriting the paper-trading engine.

We must use **Option B**, but we solve the PEAD decay by applying a time-decay multiplier to the $PEAD$ magnitude:
$$\text{Decay} = \max\left(0, 1 - \frac{\text{Days Since Earnings}}{45}\right)$$
$$\text{Final Signal} = -Z_{\text{Accrual}} \cdot (|Z_{PEAD}| \cdot \text{Decay})$$

This fits perfectly into `src/factors/composite.py`. If a stock hasn't reported in the last 45 days, the multiplier is 0, and it defaults to the rest of the m/q/v composite. 

### Fix 4: ADV Filter
To ensure the event-driven liquidity is there to absorb our trades, apply a strict pre-filter using Polygon EOD: **20-day median dollar volume > $15M**. If it fails, `Mirage = 0`.

### The Validation Lock
Your 3-step validation plan (Linear Null, Permutation Null, Placebo Gate) is bulletproof. By substituting `Z_AssetGrowth` in the Placebo Gate, we definitively prove whether the *cash-flow mismatch* is the mechanism, or if it's just generic quality. 

If you agree with the $|Z_{PEAD}|$ math correction and the YTD cash-flow extraction logic, this specification is tight, measurable, and ready to be coded into a new factor class.

### Opus 4.7
### Opus

Gemini, you're right on both counts — the math flaw is real and the YTD trap would have silently corrupted every quarterly accrual. Accepting both fixes. But your corrected formula has its own subtle problem, and Option B needs one more repair before we ship.

### Fix 1: The corrected formula is *almost* right — but it's no longer an "interaction"

Look closely at $\text{Mirage} = -Z_{\text{Accrual}} \cdot |Z_{PEAD}|$. The **sign** is now driven entirely by $Z_{\text{Accrual}}$. $|Z_{PEAD}|$ is just a magnitude scaler. A linear model with `−Z_Accrual` alone would capture 80% of this — it's basically Sloan's accrual anomaly with a PEAD-attention weight. We've lost the structural non-monotonicity that justified the whole exercise.

The genuine interaction we want is: **accruals matter *more* when there's a fresh earnings shock to anchor attention on**. That's a magnitude-conditional gate, not a sign-flip on PEAD. So the formula is defensible, but we must reframe the thesis:

> "Sloan's accrual anomaly, **gated and amplified by recent earnings-attention**." 

The novelty isn't sign-flipping PEAD — it's that the accrual edge is *concentrated in the post-earnings attention window* where mispricing is freshest, and *zero elsewhere*. Linear `Z_Accrual + Z_PEAD` cannot replicate the product structure.

For the linear null to be a fair test, we backtest **`Z_Accrual` alone** AND `Z_Accrual + Z_PEAD` — Mirage must beat *both*.

### Fix 2: $|Z_{PEAD}|$ as defined needs sharper teeth

If $Z_{PEAD}$ is just the 3-day return z-score, $|Z_{PEAD}|$ is dominated by volatile names with no real earnings information. Define explicitly:

$$Z_{PEAD,i} = \frac{r_{i,[t_e, t_e+2]} - \overline{r}_{\text{universe}}}{\sigma_{i,60d}}$$

where $t_e$ = earnings filing date on EDGAR (NOT yfinance announce date — they differ by 1-2 days and we have the filing timestamp). Cross-sectionally winsorize at ±3 before taking $|\cdot|$, so a single 10σ name doesn't dominate.

### Fix 3: The decay window has a lookahead landmine

`Days Since Earnings` must use **EDGAR filing date** (`filed` field), not the yfinance `earningsDate`. The yfinance date is often the *announce* date, which precedes the 10-Q filing by days-to-weeks — and our entire mechanism depends on the CFO line being *on EDGAR* before we trade. Rule:

$$\text{Decay} = \max\!\left(0,\ 1 - \frac{t_{\text{as\_of}} - t_{\text{filed,10Q}}}{45}\right)$$

Require `t_filed ≤ t_as_of − 2 trading days` (filing-time buffer). If only the 8-K (announcement) has been filed but not the 10-Q with cash flow, **Mirage = 0**. No CFO = no signal. This is the core PIT discipline.

### Fix 4: Sector neutralization + financials carveout

- Drop SIC 6000-6799 (banks, insurers — accruals semantically broken).
- Z-score `Accrual` **within GICS sector**, not universe-wide. Retail and software have structurally different working capital cycles; a universe z-score bakes in a sector bet.

### Fix 5: Integration into the composite (Option B, concrete)

In `src/factors/composite.py`, add `mirage.py` returning `(ticker, raw, rank, z_score)` like every other factor. Weight in `config/strategies.yaml`:

```yaml
factors:
  momentum_12_1: 0.30
  quality:      0.25
  value:        0.20   # still suspect; capped
  pead:         0.10   # existing
  mirage:       0.15   # NEW
```

For names where Decay=0, mirage z=0 (no penalty, no boost — they're judged on m/q/v alone). For names where Decay>0, mirage participates. Sector cap stays at existing config value.

### Fix 6: Validation plan — locked

Phase-averaged across 9 offsets, snapshot-frozen, on 2021-2026:

1. **Linear nulls (two):** beat both (a) `Z_Accrual` alone and (b) `Z_Accrual + |Z_PEAD|·Decay` additive by ≥0.3 phase-median Sharpe.
2. **Permutation null:** within each rebalance, shuffle `Z_Accrual` across tickers 200×; real phase-median α must exceed 95th percentile of null.
3. **Placebo gate:** replace `Z_Accrual` with `Z_AssetGrowth`; if placebo phase-median α > 50% of real, kill — it's generic quality.
4. **Decay placebo:** replace true filing date with a random date in last 90d; if "fake decay" works, the timing isn't the mechanism.

**Pre-registered ship rule:** (1a) AND (1b) AND (2) AND NOT (3) AND NOT (4). Anything else → null result, do not deploy, write it up.

### Open question for you

The **9-phase offset sweep** on an event-driven signal has a wrinkle: offsetting the rebalance date changes *which earnings windows fall inside the 45-day decay*. That's not phase noise — it's exposure variation. Do we report phase-median α as the headline, or do we need a stronger evaluator (e.g., overlapping 21-day rolls × 5 offsets = 45 sub-backtests) to separate phase luck from earnings-calendar luck?

### Gemini
Opus, your reframing of the mechanism—**"Sloan's accrual anomaly, gated and amplified by recent earnings-attention"**—is precisely the structural edge we need. It respects the math, preserves the non-monotonicity (linear models can't replicate the product gate), and avoids the double-negative trap. 

Here is the final resolution to your open question and the concrete, implementable blueprint.

### Resolving the Earnings Calendar vs. Phase Noise Dilemma
You rightly flagged that offsetting a 63-day rebalance shifts which earnings windows fall into the 45-day decay. But over a 5-year backtest (~20 earnings seasons), shifting the offset simply changes *which cohort* of filers we capture (early mega-caps vs. late small-caps). 

**We stick to the 9-offset phase-averaged median.** If the edge only survives when the rebalance perfectly aligns with week 2 of earnings season, it is brittle and *should* fail the phase sweep. To ensure we aren't grading empty portfolios, we add an **Exposure Consistency Check**: we log the `% of portfolio weight driven by active Mirage signals (Decay > 0)`. If the phase-median α relies on phases where Mirage exposure drops below 10%, the signal is too sparse to trade.

### The Concrete Implementation Blueprint

**1. Universe & Pre-filtering (`src/factors/mirage.py`)**
*   **ADV Gate:** 20-day median Polygon dollar volume > $15M. (Below this, PEAD drift is often illiquidity artifact).
*   **Sector Carve-out:** Drop SIC 6000–6799 (Financials).

**2. The EDGAR YTD Unpacking Algorithm (Strict PIT)**
To get discrete quarterly $CFO_q$ without lookahead, we must subtract the prior period's YTD value, ensuring *both* filings were available before `as_of`:
*   Identify the latest 10-Q/10-K where `filed_date <= as_of - 2 days`.
*   Extract `NetCashProvidedByOperatingActivities` (with fallbacks).
*   **Q1:** $CFO_q = CFO_{YTD, Q1}$
*   **Q2:** $CFO_q = CFO_{YTD, Q2} - CFO_{YTD, Q1}$ 
*   **Q3:** $CFO_q = CFO_{YTD, Q3} - CFO_{YTD, Q2}$
*   **Q4:** $CFO_q = CFO_{FY} - CFO_{YTD, Q3}$
*   *Safety:* If the prior quarter's YTD fact is missing from the PIT DB, $CFO_q = null \rightarrow \text{Mirage} = 0$. Do not guess.

**3. Signal Math & Normalization**
*   **Accruals:** $\text{Accrual}_q = \frac{NI_q - CFO_q}{(TA_q + TA_{q-1})/2}$. Calculate $Z_{\text{Accrual}}$ cross-sectionally **within GICS sector**. Winsorize at ±3.
*   **PEAD:** $Z_{PEAD,i} = \frac{r_{i,[t_e, t_e+2]} - \bar{r}_{\text{universe}}}{\sigma_{i,60d} \cdot \sqrt{3}}$. Winsorize at ±3. ($t_e$ = EDGAR filing date).
*   **Decay:** $\max(0, 1 - \frac{t_{\text{as\_of}} - t_e}{45})$.
*   **Final Score:** $\text{Mirage Raw} = -Z_{\text{Accrual}} \cdot (|Z_{PEAD}| \cdot \text{Decay})$.
*   Return standard tuple: `(ticker, raw, rank, z_score)`.

**4. Composite Integration**
Integrated into `src/factors/composite.py` as a standard factor. 
Weighting: Momentum (0.30), Quality (0.25), Value (0.20), PEAD (0.10), **Mirage (0.15)**. 

### Final Validation Lock (Pre-Registered)
We run `scripts/phase_envelope.py` over 2021–2026. Ship **only if**:
1.  **Linear Nulls:** Mirage beats both `Z_Accrual` alone AND `Z_Accrual + (|Z_PEAD| * Decay)` by ≥0.3 phase-median Sharpe.
2.  **Permutation Null:** Beats 95th percentile of 200× shuffled $Z_{\text{Accrual}}$ ranks.
3.  **Placebo Gate:** Fails if substituting $Z_{\text{AssetGrowth}}$ for $Z_{\text{Accrual}}$ retains >50% of the α (proves cash-flow mismatch is the true mechanism, not generic quality).
4.  **Decay Placebo:** Fails if randomizing $t_e$ within the last 90 days preserves the α.

This spec is fully contained within the data layer, fundamentally unique from standard linear models, and mathematically falsifiable. Ready to build.

### Opus 4.7
### Opus — Final spec lock + the gaps Gemini missed

Gemini, the blueprint is 90% there. Locking it requires closing four implementation gaps that will silently corrupt results if we don't pin them now.

### Gap 1: The PEAD window has a stale-signal problem

$Z_{PEAD}$ as written uses the 3-day return *around the earnings filing date*. But on rebalance day $t_{\text{as\_of}}$, the earnings event could be 1 day old or 44 days old. We're freezing a stale 3-day return and decaying it linearly — which conflates two different things: *initial reaction magnitude* and *time since event*.

Fix: $|Z_{PEAD}|$ is computed **once at the filing event** and stored. The Decay multiplier handles time-since. That's what we want — but be explicit: `mirage.py` needs an **event cache** (`data/pead_events.parquet`: `ticker, filed_date, z_pead`) populated incrementally. On each `as_of`, look up the most recent event within 45 days. No event in window → Mirage = 0. This must be PIT — events filed *after* `as_of − 2d` are invisible.

### Gap 2: Accrual staleness vs PEAD freshness mismatch

The accrual we use should be from **the same 10-Q that triggered the PEAD event**, not the latest available 10-Q. Otherwise on day 30 post-earnings, we're pairing a fresh PEAD shock with a *next-quarter* accrual reading that the market is already digesting. Pin them: `Mirage` uses `(Z_PEAD_event, Z_Accrual_event)` as a *bonded pair* from the same filing. This is the whole "as-filed" mechanism — don't separate them.

### Gap 3: Sizing — equal-weight is wrong here

The composite is equal-weight across top-24. But Mirage is a *sparse, conditional* signal: at any rebalance, maybe 8-15 names have Decay > 0. The other ~470 universe names have Mirage = 0. If we rank-combine equally with momentum/quality/value, the Mirage signal gets crushed in the composite z-score (most ranks are tied at zero).

Fix: handle Mirage as a **tilt**, not a rank-combined factor.
1. Compute the base m/q/v(+pead) composite → pick top-24.
2. Within the top-24, **reweight** by $(1 + 0.5 \cdot \text{Mirage}_z)$ clipped to $[0.5, 1.5]$, renormalize.
3. Additionally: any name *outside* the top-24 with `Mirage_z > +1.5` displaces the weakest top-24 name (max 3 displacements per rebalance, sector-cap respected).

This preserves the existing composite as the chassis and lets Mirage do what it's designed for — amplify high-conviction event-driven names — without diluting it through rank-tie averaging.

### Gap 4: The phase sweep needs an exposure floor (you started this; let me finish it)

Your Exposure Consistency Check is right but underspecified. Define:

- **Active Mirage Exposure (AME)** = $\sum_i w_i \cdot \mathbb{1}[\text{Decay}_i > 0]$ at each rebalance.
- A phase is **valid** only if median AME across its rebalances ≥ 15%.
- **Ship rule additions:** of the 9 phases, ≥7 must be valid. Phase-median α reported across *valid phases only*. If <7 valid, signal is too sparse → null result, do not deploy.

### Gap 5: Cost model — Mirage trades more than m/q/v

The displacement mechanism + tilt reweighting raises turnover. Budget for it:
- Backtest at **15bps and 30bps** per side (existing baseline is ~10-50bps sensitivity sweep).
- Ship rule: phase-median α must remain positive at 30bps round-trip.

### Final pre-registered ship checklist

Strategy ships **iff all true**:
1. Linear null (a): beats `Z_Accrual` alone by ≥0.3 phase-median Sharpe.
2. Linear null (b): beats `Z_Accrual + |Z_PEAD|·Decay` additive by ≥0.3 phase-median Sharpe.
3. Permutation null: phase-median α > 95th percentile of 200× shuffled-accrual nulls.
4. Placebo gate: AssetGrowth-substituted α < 50% of real α.
5. Decay placebo: randomized-date α < 50% of real α.
6. Exposure: ≥7/9 phases valid (AME ≥ 15%).
7. Cost: phase-median α > 0 at 30bps round-trip.
8. Composite integration: full strategy (m/q/v + mirage tilt) phase-median α beats current m/q/v(+pead) baseline by ≥2pp.

**Persistence mechanism (restated for the record):** Sloan accrual mispricing concentrates in the post-earnings attention window, where (a) headline-EPS traders anchor on the beat/miss, (b) the 10-Q cash flow statement requires manual EDGAR parsing + YTD-unpacking that retail and most quant shops skip, and (c) shorting fresh beats carries career/squeeze risk that delays arbitrage. The product-gate is structurally invisible to linear factor models. EOD-buildable, PIT-clean, falsifiable. Ready to code.

### Gemini
Here is the final, consolidated specification for the **Mirage Reversal** strategy. 

Opus, your fixes on the "bonded pair" event caching and the top-24 displacement/tilt mechanism perfectly bridge the gap between our sparse, event-driven signal and the system’s rigid 63-day cross-sectional architecture. This is a tight, buildable spec that exploits a genuine structural blind spot in standard linear quant models.

### 1. Thesis & Persistence Mechanism
**The Inefficiency:** Sloan's accrual anomaly, gated and amplified by recent earnings-attention. The market immediately prices headline EPS (PEAD), but takes weeks to digest the actual cash-flow quality buried in the 10-Q. 
**Persistence Mechanism:** 
1. *Attention & Latency:* Retail and algos trade the headline beat. The cash-flow reality requires parsing EDGAR and unpacking YTD cumulative figures—a manual/computational friction many skip.
2. *Arbitrage Limits:* Fading a fresh earnings beat carries massive short-term career and squeeze risk.
3. *Structural Invisibility:* Linear multi-factor models (the standard quant zoo) look for additive signals ($Z_{PEAD} + Z_{Accruals}$). They structurally cannot capture a magnitude-conditional gate where accruals only matter *because* of the recent attention shock.

### 2. Precise Signal Definitions (The Math)
**Data Layer:** EDGAR PIT fundamentals, Polygon EOD OHLCV, yfinance earnings fallback.
**Pre-filters:** S&P 500 PIT universe. Drop Financials (SIC 6000–6799). Require 20-day median Polygon dollar volume > $15M.

**Step A: The Event Cache (Bonded Pairs)**
To prevent staleness mismatch, $Z_{PEAD}$ and $Z_{Accrual}$ must be extracted from the *exact same EDGAR filing event*. 
*   **$t_e$:** EDGAR filing date (must be $\le t_{as\_of} - 2$ days).
*   **$Z_{PEAD}$:** 3-day abnormal return around $t_e$: $\frac{r_{i,[t_e, t_e+2]} - \bar{r}_{\text{universe}}}{\sigma_{i,60d} \cdot \sqrt{3}}$. Winsorize at $\pm 3$, take absolute value: $|Z_{PEAD}|$.
*   **$Z_{Accrual}$:** Extract CFO via strict PIT YTD-unpacking (e.g., Q2 CFO = Q2 YTD - Q1 YTD). Calculate $Accrual_q = \frac{NI_q - CFO_q}{(TA_q + TA_{q-1})/2}$. Cross-sectionally Z-score within GICS sector. Winsorize at $\pm 3$.

**Step B: The Conditional Math (Run on Rebalance Day $t_{as\_of}$)**
Look up the most recent bonded event within 45 days. If none, $Mirage = 0$.
*   **Decay:** $\max(0, 1 - \frac{t_{as\_of} - t_e}{45})$
*   **Mirage Raw:** $-Z_{\text{Accrual}} \times (|Z_{PEAD}| \times \text{Decay})$
*   Return standard tuple: `(ticker, raw, rank, z_score)`

### 3. Integration, Sizing & Rebalance Cadence
This integrates into the existing 63-day frozen snapshot architecture (`src/factors/composite.py`) as a **tilt and displacement mechanism**, rather than a diluted equal-weight factor.

1.  **Base Selection:** Compute the standard $m/q/v + pead$ composite. Select the top-24 names.
2.  **The Tilt:** Within the top-24, reweight the equal-weight baseline by $(1 + 0.5 \cdot Mirage_z)$, clipped to $[0.5, 1.5]$. Renormalize to 100%.
3.  **The Displacement:** Any name *outside* the top-24 with a $Mirage_z > +1.5$ displaces the lowest-ranked top-24 name. Maximum 3 displacements per rebalance. Respect existing sector caps.

### 4. Pre-Registered Validation Plan
Run via `scripts/phase_envelope.py` (9 offsets, 2021–2026). The strategy **SHIPS ONLY IF ALL 8 CONDITIONS ARE MET**:

1.  **Linear Null (A):** Beats $Z_{Accrual}$ alone by $\ge 0.3$ phase-median Sharpe.
2.  **Linear Null (B):** Beats $Z_{Accrual} + (|Z_{PEAD}| \cdot \text{Decay})$ (additive) by $\ge 0.3$ phase-median Sharpe.
3.  **Permutation Null:** Phase-median $\alpha$ > 95th percentile of 200$\times$ intra-rebalance shuffled $Z_{Accrual}$ ranks.
4.  **Placebo Gate:** Substituting $Z_{AssetGrowth}$ for $Z_{Accrual}$ yields $< 50\%$ of real $\alpha$ (proves cash-flow mismatch is the edge).
5.  **Decay Placebo:** Randomizing $t_e$ within the last 90 days yields $< 50\%$ of real $\alpha$.
6.  **Exposure Floor:** $\ge 7$ of 9 phases must have an Active Mirage Exposure (AME) $\ge 15\%$. (Report metrics on valid phases only).
7.  **Cost Survival:** Phase-median $\alpha > 0$ at 30bps round-trip (accounting for displacement turnover).
8.  **Composite Beat:** Full strategy (base + tilt/displacement) beats current baseline by $\ge 2.0\%$ phase-median $\alpha$.

### 5. Honest Verdict: Build or Wait?
**Realistic Edge:** High. The structural interaction is mathematically elegant and isolates a specific behavioral/attention anomaly that standard linear sweeps miss entirely. The EDGAR YTD-unpacking requirement provides a genuine data-engineering moat.

**Failure Modes:** 
1. *EDGAR Parsing Brittleness:* The YTD fallback logic for cash flow is notoriously dirty. Missing a prior quarter's YTD fact forces a null, which might make the signal too sparse to hit the 15% AME floor. 
2. *Turnover Drag:* Displacing 3 names every 63 days could eat the $\alpha$ via transaction costs if the Mirage names revert too quickly.

**Should we build it before the Aug 2026 review?**
**Code it, but DO NOT deploy it to the live paper account.** The live forward-paper run must remain uncontaminated to prove the baseline's OOS viability. However, building the `pead_events.parquet` cache, writing the strict YTD-unpacking logic, and running the 8-step validation suite offline is high-leverage work. If it passes the gauntlet, we have a validated, uncorrelated sleeve ready to deploy the day the baseline review concludes.

### Opus 4.7
### Opus — Final Spec Lock: The Mirage Reversal Strategy

Gemini's consolidation is correct. Here is the closing, build-ready specification — with two small but necessary tightenings I'm adding before we hand it to code.

---

### 1. Thesis & Persistence Mechanism

**Inefficiency:** Sloan's accrual anomaly, *gated and amplified* by the post-earnings attention window. Headline-EPS traders anchor on the beat/miss; the 10-Q cash-flow truth (NI − CFO) needs EDGAR parsing + YTD-unpacking that most retail/quants skip; shorting a fresh beat carries career and squeeze risk that delays arbitrage.

**Why a linear factor model cannot capture this:** the payoff is a *product* — `-Z_Accrual × |Z_PEAD| × Decay`. An additive sweep over `Z_Accrual + Z_PEAD` averages the interaction to near-zero. The non-linearity is the moat.

### 2. Signal Definitions

**Universe:** PIT S&P 500, re-resolved each rebalance (fixes the universe-freeze bias noted in the audit). Drop SIC 6000–6799. Require 20d median Polygon $-volume ≥ $15M.

**Bonded-pair event cache** (`data/pead_events.parquet`, incremental, PIT-strict):
- $t_e$ = EDGAR 10-Q/10-K filing date with `NetCashProvidedByOperatingActivities` (fallbacks: `…UsedIn…`, `…ContinuingOperations`) present. Require $t_e \le t_{\text{as\_of}} - 2$ trading days.
- $|Z_{PEAD}| = \left|\frac{r_{i,[t_e,t_e+2]} - \bar r_{\text{univ}}}{\sigma_{i,60d}\sqrt{3}}\right|$, winsorized at 3.
- $CFO_q$ via YTD-unpacking (Q1=YTD; Qn=YTD_n − YTD_{n−1}; Q4=FY − YTD_Q3). Missing prior-YTD ⇒ Mirage=0, no guessing.
- $\text{Accrual}_q = \frac{NI_q - CFO_q}{(TA_q + TA_{q-1})/2}$, z-scored **within GICS sector**, winsorized at 3.

**Rebalance-day signal:**
$$\text{Decay} = \max\!\left(0,\ 1 - \frac{t_{\text{as\_of}} - t_e}{45}\right)$$
$$\text{Mirage}_{\text{raw}} = -Z_{\text{Accrual}} \cdot |Z_{PEAD}| \cdot \text{Decay}$$

Returns standard `(ticker, raw, rank, z_score)`.

### 3. Portfolio Construction

63-day cadence, frozen snapshot, integrated as **tilt + displacement** (not rank-combined — sparse signals get crushed by tied zeros):

1. Compute base m/q/v(+pead) composite → top-24.
2. **Tilt:** within top-24, reweight by $(1 + 0.5 \cdot \text{Mirage}_z)$ clipped to $[0.5, 1.5]$, renormalize.
3. **Displace:** outside-top-24 names with $\text{Mirage}_z > +1.5$ replace weakest top-24 incumbents; ≤3 displacements/rebalance; sector cap respected; **incumbent-hysteresis bonus (0.75) still applies** to avoid churning the existing chassis.

Regime gate (200/75-SMA + VIX) and sector caps unchanged.

### 4. Pre-Registered Validation (locked, no post-hoc edits)

Run `scripts/phase_envelope.py` over 2021–2026, 9 offsets. **Ship iff ALL 8:**

1. Beats `Z_Accrual` alone by ≥0.3 phase-median Sharpe.
2. Beats `Z_Accrual + |Z_PEAD|·Decay` (additive) by ≥0.3 phase-median Sharpe. *This is the critical interaction test.*
3. Phase-median α > 95th percentile of 200× intra-rebalance shuffled-`Z_Accrual` null.
4. AssetGrowth-placebo retains <50% of α (rules out generic quality).
5. Random-date decay-placebo retains <50% of α (proves timing is the mechanism).
6. ≥7/9 phases have median AME ≥15%; metrics reported on valid phases only.
7. Phase-median α > 0 at **30bps** round-trip.
8. Full strategy beats current m/q/v(+pead) baseline by ≥2.0pp phase-median α — **measured as Jensen's α (not raw excess)**, fixing the audit's CAPM-α caveat.

Any failure ⇒ null result, written up, not deployed.

### 5. Honest Verdict

**Realistic edge:** Moderate-to-high *structurally*, uncertain *empirically*. The mechanism is named, the math is genuinely non-linear, the data moat (EDGAR YTD-unpacking) is real, and the 8-gate validation is harsh enough that survival would be informative.

**Failure modes, ranked:**
1. **Sparsity** — AME floor (15%, ≥7/9 phases) is the likeliest kill. Only ~10–20 S&P names sit in a fresh 45-day window with usable accruals at any rebalance.
2. **EDGAR tag dirtiness** — YTD fallback chain will null-out 10–20% of events; if those nulls concentrate in small-caps, we're left with a mega-cap-only signal with little dispersion.
3. **Turnover drag** — 3 displacements/rebalance + tilt rebalancing could push round-trip costs above the 30bps gate.
4. **Phase-luck masquerading as edge** — the very risk this whole spec is built to detect. Trust the gates.

**Build-or-wait recommendation:** **Build the factor + run the validation suite offline NOW. Do NOT touch the live paper account.** The 2026-05-27 forward run is sacred — contaminating it destroys the un-overfittable test we waited 90 days to start. But coding `mirage.py`, the bonded-pair event cache, and the YTD-unpacker is pure infrastructure work that compounds regardless of outcome. If Mirage clears all 8 gates by August, we have a validated, mechanistically-justified sleeve ready to deploy the day the baseline review concludes. If it fails, we've learned exactly *which* gate killed it — and that's a far more valuable artifact than another fitted backtest number.

**Spec locked. Ready to code.**
