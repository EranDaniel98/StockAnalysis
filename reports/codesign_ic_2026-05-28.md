# Strategy Debate — 2026-05-28

- **Opus model:** `claude-opus-4-7`
- **Gemini model:** `gemini-3.1-pro-preview`
- **Rounds:** 6 · **Opener:** Gemini
- **Format:** collaborative co-design of a new strategy
- **Seed:** `scripts/debate_seed_ic_leaderboard.md`

---

### Gemini
This is an excellent starting point. Since the lab results show multiplicative interactions are a dead end and momentum/low-vol carry heavy regime risk, our path forward is clear: **we must build an additive composite of sign-stable, fundamentally rooted anomalies.** 

Quality and PEAD are our proven anchors (100% sign consistency). To lift the IC and breadth of this core without introducing regime fragility, I propose we expand the definition of "Quality" beyond static margins and introduce **Capital Discipline** and **Fundamental Momentum**. 

Here is v0 of the strategy, relying strictly on the EDGAR PIT and yfinance earnings data.

### The Core Inefficiency
The market systematically underreacts to slow-moving fundamental improvements (Fundamental Momentum/PEAD) and overestimates the future returns of "empire-building" firms that aggressively expand their asset base (Asset Growth anomaly). By combining clean profitability with capital discipline and positive earnings trajectory, we target firms generating cash efficiently without diluting ROIC through over-expansion. 

### Concrete Signals (The "Q-Growth" Composite)
Let's add these three specific signals to `factor_lab.py` to test alongside PEAD:

1. **Gross Profitability to Assets (GPA - Novy-Marx)**
   * **Thesis:** Higher up the income statement than ROE/ROA, making it cleaner and less susceptible to accrual/leverage distortions. 
   * **Formula:** `(gross_margin * revenue) / total_assets` (using the most recent PIT filing).
   * **Sign:** Positive.
   * **Note:** This replaces our generic "quality" factor with a proven, robust academic specification.

2. **Asset Growth (Cooper-Gulen-Schill)**
   * **Thesis:** Companies that rapidly grow total assets historically underperform (empire building, over-investment). 
   * **Formula:** `(total_assets_t / total_assets_{t-4q}) - 1`.
   * **Sign:** Negative (we rank descending, preferring *low* or negative asset growth).
   * **Lookback:** Current PIT filing vs. the PIT filing from ~1 year prior.

3. **Fundamental Trajectory (Δ Profitability)**
   * **Thesis:** PEAD captures the *event* underreaction (the surprise). Fundamental trajectory captures the slow-moving *trend* underreaction.
   * **Formula:** `operating_margin_t - operating_margin_{t-4q}`.
   * **Sign:** Positive.

### The Combination Method: Sector-Neutral Z-Score Sum
Since interactions fail, we use an additive cross-sectional rank. However, standard equal-weight ranks can be drowned out by sector biases (e.g., Tech dominates GPA, Financials distort Asset Growth). 

* **Method:** For each of the 4 signals (GPA, -Asset_Growth, ΔMargin, PEAD), we compute a cross-sectional Z-score *within each sector* (using the `sector` field from EDGAR). 
* **Composite:** `Z_composite = Z_sector(GPA) + Z_sector(-Asset_Growth) + Z_sector(ΔMargin) + Z_sector(PEAD)`.
* **Execution:** Rank the S&P 500 universe on `Z_composite`, hold the top 24, rebalance every 63 days.

### Over to you (Opus):
1. **Refinement:** Do you agree with sector-neutralizing the Z-scores before summing, or should we winsorize/rank-normalize differently to handle EDGAR outliers? 
2. **Risk/Validation:** How exactly should we define the permutation/null baseline in `factor_lab.py` to prove this composite actually lifts IC above the standalone PEAD/Quality legs across all 8 regime-cells, given the ±20-30pp phase-luck envelope?

### Opus 4.7
### Opus

Strong v0. I'll lock the spec where you have it right, fix two things that will bite us, and pin down the validation so we can actually tell signal from luck.

### Fixes to the signal layer

**1. Sector-neutralize ranks, not z-scores.** EDGAR raw fields are heavy-tailed (asset growth can be +400% post-acquisition; GPA explodes for asset-light software). Z-scores within a 10-name Utilities bucket are meaningless. Use:
- Cross-sectional **rank within sector → normalize to [-0.5, +0.5]** (i.e., `(rank-1)/(n-1) - 0.5`).
- Sum the four sector-demeaned ranks. This is winsorization-by-construction and handles small sectors gracefully.
- Drop sectors with n<8 to global rank (Real Estate, Materials sometimes thin in S&P PIT).

**2. Asset Growth needs a denominator floor + log.** Use `log(total_assets_t / total_assets_{t-4q})` with a guard for `t-4q` missing → fall back to `t-3q` annualized, else drop the name from that leg (don't zero it — that biases toward zero-growth). Sign: short high-growth, i.e., rank ascending.

**3. ΔMargin needs scaling.** `operating_margin_t − operating_margin_{t-4q}` is in percentage points; a 5pp margin gain for a 2%-margin retailer ≠ a 5pp gain for a 40%-margin software co. Use **relative**: `(om_t − om_{t-4q}) / (|om_{t-4q}| + 0.05)`. The 0.05 floor prevents blowups near zero margins.

**4. Add a 4th leg you skipped: Earnings-Revision Drift via realized growth acceleration.** 
- Formula: `earnings_growth_yoy_t − earnings_growth_yoy_{t-1q}` (acceleration, not level).
- This is the closest PIT proxy we have to analyst revisions (which we don't have). Cheap to add, sign-stable thesis, orthogonal to PEAD (which is price-around-event).

So the composite becomes **5 legs**: GPA, −AssetGrowth, ΔOpMargin (scaled), ΔEarningsGrowth, PEAD — all sector-rank-neutralized, equal-weight sum.

### Position sizing & execution
- **Top 24, 63d rebalance, equal weight** — keep, matches current infra.
- **Sector cap 6 names** (already in `config/settings.yaml`).
- **Hysteresis 0.75 carry bonus** — keep, it's worth +4.31pp.
- **Regime gate:** keep the existing 200/75 SMA + VIX gate, but I want to flag this is *separate* from whether the composite has alpha. Test the composite **ungated** in factor_lab first; only add the gate at portfolio-construction stage.

### Validation plan (the non-negotiable part)

This is where most "composite lift" claims die. Pre-register:

1. **Per-leg IC first.** Each new leg (GPA, AG, ΔOM, ΔEG) must clear `|IC| > 0.01 AND permutation p<0.05 in ≥4/8 regime-cells AND sign_consistency ≥ 75%` to enter the composite. No exceptions, no "but it helps in combination."

2. **Composite lift test.** The 5-leg composite must beat the **best single leg's IC by ≥30%** AND beat **equal-weight (quality+PEAD)** on:
   - Mean IC across 8 cells
   - %-cells positive (target ≥6/8)
   - IC stability (std across cells)

3. **Permutation null for the COMPOSITE.** Shuffle forward returns within each rebalance date 1000×, recompute composite IC. Real IC must exceed 95th percentile of null in ≥6/8 cells. This controls for the multi-leg fishing.

4. **Phase-averaged backtest.** Run `phase_envelope.py` across all 9 offsets. Decision rule: **median CAPM-α (not raw excess) > 0 AND ≥6/9 phases positive**. Not "best phase looks great."

5. **Kill criterion, pre-registered:** if composite median CAPM-α < quality-only median by >2pp, we ship quality+PEAD only and abandon the expansion.

### Over to you
- Agree on the 5th leg (ΔEarningsGrowth) and the rank-within-sector vs z-score fix?
- Should we weight legs by their **standalone IC** (Grinold) or stay equal-weight given small-sample IC noise? I lean equal-weight — IC-weighting overfits at n=8 cells.

### Gemini
### Gemini

I completely agree with the sector-neutral rank normalization `[-0.5, +0.5]`. EDGAR outliers are notorious (e.g., a software firm's GPA or an acquisition-driven asset spike), and ranks natively immunize the composite. I also strongly agree on **equal-weighting the legs**. In small-sample regimes (n=8 cells), IC-weighting is a classic overfitting trap; equal-weighting mathematically shrinks off-diagonal noise to zero, which is optimal for out-of-sample robustness.

I accept the 5th leg (ΔEarningsGrowth). However, because YoY growth metrics explode when the base is near zero, we must apply the same fallback logic as Asset Growth: if `t-1q` is missing or the base is mathematically invalid, assign the stock a neutral score (0.0 in the normalized rank) for that leg rather than dropping it, preserving its scores on the other 4 legs.

Here is how we finalize the spec, addressing the remaining gaps in the dossier:

### 1. Rescuing the "Value" Anchor (The 6th Leg)
We dropped the Value factor because of the known EPS-duration bug (`compute_eps_ttm`). But a pure Q-Growth composite without a price anchor risks drifting into expensive mega-cap tech, exacerbating the regime fragility we are trying to fix. 

We can rescue Value using strictly clean, non-buggy EDGAR fields: **Free Cash Flow Yield**. 
* **Formula:** `free_cash_flow / market_cap` (both fields are explicitly available in the PIT dossier).
* **Sign:** Positive (rank ascending, higher yield is better).
* **Why:** It bypasses the net income/EPS duration bug entirely, anchors the growth/momentum legs to a hard cash valuation, and natively penalizes overvalued empire-builders. This makes it a 6-leg composite: GPA, −AssetGrowth, ΔOpMargin, ΔEarningsGrowth, PEAD, FCF Yield.

### 2. Upgrading Execution: Inverse-Volatility Sizing
The dossier explicitly flags: *"no covariance/vol-aware sizing yet"* and notes that concentration mechanically raised portfolio Beta (0.694 → 0.884), meaning 70% of the excess drawdown was just beta, not negative skill.

Equal-weighting the top 24 names is leaving free Sharpe on the table. We must implement **Inverse Volatility sizing**.
* **Method:** For the 24 selected names, compute the 60-day trailing daily return volatility (`60d_vol`).
* **Weighting:** `w_i = (1 / 60d_vol_i) / SUM(1 / 60d_vol_j)`.
* **Impact:** This is computable entirely on the Polygon EOD data layer. It natively down-weights high-beta momentum names and up-weights stable quality names, directly compressing the beta-driven drawdowns that hurt the previous iteration.

### 3. Finalizing the Validation Lock
Your pre-registered validation plan is airtight. To ensure we don't trip over the "raw excess return is meaningless" caveat again, I am adding one strict addendum to Step 4:

* **CAPM-α Measurement:** The `phase_envelope.py` script *must* regress the portfolio's daily returns against SPY daily returns to extract Beta and Jensen's Alpha over the 63-day forward windows. 
* **The Final Hurdle:** The phase-averaged median CAPM-α must be **> +3.0% annualized** (to clear the 50bps cost hurdle with margin of safety), with ≥6/9 phases positive.

We now have a fully specified, 6-leg, sector-neutralized, inverse-volatility-sized composite. No new data required. Ready to run `factor_lab.py`. Agree with FCF Yield and InvVol sizing as the final pieces?

### Opus 4.7
### Opus

Agree on FCF Yield and InvVol — both are clean wins. Two refinements, then I want to lock the spec and pre-register.

### Refinements

**1. FCF Yield needs a sign guard.** `free_cash_flow / market_cap` is fine for positive FCF, but ~15% of S&P names have negative TTM FCF in any given quarter (especially post-COVID growth names). Negative FCF/MC ranks below zero-FCF, which is what we want directionally, but the *magnitude* is meaningless (a -$10B FCF on a $50B mcap shouldn't dominate). Solution: rank-based, not magnitude-based, which our `[-0.5, +0.5]` sector-rank normalization already handles. **No change needed — flagging that this is why we chose ranks over z-scores.** Also: use **TTM FCF** (sum of last 4 quarterly FCF values from the EDGAR sidecar), not the latest single quarter, to avoid seasonal noise.

**2. InvVol needs a cap and a floor.** Raw `1/vol` weighting can put 15% in a single ultra-low-vol utility and create stealth concentration. Constraints:
- **Floor vol at the 10th percentile** of the selection's vol distribution (prevents one stock dominating).
- **Cap any single weight at 8%** (2× equal-weight); redistribute overflow pro-rata.
- **Sector cap stays at 6 names** but also add a **sector weight cap of 30%** post-InvVol (since vol-weighting can concentrate into low-vol sectors like Staples/Utilities).

This keeps the beta-compression benefit without trading one concentration risk for another.

### One missing piece: exit logic between rebalances

We're rebalancing every 63 days. With a 6-leg fundamental composite, individual names can deteriorate fast (earnings miss, guidance cut) inside that window. Pure calendar rebalance is leaving money on the floor. Add a **minimal intra-period exit rule**:

- **Earnings-event exit:** If a held name reports earnings with surprise < -5% (yfinance field), exit at next open. Replaces with #25 from last ranking.
- **Stop-loss:** −20% from entry, hard stop. (Not a trailing stop — we want to preserve mean reversion in the composite names.)
- **No discretionary additions.** Only the two rules above. Everything else waits for the 63d rebalance.

This is cheap to implement and addresses the "regime gate too slow for crashes" caveat without abandoning the cadence.

### Pre-registration lock (commit before running)

Writing this down so we can't move goalposts:

| Test | Threshold | Kill if fails |
|---|---|---|
| Each new leg standalone | \|IC\|>0.01, p<0.05 in ≥4/8 cells, sign_cons ≥75% | Drop that leg only |
| 6-leg composite mean IC | ≥1.3× best single leg | Revert to quality+PEAD only |
| Composite %-cells positive | ≥6/8 | Revert to quality+PEAD only |
| Permutation null (composite) | Real IC > 95th pct null in ≥6/8 cells | Abandon composite |
| Phase-averaged median CAPM-α (annualized) | > +3.0% | Abandon |
| Phases positive | ≥6/9 | Abandon |
| Median CAPM-α vs quality-only | > -2pp | Revert to quality+PEAD |

**Important:** run the IC/permutation tests on the **ungated** composite (pure factor signal), then run the phase-averaged CAPM-α on the **gated+InvVol-sized portfolio** (the actual tradeable thing). Don't conflate "is there factor IC?" with "does the portfolio earn alpha?" — those are separate questions and the gate/sizing affect only the second.

### Final spec (locked)

- **Universe:** PIT S&P 500, re-resolved per rebalance (fixes universe-freeze bias).
- **Signals:** 6 legs — GPA, −log(AssetGrowth_4q), ΔOpMargin (scaled), ΔEarningsGrowth_yoy, PEAD, FCF Yield (TTM).
- **Normalization:** sector-rank → `[-0.5, +0.5]`; fallback to global rank if sector n<8; missing leg → 0.0.
- **Composite:** equal-weight sum.
- **Selection:** top 24 by composite.
- **Sizing:** InvVol(60d), vol floor at 10th pct, weight cap 8%, sector weight cap 30%.
- **Rebalance:** 63d, hysteresis 0.75 carry bonus to incumbents.
- **Regime gate:** existing 200/75 SMA + VIX.
- **Intra-period exits:** earnings surprise < -5% OR -20% stop.

Ship it to `factor_lab.py`. Agreed?

### Gemini
Agreed. The intra-period exit rules and InvVol constraints perfectly plug the remaining crash-latency and concentration gaps. Here is the final, locked specification for the **Q-Growth FCF Composite**.

### 1. Thesis & Inefficiency
The strategy exploits a dual behavioral inefficiency: the market systematically underreacts to slow-moving fundamental momentum (profitability trends, earnings acceleration) and overvalues "empire-building" (aggressive asset expansion without cash-flow backing). By anchoring to clean Free Cash Flow and Gross Profitability, we bypass the known EDGAR EPS-duration bug while structurally avoiding expensive, low-quality beta.

### 2. Signal Definitions & Normalization
**Data:** Polygon EOD (OHLCV), EDGAR PIT (fundamentals/accruals), yfinance (earnings).
**Normalization:** For each leg, rank cross-sectionally *within sector* (if sector $n \ge 8$, else global), then scale to `[-0.5, +0.5]`. Missing data = `0.0`. 
**Composite:** Equal-weight sum of the 6 normalized legs.

1.  **GPA (Novy-Marx):** `(gross_margin * revenue) / total_assets` (Rank ascending: higher is better).
2.  **Asset Growth (Cooper-Gulen-Schill):** `-log(total_assets_t / total_assets_{t-4q})` (Fallback to 3q annualized. Rank ascending: lower growth is better).
3.  **$\Delta$ OpMargin:** `(om_t - om_{t-4q}) / (|om_{t-4q}| + 0.05)` (Rank ascending).
4.  **$\Delta$ Earnings Growth:** `earnings_growth_yoy_t - earnings_growth_yoy_{t-1q}` (Rank ascending).
5.  **PEAD:** Latest earnings surprise % via yfinance (Rank ascending).
6.  **FCF Yield:** `sum(fcf_last_4q) / market_cap` (Rank ascending).

### 3. Execution, Sizing & Risk
*   **Universe:** PIT S&P 500 (re-resolved at each rebalance to eliminate freeze bias).
*   **Entry/Rebalance:** Top 24 names by composite score. 63-day cadence. 0.75 score hysteresis bonus for incumbents.
*   **Sizing (InvVol):** Weight $\propto 1 / \text{60d\_vol}$. Floor volatility at the 10th percentile of the 24 selected names. Cap single stock weight at 8%; cap sector weight at 30%.
*   **Regime Gate:** Apply existing 200/75 SMA + VIX gate at the portfolio level.
*   **Intra-Period Exits:** Hard stop at -20% from entry, OR exit at next open if a held name reports an earnings surprise $< -5\%$. Replace with the #25 name from the last ranking.

### 4. Pre-Registered Validation Plan
Run `factor_lab.py` (ungated) and `phase_envelope.py` (gated/sized). Kill the strategy if it fails *any* of these hurdles:
*   **Leg-level:** $|IC| > 0.01$, $p < 0.05$ in $\ge 4/8$ cells, sign consistency $\ge 75\%$.
*   **Composite IC:** Mean IC $\ge 1.3\times$ the best single leg, positive in $\ge 6/8$ cells.
*   **Permutation Null:** Composite IC must exceed the 95th percentile of the shuffled-return null in $\ge 6/8$ cells.
*   **Phase-Averaged CAPM-$\alpha$:** Median annualized CAPM-$\alpha > +3.0\%$, positive in $\ge 6/9$ phase offsets.

### 5. Honest Verdict & Next Steps
**Realistic Edge:** This is highly robust. By combining orthogonal, sign-stable anomalies (Quality + Momentum + PEAD + Asset Growth) and neutralizing sector/beta distortions via ranks and InvVol, we maximize the probability of surviving the $\pm 20$-30pp phase-luck envelope.

**Failure Modes:** The primary risk is a sudden rotation into deep-value/junk (e.g., late 2020), where high-quality cash-compounders lag severely.

**Deployment Verdict:** Do **not** deploy this to Alpaca yet. The current live paper run is midway through its out-of-sample validation (ending 2026-08-27). Swapping strategies mid-validation is a fatal methodological error. **Action:** Code the signals, run the pre-registered offline validation today, and if it passes the hurdles, queue it as the primary candidate for the post-August 27 system upgrade.

### Opus 4.7
### Opus — Closing Turn: Final Locked Specification

## Strategy: **Q-Growth FCF Composite (QGF-6)**

### 1. Thesis & Exploited Inefficiency

Two persistent behavioral biases, both documented in the academic literature and — critically — both expressible on our EDGAR PIT + Polygon EOD data layer:

1. **Underreaction to fundamental trajectory.** Markets price the *level* of profitability quickly but underreact to the *trend* (Δ margin, earnings acceleration, post-announcement drift). The drift compounds over 1-3 quarters — well-matched to our 63d cadence.
2. **Overreaction to empire-building.** Aggressive asset growth predicts negative returns (Cooper-Gulen-Schill); the market extrapolates investment as growth signal and ignores the ROIC dilution.

Anchoring both with **FCF Yield** (clean, bypasses the known EPS-duration bug) keeps the book from drifting into expensive mega-cap quality — the exact failure mode that made the current m/q/v composite a bull-laggard.

### 2. Signal Definitions (6 legs, equal-weight)

All legs computed PIT, sector-rank-normalized to `[-0.5, +0.5]` (global rank if sector n<8), missing → 0.0, equal-weight sum.

| # | Leg | Formula | Sign |
|---|---|---|---|
| 1 | GPA | `(gross_margin · revenue) / total_assets` | + |
| 2 | Asset Growth | `−log(total_assets_t / total_assets_{t−4q})`, fallback 3q-annualized | + (i.e., low growth wins) |
| 3 | ΔOpMargin | `(om_t − om_{t−4q}) / (|om_{t−4q}| + 0.05)` | + |
| 4 | ΔEarningsGrowth | `earnings_growth_yoy_t − earnings_growth_yoy_{t−1q}` | + |
| 5 | PEAD | latest yfinance surprise % | + |
| 6 | FCF Yield (TTM) | `sum(fcf_last_4q) / market_cap` | + |

### 3. Portfolio Construction

- **Universe:** PIT S&P 500, **re-resolved each rebalance** (fixes universe-freeze bias).
- **Selection:** top 24 by composite score, with 0.75 carry bonus to incumbents (hysteresis).
- **Sizing:** InvVol on 60d daily-return vol; vol floor at 10th pct of selection; weight cap 8%; sector weight cap 30%; sector name cap 6.
- **Rebalance:** 63 trading days.
- **Regime gate:** existing 200/75 SMA + VIX (applied only at portfolio stage, not in IC tests).
- **Intra-period exits:** (a) earnings surprise < −5% → exit next open; (b) −20% hard stop from entry. Replace with name #25 from prior ranking. No other discretionary actions.

### 4. Pre-Registered Validation (commit before code)

**Stage A — Ungated factor IC (`factor_lab.py`):**
- Each new leg standalone: |IC|>0.01, permutation p<0.05 in ≥4/8 regime-cells, sign consistency ≥75%. Fail → drop that leg only.
- 6-leg composite mean IC ≥ 1.3× best single leg AND positive in ≥6/8 cells. Fail → revert to quality+PEAD baseline.
- Composite permutation null (1000× shuffled forward returns within rebalance dates): real IC > 95th pct of null in ≥6/8 cells. Fail → abandon composite.

**Stage B — Gated/sized portfolio (`phase_envelope.py`, all 9 offsets):**
- Median annualized **Jensen's α (regress portfolio daily returns on SPY)** > +3.0%. Fail → abandon.
- ≥6/9 phases CAPM-α positive. Fail → abandon.
- Median CAPM-α > (quality+PEAD-only median) − 2pp. Fail → revert to quality+PEAD.

**Decision rule:** ship only if Stage A and Stage B both pass. Pre-registration locked in this thread; no goalpost moves.

### 5. Honest Verdict

**Realistic edge:** modestly positive expected value. We are stacking 4 sign-stable, academically-documented anomalies (GPA, asset growth, PEAD, fundamental momentum) on top of an FCF anchor, normalized to neutralize sector/heavy-tail noise, sized to compress beta. Each leg is small (~0.015 IC); the bet is that *additive combination of orthogonal small edges* clears the cost hurdle where any single leg wouldn't. This is the correct shape — diversification of weak signals beats concentration in any one.

**Failure modes, ranked:**
1. **Junk rallies** (late-2020-style deep-value/low-quality melt-up): quality + asset-discipline tilts lag hard. Regime gate doesn't help — it's long-only in an up-tape.
2. **IC stays at ~0.015 even for the composite** because the legs aren't as orthogonal as we hope (GPA, ΔOM, ΔEG all touch profitability). Plausible — and the 1.3× lift hurdle is designed to catch exactly this.
3. **Phase-luck still dominates.** Even with 9 phases × 6/8 cells × permutation null, the 2yr/63d window's ±20-30pp envelope means a "passing" result could still be a 1-in-20 fluke. Mitigation: the multi-stage AND-gated hurdles make the joint false-positive rate substantially below 5%.
4. **InvVol concentration into Staples/Utilities** during risk-off — the 30% sector cap is the backstop.

**Build before 2026-08-27?** **Yes — code and validate offline; do NOT deploy.** The live paper run is the un-overfittable OOS test of the *current* config; swapping mid-stream destroys that evidence. But running QGF-6 through `factor_lab.py` + `phase_envelope.py` *offline* costs nothing and prejudges nothing. If it clears all pre-registered hurdles, it's queued as the primary candidate for the post-Aug-27 upgrade. If it fails, we learned cheaply and the live run continues uncontaminated. Either outcome is a win.

Ship to `factor_lab.py`.
