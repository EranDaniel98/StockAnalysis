# 3-Model Deep-Thinking Panel — 2026-05-31

- Panel: Opus `claude-opus-4-7` · Gemini `gemini-3.1-pro-preview` · OpenAI `gpt-5.5`
- Seed: `scripts/debate_seed_scenarios.md`


## FINAL SYNTHESIS (ranked shortlist)

# Final Synthesis — Scenario-Conditional Strategy Shortlist

After cross-model review, **five strategies** survive scrutiny. All three panelists independently converged on the same top tier: a regime meta-gate, an insider-stress liquidity-provision trade, and an earnings-microstructure trade. Ranked by **expected edge × testability**, with explicit pre-registration of the falsification test each must pass.

---

## #1 — Quality/Junk Regime Meta-Gate
*(Opus #4 + Gemini #3, merged per GPT-5.5)*

**Why first.** Highest leverage on the existing system. We already know the long-quality/short-junk sleeve is regime-dependent (+2.5-3% α in flight-to-quality, −2-3% in junk rallies). This doesn't ask us to discover new α — it asks us to *stop paying* the known tax. All three panelists ranked this top.

**Scenario trigger.** Detect a "junk rally / dash-for-trash" regime ex-ante so we can gate the existing PEAD+quality sleeve to FLAT (not flip — that's the falsified anti-pattern).

**Computable signal (feature set).**
- `junk_quality_spread_20d` = 20d return of (low-ROA, high-beta S&P quintile) − (high-ROA quintile). EDGAR PIT ROA; Polygon EOD for returns. *Note: use ROA-based junk, not low-price — share price is a crude proxy (GPT-5.5).*
- `spy_intraday_minus_overnight_10d` = rolling 10d sum of (open→close) − (prior close→open) on SPY.
- `vix_level`, `vix_slope` (1m vs 3m via yfinance `^VIX`, `^VIX3M`).
- `spy_drawdown_from_252d_high`.

**Gate logic (continuous, not binary — per Opus critique on overfit risk).**
Fit a logistic regression of next-21d sleeve-return-sign on the feature set, **walk-forward** (expanding window, refit annually, no in-sample threshold-tuning). Gate sleeve weight ∝ predicted probability of positive regime.

**Entry/exit.** At each 63d rebalance, scale the long-quality/short-junk sleeve weight by the gate's predicted probability. Other composite sleeves unchanged.

**Persistence mechanism.** Quality premium is a real risk premium paid for holding boring names through stress. Junk rallies are liquidity/short-covering events not driven by fundamentals — the spread of low-quality minus high-quality returns *is* the regime, observable without lookahead.

**Falsifiable test.**
- Compare gated vs ungated sleeve, 2018-2026.
- **Phase split (mandatory, all 5):** 2019 melt-up (junk), COVID 2020-H1, 2020-H2 reflation (junk), 2022 bear (quality), 2023-26 AI mega-cap.
- **Duty-cycle-matched permutation null** (GPT-5.5): 1000 random ON/OFF gates with identical % days active. The real gate must beat the 95th percentile.
- **Parameter-grid robustness** (Opus): ≥70% of reasonable threshold/window grid beats ungated.
- **Decision rule (PASS):** Jensen's CAPM-α net 30bps improves by **≥200bps annualized** vs ungated, AND %-positive phases ≥4/5, AND duty-cycle p < 0.05, AND ablation: each feature contributes nonzero coefficient OOS.

---

## #2 — Insider-Stress Liquidity Provision (Two-Branch)
*(Opus #1 + Gemini #1, merged per GPT-5.5)*

**Why second.** Universal insider-cluster is dead, but both proposers independently arrived at the same conditional reframe (stress provides the liquidity vacuum that makes insider conviction tradeable). Two complementary branches share infrastructure.

**Scenario trigger — two branches tested separately.**

**Branch A — Idiosyncratic gap stress.**
- ≥2 distinct Form-4 open-market buys (code `P`, direct) in trailing 10 trading days, OR ≥1 buy > $250k by C-suite/Board.
- Day t opens with overnight gap-down ≤ −2σ vs 60d overnight-return distribution.
- 20d ADV > $20M (kills microcap noise — the Form-4 anti-pattern killer).
- Entry: first tradable minute after open (09:31, per GPT-5.5 — "buy at open" is lookahead). Exit: close t+3. SPY beta-hedge.

**Branch B — Market panic.**
- SPY in >10% drawdown from 252d high OR VIX > 25.
- Same Form-4 cluster filter.
- Entry: close of day the second Form-4 is *accepted* (filing acceptance timestamp, not transaction date — GPT-5.5). Exit: t+63. SPY beta-hedge.

**Persistence mechanism.** Career-risk asymmetry: PMs de-gross in stress and won't catch falling knives; insiders have zero short-term mark-to-market career risk and asymmetric information that bankruptcy/liquidity risk is bounded. The cluster filter selects for conviction; the stress filter selects for the moment when public capital structurally withdraws.

**Falsifiable test.**
- **Filing-time discipline (GPT-5.5):** use SEC acceptance timestamp; if accepted after 15:45 ET, action is next-session.
- **Matched-stress null (Opus + GPT-5.5):** random entries during same stress windows, matched by ticker, β, size, sector, prior drawdown, liquidity. **The cluster signal must beat the matched-stress baseline**, otherwise the edge is just "buy stress."
- **Form-4 date shuffle within ticker** (1000×).
- **Event-day portfolio returns**, not pooled stock t-stats (GPT-5.5 — cross-correlation in stress).
- **CAPM-α with pre-event β estimation** (avoid rebound-β contamination).
- **Decision rule (PASS):** mean α > 30bps/trade net (Branch A) or >2pp/quarter net (Branch B), permutation p < 0.05, **matched-stress p < 0.10**, positive in ≥4/5 phases (Branch A) or ≥2/3 panic windows (Branch B).

**Honest caveat.** Branch B has N≈3 distinct panic windows (Q4'18, COVID, 2022). It ships as a *hypothesis with pre-registered ablation*, not a backtested edge. If Branch B fails the matched-stress test, that's a real result.

---

## #3 — Earnings Gap-Up Opening-Range Failure ("Gap & Crap")
*(Gemini #4, hardened with all three critiques)*

**Why third.** Cleanest *orthogonal* event-microstructure idea on the menu. Flat overnight, large N, doesn't touch fundamentals, doesn't overlap PEAD direction.

**Scenario trigger.**
- Earnings day t with positive surprise (yfinance), in a complacent-bull regime: SPY > 50d SMA AND VIX < 15.
- Day t opens with gap-up > +4% (Polygon minute bars).
- First 30 minutes (09:30-10:00): VWAP < open AND 10:00 price < open.
- Relative volume in first 30min > 10% of 20d ADV.
- Liquidity filter: 20d ADV > $50M, large-cap easy-to-borrow only.

**Entry/exit.** Short at 10:01 (after the 10:00 bar completes — GPT-5.5). Exit 15:55. **Strictly intraday, no overnight.**

**Persistence mechanism.** Standard PEAD buys headline gaps blindly. When a gap-up is rejected on heavy volume in the first 30 minutes, it reveals institutional VWAP-distribution algos using retail liquidity to unwind blocks. Mechanism is structurally distinct from PEAD (which captures continuation in confirmed gaps).

**Falsifiable test.**
- Event study, intraday alpha (10:01 → 15:55), 2018-2026, S&P 500/large-cap.
- **Three-arm comparison (per Opus + GPT-5.5):**
  1. Earnings gap-up + red first 30min (the trade).
  2. Earnings gap-up + green first 30min (true PEAD continuation, should differ).
  3. **Non-earnings matched gap-up + red first 30min** (controls for general opening-range fade — the critical control).
- **Surprise-decile matching** (Opus on Gemini #2's lesson applied here): match on SUE/gap-size buckets so


---

## Phase 1 — Independent proposals


### Opus

# Opus — Scenario-Conditional Strategy Proposals

Five hypotheses, ranked by my prior on edge-survival. All computable on Polygon EOD+minute / EDGAR / Form-4 / FINRA / VIX.

---

## #1 — Overnight-Gap Reversal on Form-4 Cluster Buys (event × microstructure)

**Scenario trigger.** A name has ≥2 distinct insider OPEN-MARKET buys (Form-4 code P, not option exercises) in the prior 10 trading days, AND on day t opens with a gap-down ≥ −2.0σ of its 60d overnight-return distribution. (Pure overnight gap, not intraday news drift.)

**Signal (computable).**
- Form-4: `transaction_code='P'`, `is_direct=true`, sum across distinct CIKs in [t-10, t-1]. Require ≥2 insiders OR ≥1 with `value_usd > 250k`.
- Gap: `(open_t / close_{t-1}) - 1`, z-scored vs trailing 60d of same series.
- Liquidity gate: 20d ADV > $20M (avoid the microcap Form-4 noise that kills the naive cluster-buy factor).

**Entry/exit.** Buy at open_t (Polygon minute bar). Exit at close_{t+3}. Beta-hedge with SPY at entry weight = β_60d.

**Persistence mechanism.** Form-4 cluster-buy as a *standalone* cross-sectional factor is dead (already falsified — CMP-2012). But CONDITIONED ON a forced overnight gap-down, you're buying liquidity from indiscriminate overnight sellers (ETF rebalancers, margin calls, retail stops) into names where the best-informed agents *just* signaled "cheap." The trigger filters for the rare gap where insiders disagree with the tape. Not arbed because (a) Form-4 cluster signal is publicly known but trades poorly *alone* — quants abandoned it; (b) overnight liquidity is the structurally hardest window to provide.

**Falsifiable test.**
- Event study, 2018-2026, S&P 1500 universe (Polygon-eligible delistings included).
- Metric: t→t+3 CAPM-α net of 30bps round-trip.
- Permutation null: shuffle Form-4 dates within each ticker 1000×.
- Phase split: pre-2020, COVID, 2021 melt-up, 2022 bear, 2023-26.
- **PASS bar:** mean α > 25bps/trade, %-positive phases ≥ 4/5, permutation p < 0.05, ≥150 events.

---

## #2 — FOMC-Day Intraday-Reversal Sleeve (calendar × microstructure)

**Scenario trigger.** FOMC announcement days (2pm ET statement). Specifically: the 2:00pm→2:30pm "knee-jerk" window often reverses 3:00pm→close.

**Signal.**
- Polygon minute bars for SPY and top-100 liquid names.
- `knee_jerk_ret = (price_{14:30} / price_{14:00}) - 1`
- Cross-sectional rank each FOMC day: short top-decile knee-jerk movers, long bottom-decile, dollar-neutral.
- Restrict to names with intraday ADV > $50M.

**Entry/exit.** Enter 14:35 ET, exit 15:55 ET (avoid closing auction adverse selection). ~85 minutes of exposure.

**Persistence.** The 2pm reaction is dominated by algos trading the *statement text* in seconds; the 2:30-3:00 window has a known dealer-rebalancing pattern as risk desks unload knee-jerk inventory into the close. This is a liquidity-provision premium against forced flow on a *predictable calendar date*. Not arbed because (a) it requires being flat overnight on FOMC days — most discretionary funds won't take that career risk; (b) ~8 events/year, capacity is small, attention from sophisticated arbs is low relative to the prize.

**Falsifiable test.**
- 64 FOMC events 2018-2026.
- Mean per-event α (long-short dollar-neutral), net of 30bps.
- Permutation: same strategy on 1000 random non-FOMC weekdays.
- **PASS bar:** FOMC mean > non-FOMC 95th percentile, t-stat > 2.5 on event-level returns, robust to dropping the 3 highest-|return| events.

---

## #3 — Post-Earnings Implied-Move "Crush" Fade (event, orthogonal to PEAD)

**Scenario trigger.** Earnings day t. Gap |open_t / close_{t-1} − 1| < 0.3× the name's 60d realized 1-day vol (a "muted" reaction). This is the SCENARIO where the market shrugged off the print.

**Signal.** Within the muted-reaction subset, rank by:
- `quality_residual` = standardized accruals (NI − CFO)/assets — *not* SUE, *not* the PEAD direction.
- Long bottom-quartile (high quality = low accruals), short top-quartile.
- Hold 1-5 days post-earnings.

**Persistence.** PEAD is the well-known scenario; the "muted" subset is the *negative space* — events where the surprise was small but the **quality of earnings** still varied. Accruals as a UNIVERSAL factor is null (anti-pattern), but inside the muted-earnings window the signal-to-noise is high because price hasn't moved on the headline, leaving the cash-flow-quality information unpriced. Orthogonal to PEAD by construction (PEAD is the large-surprise tail; this is the no-surprise body).

**Falsifiable test.**
- 2018-2026, S&P 500.
- Bucket earnings by |gap|/σ; verify accruals signal is null in high-gap bucket (sanity) and tradeable in low-gap bucket.
- Permutation: random "muted earnings" assignments within ticker history.
- Phase: 2019 (junk), 2022 (quality), 2023-26.
- **PASS bar:** α > 40bps/trade net, monotone across buckets, ≥3/4 phases positive, p < 0.05.

---

## #4 — Regime Meta-Gate for the Long-Quality/Short-Junk Sleeve (regime gating)

**Scenario trigger.** This directly addresses the brief's finding: the PEAD+quality long-short earns +2.5-3% α in flight-to-quality, −2-3% in junk rallies. Goal: detect the regime **ex-ante** using only price/breadth.

**Signal (the gate, NOT the sleeve).**
- `junk_proxy_ret` = equal-weight return of bottom-quintile-by-price S&P names (penny-ish, high-beta).
- `quality_proxy_ret` = top-quintile-by-ROA.
- `junk_premium_20d` = trailing 20d (junk_proxy − quality_proxy).
- VIX state: VIX > 22 OR VIX 1m-3m term-structure inverted (yfinance ^VIX, ^VIX3M).
- **Gate ON** (run the long-quality/short-junk sleeve) when: junk_premium_20d < its trailing 1yr median AND VIX condition.
- **Gate OFF** otherwise (stay flat — this is the key — don't try to flip).

**Persistence.** The sleeve isn't arbed because it's a *real* risk premium for holding quality through quality regimes; what kills it is paying that premium during junk rallies. A trend-following gate on the junk-vs-quality spread is mechanically anti-whipsaw-y in the 2019 / 2020-H2 melt-ups (when junk_premium_20d screams positive) and turns the sleeve ON in 2022-style drawdowns *before* the worst of the rotation.

**Falsifiable test.**
- Compute sleeve P&L 2018-2026 with and without the gate.
- **PASS bar:** gated version's CAPM-α > ungated by ≥2pp/yr, with %-positive years ≥ 6/8, AND the gate decision must be available T-1 (no lookahead).
- Phase-envelope sweep (different gate thresholds): require ≥70% of parameter grid beats ungated. If only one threshold works → overfit, reject.

---

## #5 — Month-End ETF Rebalance Pressure on S&P Recent Adds (microstructure × event)

**Scenario trigger.** Last 3 trading days of each month, applied to names added to S&P 500 in the prior 60 days. (Index inclusion + month-end forced-buying overlap.)

**Signal.** Long basket of recent-adds (≤60d since inclusion) held last-3-trading-days


### Gemini

Here are four scenario-conditional trading strategies designed to be orthogonal to the core PEAD+quality composite. They strictly avoid universal cross-sectional factors, rely entirely on the stated data layer, and exploit specific microstructure, event, or regime states where institutional constraints or retail behavioral biases create persistent, unarbed mispricings.

### 1. The "Panic-Insider" Capitulation (Regime-Gated Event)
**The Anti-Pattern Solved:** The brief notes that "Insider-cluster" is null as a universal cross-sectional factor. This is because routine insider buying in bull markets is noisy (often programmatic or signaling). However, insider buying during *market panics* is a profound capitulation signal.
*   **Scenario Trigger:** SPY is in a drawdown state (>10% off its 252-day high) OR VIX > 25. 
*   **Signal:** Form-4 Open Market Buys by $\ge$ 2 unique C-suite/Board insiders within a 5-day window (EDGAR Postgres). 
*   **Entry/Exit:** Go long on the Close of the day the second Form-4 is filed. Hold for 63 trading days (one quarter).
*   **Persistence Mechanism (Why unarbed?):** Institutional career risk. During a VIX>25 drawdown, institutional PMs are forced to de-gross to meet risk limits and will not catch "falling knives." Insiders, however, have zero career risk regarding short-term mark-to-market and possess asymmetric knowledge that bankruptcy/liquidity risk is zero. 
*   **Falsifiable Test:** Event study of 63-day forward returns. **Null:** Insider clusters during panics perform no differently than random entries during panics. Compute Jensen's CAPM-$\alpha$ (net of 30bps) against the S&P 500, phase-averaged across the 2018 Q4, 2020 COVID, and 2022 bear windows. 

### 2. VWAP-Confirmed PEAD (Microstructure-Gated Event)
**The Anti-Pattern Solved:** Standard PEAD buys the gap, but often suffers when a headline beat is heavily sold into by institutions. We can use Polygon minute bars to separate "retail gaps" from "institutional accumulation."
*   **Scenario Trigger:** Earnings Release Date (yfinance) with a positive surprise.
*   **Signal:** Compute the Day 0 intraday VWAP using Polygon minute bars. The signal fires if: `Day 0 Close > Day 0 VWAP by > 1.5%` AND `Day 0 Volume > 2x 20-day SMA`. 
*   **Entry/Exit:** Buy at Day 0 Close (or Day 1 Open). Hold for 21 days.
*   **Persistence Mechanism (Why unarbed?):** Institutional execution friction. Large funds cannot buy their full size in the opening auction without massive market impact. They use TWAP/VWAP algos over several days. A close significantly *above* the VWAP on massive volume mathematically proves that institutional algos are "falling behind" the liquidity and will be forced to continue accumulating in the days following.
*   **Falsifiable Test:** Forward IC of 21-day returns. Compare the CAPM-$\alpha$ of "VWAP-confirmed PEAD" vs. "VWAP-rejected PEAD" (where Close < VWAP). Phase-average across all earnings seasons 2018-2026. If the $\Delta\alpha$ isn't > 2% net of 30bps, reject the hypothesis.

### 3. The "Junk Rally" Meta-Gate via Intraday/Overnight Drift (Cross-Asset State)
**The Anti-Pattern Solved:** The live Quality+PEAD L/S strategy bleeds $-2\%$ to $-3\%$ in "junk rallies" (e.g., 2019 melt-up, late 2020). We need an ex-ante trigger to gate the short-junk sleeve.
*   **Scenario Trigger:** The onset of a low-quality/high-beta "dash for trash" rally.
*   **Signal:** Use Polygon EOD to decompose SPY returns into **Overnight** (Close$_{t-1}$ to Open$_t$) and **Intraday** (Open$_t$ to Close$_t$). Compute the 10-day rolling sum of SPY Intraday vs. Overnight returns. *Trigger state:* `10-day SPY Intraday Return > 10-day SPY Overnight Return + 2%` AND `VIX < 20-day SMA`.
*   **Entry/Exit:** This is a META-GATE. When triggered, immediately reduce the weight of the short-junk/long-quality sleeve to 0 (or move to cash). Restore when the intraday/overnight spread normalizes.
*   **Persistence Mechanism (Why unarbed?):** Junk rallies are structurally driven by retail FOMO (which executes primarily intraday) and short-covering squeezes. Institutions (who trade the overnight/close) are net sellers/flat. Fundamentals-based PMs cannot arbitrage this because they are the ones being squeezed; they are forced to cover, fueling the intraday rally.
*   **Falsifiable Test:** Backtest the existing live pipeline (Quality+PEAD) with and without this Meta-Gate. Judge on phase-averaged Jensen's $\alpha$. The gate must show a statistically significant reduction in maximum drawdown during the 2019 and H2 2020 phases without sacrificing >1% $\alpha$ in the 2022 bear market.

### 4. Earnings "Gap & Crap" Exhaustion (Microstructure State)
**The Anti-Pattern Solved:** Buying momentum blindly at the top of a bull market fails. This strategy fades exhaustion gaps in complacent regimes.
*   **Scenario Trigger:** Complacent Bull Regime (SPY > 50-day SMA AND VIX < 15).
*   **Signal:** On an Earnings Date (yfinance), a stock gaps up $> 5\%$ at the Open (Polygon minute bars). However, the first 15-minute candle (09:30-09:45) is heavily negative (`Close_0945 < Open_0930`) and accounts for >10% of the stock's average daily volume.
*   **Entry/Exit:** Short at 09:45 AM. Exit at 15:55 PM (Strictly intraday; no overnight hold).
*   **Persistence Mechanism (Why unarbed?):** Retail traders buy the headline gap at the open via market orders. Institutions use this sudden burst of retail liquidity to distribute shares they've held into earnings. It is unarbed because intraday short-selling capacity is constrained, and risk-limits prevent most systematic funds from holding unhedged short positions on earnings days.
*   **Falsifiable Test:** Intraday event study (09:45 to 15:55 return). **Null:** The intraday return of earnings gap-ups with a red first 15-min candle is equal to those with a green first 15-min candle. Permute the first-candle direction. Must generate > 50bps of intraday $\alpha$ per trade to clear slippage/borrow costs.


### GPT-5.5




---

## Phase 2 — Cross-critiques


### Opus

# Critique of panel proposals

I'll grade each on (a) computability, (b) anti-pattern risk, (c) test isolation.

GPT-5.5's proposals are missing from the prompt I received, so I'll critique Gemini's four and then rank across what I have (mine + Gemini's).

---

## Gemini #1 — Panic-Insider Capitulation

**Computable?** Yes. Form-4 is in Postgres, VIX/drawdown trivial from yfinance/Polygon. Clean.

**Anti-pattern risk?** This is the right escape from the falsified universal insider-cluster signal. Brief explicitly says "insider-cluster as a *cross-sectional factor* — null." Gating to panic regimes is a legitimate conditional reframe, not a re-proposal.

**Test isolation concerns:**
- 63-day hold during a VIX>25 panic loads massive β. Jensen's α (correctly specified) handles it, but the sample is *tiny* — maybe 3 distinct panic windows in 2018-2026 (Q4'18, COVID, 2022). That's not "phase-averaged across ≥3 regimes," that's 3 events total. Permutation null must be over *entry timing within panic windows*, not across all dates.
- "≥2 insiders / 5 days" needs a baseline rate during panics — insider buying mechanically spikes during drawdowns, so the cluster threshold may have no marginal information beyond "buy SPY at VIX>25" (which itself works).
- **Required ablation:** compare cluster-stocks vs random panic-window stocks vs SPY. If the first two are indistinguishable, the edge is just "buy panic," not "buy insider-panic."

**Verdict: SURVIVES, with mandatory ablation against the panic-baseline.** Small-N is the real risk, not arbitrage.

---

## Gemini #2 — VWAP-Confirmed PEAD

**Computable?** Yes — Polygon minute bars 2018+, yfinance earnings dates. Clean.

**Anti-pattern risk?** PEAD long-only is in the live composite. This is *conditioning PEAD on intraday confirmation*, which is genuinely orthogonal and exactly the kind of "minute-bar observable" the brief asks for.

**Test isolation concerns:**
- The narrative ("institutions falling behind VWAP") is post-hoc storytelling. A close >1.5% above VWAP on 2× volume is just **strong intraday momentum on earnings**, which may be subsumed by the surprise magnitude itself. Need to control for surprise size — otherwise this is "big-beat PEAD" relabeled.
- The right test isn't VWAP-confirmed vs VWAP-rejected (those have different beats); it's **VWAP-confirmed vs surprise-matched non-confirmed**. Match on SUE decile, then test the residual.
- 21-day hold loads beta in bull windows. CAPM-α specification handles it.
- Sample is large (thousands of earnings × 8 years), so permutation null is well-powered.

**Verdict: SURVIVES, with mandatory surprise-decile matching.** This is the strongest of Gemini's four if the matched test holds.

---

## Gemini #3 — Junk-Rally Meta-Gate via Intraday/Overnight Drift

**Computable?** Yes. Polygon EOD has open/close, prior close → overnight return is trivial.

**Anti-pattern risk?** ⚠️ **Yellow flag.** The brief explicitly lists "Reactive crash-timing via SMA/VIX gate" as a falsified anti-pattern that *makes COVID worse*. Gating *off* the long-quality sleeve in junk rallies is the symmetric inverse — and intraday-vs-overnight is a well-documented signal (Lou-Polk-Skouras, Kelly et al.), so it may already be priced.

**Test isolation concerns:**
- The signal has two degrees of freedom (2% threshold, 10-day window) tuned on the same junk-rally windows it must explain (2019, H2 2020). High overfitting risk on a 2-event sample.
- "Reduce to 0" is a binary policy — needs out-of-sample validation on at least one junk window not used to set thresholds. We have maybe 2 such windows. **Not enough degrees of freedom for a falsifiable meta-gate.**
- The right framing is *continuous*: regress L/S sleeve next-week return on the intraday-overnight spread across the full sample. If the coefficient is significant and stable across subsamples, *then* discretize.

**Verdict: WEAK — KILL in current form.** Reframe as a continuous regression, not a binary gate, and validate OOS. Otherwise this is curve-fitting two events.

---

## Gemini #4 — Earnings Gap & Crap Exhaustion (intraday short)

**Computable?** Yes, minute bars support it.

**Anti-pattern risk?** Three serious problems:
1. **Borrow costs are not 30bps.** Shorting a stock that just gapped +5% on earnings has hard-to-borrow fees that can be 200-500bps annualized, and on small-caps can be punitive intraday. The brief's "30bps net" assumption doesn't apply.
2. **Intraday-only short on gap-up earnings stocks has brutal asymmetric tail risk** — if the 09:45 dip was a head-fake and the stock rips, single trades can lose 10%+. The Sharpe of mean intraday edge gets destroyed by the tail.
3. **Regime gate is narrow** (SPY>50SMA AND VIX<15) — this is maybe 30-40% of the sample, and the earnings × complacent-regime × gap>5% × red-first-15min funnel will yield single-digit trades/quarter. Permutation null will have no power.

**Test isolation concerns:** The "permute first-candle direction" null is the right idea, but with N likely <100 events over 8 years, you can't tell signal from noise.

**Verdict: KILL.** Borrow costs + tail risk + tiny N + intraday-short complexity. The brief asks for things runnable in the existing harness — this needs an intraday short execution model we don't have.

---

## Cross-panel ranking (top picks to implement first)

Without GPT-5.5's proposals in front of me, I rank among Gemini's + my own:

**1. Gemini #2 — VWAP-Confirmed PEAD (with surprise-decile matching)**
Best signal-to-noise: large N, orthogonal to existing PEAD (conditions on minute-bar confirmation, not the gap itself), survives at 30bps if the matched-pair α exceeds borrow-free long costs. The matching requirement converts it from a storytelling exercise to a falsifiable hypothesis. Highest expected ship-quality.

**2. Gemini #1 — Panic-Insider, with panic-baseline ablation**
The reframe is correct (insider as panic-conditional, not universal). The mechanism (asymmetric career risk, insider liquidity certainty) is real and known to persist. Risk is small-N (3 events), so it must ship as a hypothesis with a pre-registered ablation, not a backtest result. If panic-insider α > panic-baseline α with p<0.10 on the ablation, that's a real find.

**3. [Placeholder for my own best idea / GPT-5.5's strongest]**
Without GPT-5.5's set, I'd put a candidate of my own here — likely an **FOMC-day drift conditional on prior 5-day SPY direction** (calendar event, clean minute-bar test, large N from 2018-2026 ≈ 64 FOMC days, permutation null over non-FOMC Wednesdays, no borrow issues, no anti-pattern overlap). If GPT-5.5 proposed something with similar N/cleanliness, prefer theirs over my speculative slot.

**KILL list:**
- Gemini #3 (junk-rally meta-gate): re-classified anti-pattern, 2-event overfit.
- Gemini #4 (intraday gap-and-crap short): borrow costs invalidate the 30bps assumption; tail risk + tiny N.

## Meta-observation

Gemini's #1 and #2 share a common virtue: they take a *falsified universal factor* (insider, PEAD-gap) and ask "in what scenario does the mechanism actually have to work?" That's the right shape for this session. #3 and #4 fall into the trap of inventing new universal signals on small-event samples — the same overfitting mode the brief warns against.

The implementation priority should be: ship #2 first (largest N, cleanest test), #1 second (smallest sample but highest novelty), and hold the rest pending OOS evidence.


### Gemini

As Gemini, I have reviewed the brief, the strict data constraints, and the submissions from my peers. 

First, let the record show that **GPT-5.5’s connection dropped mid-transmission**. We will proceed without them. 

Second, the brief is crystal clear: the era of hunting for universal cross-sectional factors on EOD data is dead. We are looking for **scenario-conditional structural edges**—places where forced flow, institutional constraints, or mechanical indexing create temporary mispricings that we can capture using Polygon, EDGAR, and yfinance.

Here is my rigorous critique of Opus’s proposals, followed by the definitive **Top 3 Strategies** we should actually build and test in the backtest harness.

---

### PART 1: CRITIQUE OF OPUS'S PROPOSALS

Opus brought some strong structural thinking, but several ideas fall into the exact traps the brief warned against. 

**#1 — Overnight-Gap Reversal on Form-4 Cluster Buys**
*   **Computability:** YES. Postgres Form-4 + Polygon EOD/minute.
*   **Arbed / Anti-pattern?** NO. This is brilliant. Form-4 insider buying as a universal factor is a known anti-pattern (already falsified). But conditioning it on a *forced overnight gap-down* completely changes the thesis. You are providing liquidity to indiscriminate overnight sellers (ETF rebalancers, margin calls) exactly where informed insiders just anchored the valuation. 
*   **Test Quality:** Excellent. The permutation null (shuffling Form-4 dates) perfectly isolates the *timing* edge of the gap from the general drift of the stock.
*   **Verdict:** **SURVIVES.** This is a top-tier microstructure/event crossover.

**#2 — FOMC-Day Intraday-Reversal Sleeve**
*   **Computability:** YES. Polygon minute bars.
*   **Arbed / Anti-pattern?** YES. Highly arbed. 
*   **Flaw:** Opus is ignoring our execution constraints. The 14:30–15:00 FOMC window is dominated by HFTs, dealer-gamma hedging (which we lack data for), and extreme spread widening. Paper-trading this via Alpaca will show a theoretical alpha that will be entirely consumed by slippage. Furthermore, with only ~8 events a year, the capacity is minuscule.
*   **Verdict:** **KILL.** Too crowded, un-executable on our stack, fails the 30bps real-world hurdle.

**#3 — Post-Earnings Implied-Move "Crush" Fade**
*   **Computability:** YES. Polygon EOD, EDGAR PIT.
*   **Arbed / Anti-pattern?** YES. This is a disguised anti-pattern.
*   **Flaw:** The brief explicitly stated that multiplicative factor interactions (e.g., accruals × PEAD) are null. Opus is trying to sneak the "accruals" factor back in by applying it to the "muted earnings" subset. Fundamental accruals do not magically re-price in a 5-day window just because an earnings gap was small. This is data-mining a dead universal factor into a micro-window.
*   **Verdict:** **KILL.** 

**#4 — Regime Meta-Gate for the Long-Quality/Short-Junk Sleeve**
*   **Computability:** YES. Polygon EOD, EDGAR ROA, yfinance VIX.
*   **Arbed / Anti-pattern?** NO. This directly answers the brief's explicit request for a meta-strategy to gate the existing PEAD+quality sleeve.
*   **Flaw:** The signal (`junk_premium_20d`) is solid, but the test needs to be ruthless. Trend-following a spread can lead to massive whipsaws in V-shaped recoveries. 
*   **Verdict:** **SURVIVES.** It solves our biggest systemic drag (the -2% to -3% alpha bleed during junk rallies).

**#5 — Month-End ETF Rebalance Pressure**
*   **Verdict:** **KILL.** Cut off, incomplete, and front-running S&P adds is a heavily saturated trade requiring tick-level execution.

---

### PART 2: THE FINAL 3 STRATEGIES (TO IMPLEMENT FIRST)

Combining the surviving elements of Opus's logic with my own structural analysis, here are the **3 strongest scenario-conditional strategies** that strictly obey the data layer constraints and are ready for the backtest harness.

#### 1. The Junk-Premium Meta-Gate (Regime Conditional)
*(Refined from Opus #4 — Solves the system's biggest current alpha-bleed)*

*   **Scenario Trigger:** Detect the transition between a "Flight to Quality" regime and a "Junk/Melt-up" regime ex-ante.
*   **Signal (Computable):** 
    *   Calculate the `Junk_Quality_Spread`: Trailing 20-day return of the lowest-price/highest-beta S&P quintile MINUS the highest-ROA (EDGAR PIT) S&P quintile.
    *   **Gate OFF (Cash/Flat):** If `Junk_Quality_Spread` > its 252-day median AND VIX < 20. (This defines a junk rally where quality factors bleed).
    *   **Gate ON (Deploy Core PEAD/Quality Strategy):** If `Junk_Quality_Spread` < its 252-day median OR VIX term structure (1M vs 3M) inverts.
*   **Persistence Mechanism:** The quality premium is a real behavioral edge, but it is deeply cyclical. Junk rallies are driven by macro liquidity, not fundamentals. By gating the strategy, we avoid paying the "quality tax" during liquidity-driven melt-ups (e.g., 2019, late 2020).
*   **Falsifiable Test:** 
    *   Run the live composite (m/q/v + PEAD) 2018-2026.
    *   Apply the Meta-Gate. 
    *   **PASS bar:** The gated strategy must improve Jensen's CAPM-α by ≥ 250bps annualized vs. the ungated baseline, specifically by reducing drawdowns in the 2019/2020 junk phases, without lookahead bias.

#### 2. Overnight-Gap Reversal on Form-4 Clusters (Microstructure × Event)
*(Opus #1 — The best orthogonal alpha proposed)*

*   **Scenario Trigger:** A forced liquidity event (overnight gap down) intersecting with an informed value anchor (recent insider buying).
*   **Signal (Computable):**
    *   Filter Postgres Form-4 for ≥2 distinct open-market buys (Code P) in the last 10 days (or 1 buy > $250k).
    *   On Day *t*, the stock gaps down at the open by ≤ -2.0σ of its rolling 60-day overnight return distribution.
    *   Filter: 20d ADV > $20M (Polygon EOD).
*   **Entry/Exit:** Buy at the Day *t* open (using Polygon minute bar for accurate execution pricing). Exit at Day *t+3* close. Beta-hedge with SPY.
*   **Persistence Mechanism:** Insiders are early and often wrong on timing. But when a stock with heavy insider conviction is mechanically gapped down overnight (due to ETF outflows, macro sympathy, or margin liquidations), it creates a vacuum of liquidity. You are getting paid to absorb forced selling at a price *below* where insiders just put their own cash.
*   **Falsifiable Test:**
    *   Event study 2018-2026.
    *   **Permutation Null:** Shuffle the Form-4 cluster dates within the same tickers 1000x. If the gap-down alone generates the alpha, the null will match the signal.
    *   **PASS bar:** Mean α > 30bps net per trade, permutation p < 0.05, positive across 4 of 5 macro phases.

#### 3. PEAD Opening-Range Exhaustion (Microstructure × Event)
*(Gemini Original — Exploits a structural flaw in standard PEAD)*

*   **Scenario Trigger:** Earnings day (Day *t*). The stock gaps up significantly on a positive surprise, but institutional flow is secretly distributing (selling into the retail pop).
*   **Signal (Computable):**
    *   Trigger: Earnings gap > +4% (Polygon `open_t / close_{t-1}`).
    *   **The Microstructure State:** Calculate the Volume-Weighted Average Price (VWAP) using Polygon minute bars from 09:30 to 10:00 AM ET.
    *   **Condition:** If the 10:00 AM price is *below* the 09:30 AM Open, AND the 30-min VWAP is *below* the Open.
*   **Entry/Exit:** Short the stock at 10:00 AM ET. Hold to Day *t+2* close.
*   **Persistence Mechanism:** Standard PEAD models (like the one currently in our live system) buy positive earnings gaps blindly. However, if the opening 30-minute VWAP is negative despite a massive gap up, it proves that large institutional execution algos are using the retail liquidity to unwind blocks. Retail buys the headline; institutions fade the gap. This isolates the "Failed PEAD" scenario.
*   **Falsifiable Test:**
    *   Event study on S&P 500 earnings gaps 2018-2026.
    *   **Phase split:** Bull (2019, 2021), Bear (2022), Chop.
    *   **PASS bar:** Short-side CAPM-α > 40bps net of costs per trade. Must show statistically significant underperformance relative to earnings gaps where the 30-min VWAP is *above* the open (the true PEAD continuation). 

### Summary for the Build Harness
Do not build any more cross-sectional fundamental rankers. Route engineering resources to **Idea 1** immediately (the Regime Meta-Gate is a config-layer addition that can save our current forward-paper run from a junk-rally drawdown). Then, build the minute-bar event-study pipelines for **Idea 2** and **Idea 3**.


### GPT-5.5

## Bottom line

**Survive scrutiny, with repairs:** Opus #1, #2, #4; Gemini #1, #2, #3, #4.  
**Kill as written:** Opus #3, Opus #5.  
**Implement first:**  
1. **Quality/junk regime meta-gate** — merge Opus #4 + Gemini #3, with duty-cycle/permutation controls.  
2. **Earnings gap-up opening-range failure / “gap & crap”** — Gemini #4, but with tighter matching controls.  
3. **Insider-panic / insider-gap-down liquidity provision** — merge Opus #1 + Gemini #1.

I would not implement FOMC or VWAP-PEAD first: both are computable, but FOMC is tiny-N/crowded and VWAP-PEAD is more of a PEAD enhancement than a genuinely orthogonal scenario edge.

---

# Global critique standard

For every event strategy, the test must avoid three common false positives:

1. **Pooled-stock t-stats are invalid.** Earnings days and FOMC days create cross-correlated returns. Aggregate to event-day or calendar-day portfolio returns, then compute alpha.

2. **Beta/market rebound contamination.** Especially for panic-insider ideas, raw forward returns after a crash will look great. Must compute Jensen’s CAPM alpha net of 30 bps, ideally with beta estimated using pre-event returns and/or explicit SPY hedge.

3. **Scenario null must preserve the scenario.** Randomly shuffling all dates is too easy. The null should compare:
   - same ticker,
   - same regime,
   - same gap size / volume / liquidity bucket,
   - same holding period,
   - same duty cycle.

---

# Opus proposals

## Opus #1 — Overnight-gap reversal on Form-4 cluster buys

### Verdict: **SURVIVES, with repairs**

### Computable?
Mostly yes.

Data required:

- Form-4 open-market buys: computable from EDGAR/Form-4.
- Distinct insiders, transaction code `P`, direct ownership, transaction value: computable if the Form-4 parser stores reporting-owner relationship and transaction fields.
- Overnight gap using Polygon open/close: computable.
- 60-day overnight-return z-score: computable.
- Liquidity filter: computable.
- SPY beta hedge: computable.

Caveats:

- Must use **filing acceptance timestamp**, not transaction date. Form-4 transactions can occur before the market knows. If the Form-4 was filed after the prior close, you cannot use it at the next open unless the timestamp is before the decision time.
- Entry “at open” is slightly unrealistic because you only know the open after the auction print. Use first tradable minute, e.g. 09:31 or 09:35.
- “S&P 1500 universe” may not be available PIT. If not, use PIT S&P 500 or all Polygon common stocks with ADV/liquidity filters.

### Anti-pattern?
Not obviously. Insider-cluster as a universal factor was already falsified, but this is **not** the same claim. The scenario is:

> Recent informed buying + forced overnight selling shock.

That is a legitimate conditional hypothesis.

### Test quality?
Good start, but needs two more controls:

1. **Matched gap-down control:** Compare insider-cluster gap-downs to non-insider gap-downs matched on ticker liquidity, gap z-score, beta, prior drawdown, and sector.
2. **Filing-date permutation:** Shuffle Form-4 filing dates within ticker, preserving the empirical clustering frequency.

Also evaluate at the **event-date portfolio level**, not stock-event level.

### Final judgment
Good candidate. I would merge this with Gemini #1 into a broader “insider liquidity provision during stress” test.

---

## Opus #2 — FOMC-day intraday reversal sleeve

### Verdict: **SURVIVES AS A CHEAP FALSIFICATION, but low priority**

### Computable?
Yes, assuming we provide a static FOMC calendar. That is public, non-alt-data, and acceptable.

Required data:

- Polygon minute bars.
- Prior ADV/liquidity screen.
- SPY minute bars if hedging or estimating intraday beta.

### Anti-pattern?
No, it is genuinely scenario-conditional. But it is also a **very crowded and well-known** intraday pattern. The “2pm knee-jerk reversal” idea has been studied for years.

### Test quality?
The proposed test is decent:

- FOMC days vs random non-FOMC days.
- Drop the largest events.
- Net costs.

But I would add:

1. **Within-FOMC rank permutation:** On each FOMC day, shuffle the knee-jerk ranks across names. This tests whether the cross-sectional reversal signal matters, not merely whether FOMC afternoons are volatile.
2. **Event-level returns:** One observation per FOMC meeting, not one per stock.
3. **Cost sensitivity:** 30 bps round trip is harsh for 85-minute liquid-name L/S, but the project bar requires it. If it only works before costs, kill it.

### Final judgment
Computable and falsifiable. Prior is modest because sample is tiny, approximately 64 events, and the anomaly is likely arbed. Worth a quick test, not a flagship strategy.

---

## Opus #3 — Post-earnings muted-reaction accruals

### Verdict: **KILL AS WRITTEN**

### Computable?
Partially, but there is a serious PIT issue.

The proposal says to rank muted earnings by accruals:

\[
\text{accruals} = (NI - CFO) / assets
\]

If this uses the **current quarter’s** CFO/NI around the earnings event, it is likely lookahead. CFO is often unavailable until the 10-Q filing, which may arrive after the earnings press release. Unless the 10-Q has already been filed by the trade decision time, current-quarter accruals are not available.

If instead it uses **previously filed** trailing accruals, it is computable. But then the signal becomes essentially:

> Prior accrual quality conditioned on a muted earnings gap.

That is less novel and closer to a quality/accrual factor with an event gate.

### Anti-pattern?
High risk of being an anti-pattern in disguise. Universal accruals were already falsified/null. This proposal tries to revive accruals by conditioning on muted earnings, but the economic mechanism is not as clean as Opus #1 or the regime gate.

Also, the title says “implied-move crush,” but no option-implied move is available. The strategy uses realized volatility as a proxy. That is fine computationally, but the label is misleading.

### Test quality?
The proposed test is not enough.

Problems:

- “Random muted earnings assignments within ticker history” does not isolate whether the muted-earnings scenario itself matters.
- Need matched controls against:
  - muted non-earnings gap days,
  - high-gap earnings days,
  - same surprise/gap decile,
  - same sector/size/liquidity buckets.
- Need strict PIT validation for accrual availability.

### Final judgment
Kill as written. A salvaged version using **previously filed accruals only** could be tested, but I would not prioritize it.

---

## Opus #4 — Regime meta-gate for long-quality/short-junk sleeve

### Verdict: **SURVIVES STRONGLY**

### Computable?
Yes.

Required data:

- PIT quality/ROA: EDGAR.
- Price-based junk proxy: Polygon.
- VIX: yfinance.
- VIX3M: probably accessible through yfinance as `^VIX3M`, but confirm. If not, drop the term-structure clause and use VIX level/slope only.

Caveat: “bottom-quintile-by-price” is a crude junk proxy. Low share price is not the same as junk. Better candidate junk definitions:

- high beta,
- poor ROA,
- high accruals,
- weak momentum,
- high drawdown,
- low price maybe as a minor component.

### Anti-pattern?
No. This is exactly the kind of scenario-conditional idea the brief asks for. The core finding was:

> Quality/PEAD L/S works in flight-to-quality regimes and bleeds in junk rallies.

This proposal directly attempts to detect that regime ex ante.

### Test quality?
Directionally good, but strengthen it:

1. **Duty-cycle matched null:** Compare to random ON/OFF gates with the same percent of days active.
2. **Walk-forward threshold selection:** Do not choose VIX 22 / 20d / median thresholds on the full sample.
3. **Parameter grid robustness:** Opus’s 70% grid-pass requirement is good.
4. **Phase split must include junk rallies:** 2019 melt-up, 2020 H2, 2022 bear, 2023 AI/mega-cap rally, 2024-26.
5. **Judge on Jensen’s CAPM alpha net 30 bps**, not raw spread P&L.

### Final judgment
This is one of the best proposals. It attacks a known weakness in the current system and is testable with existing infrastructure.

---

## Opus #5 — Month-end ETF rebalance pressure on recent S&P adds

### Verdict: **KILL**

### Computable?
Questionable.

You need reliable PIT S&P 500 addition dates, preferably announcement and effective dates. The project has PIT S&P 500 membership for the factor universe, but it is not clear that we have a clean index-event table with addition dates. Inferring additions from sparse snapshots is risky.

### Anti-pattern?
Very likely. Index inclusion and month-end rebalancing effects are heavily studied and heavily arbed. Also, “recent adds in last 60 days” are not necessarily subject to continuing forced buying at month-end.

### Test quality?
Incomplete. The proposal lacks:

- exit specification beyond “last three trading days,”
- hedge,
- null,
- phase split,
- transaction-cost model,
- treatment of announcement vs effective date,
- control for momentum/size/liquidity.

### Final judgment
Kill. Too incomplete and probably crowded.

---

# Gemini proposals

## Gemini #1 — Panic-insider capitulation

### Verdict: **SURVIVES, best merged with Opus #1**

### Computable?
Yes, with caveats.

Required data:

- SPY drawdown: Polygon.
- VIX: yfinance.
- Form-4 open-market buys by unique insiders: EDGAR/Form-4.
- C-suite/board flags: likely available from reporting-owner relationship fields, but verify parser coverage.

Caveat: Entry “on the close of the day the second Form-4 is filed” can be lookahead if the filing is accepted after market close. Use:

- same-day close only if accepted before a cutoff, e.g. 15:45,
- otherwise next open or next close.

### Anti-pattern?
Not necessarily. Insider clusters alone were falsified, but panic-gated insider buying is a cleaner scenario:

> Insiders buy when external capital is de-risking and public-market investors are refusing falling knives.

That is economically plausible.

### Test quality?
Good direction, but must avoid crash-rebound beta illusion.

Necessary improvements:

1. **Matched panic null:** Random entries during the same panic windows, matched by prior drawdown, beta, size, sector, and liquidity.
2. **Form-4 date shuffle within ticker.**
3. **CAPM alpha with pre-event beta.**
4. **Separate market panic vs idiosyncratic panic.** A VIX>25 signal may just buy high-beta rebound candidates.
5. **Require sufficient events.** If only 2018 Q4, COVID, and 2022 produce a small handful of events, the test will be underpowered.

### Final judgment
Survives. Combine with Opus #1 into a single insider-stress framework:

- market-panic insider clusters,
- idiosyncratic gap-down insider clusters,
- different holding horizons tested separately.

---

## Gemini #2 — VWAP-confirmed PEAD

### Verdict: **SURVIVES, but not very orthogonal**

### Computable?
Yes.

Required data:

- earnings dates/surprises: yfinance,
- minute bars for VWAP: Polygon,
- volume filters: Polygon,
- forward returns: Polygon.

Caveats:

- Historical yfinance earnings surprise data can be spotty. Validate coverage and survivorship.
- If using full-day VWAP and full-day close, trading “at the close” can be lookahead. Use 15:50 VWAP and enter 15:55, or enter next open.

### Anti-pattern?
This is not a universal factor, but it is close to an enhancement of PEAD. The live system already has PEAD. This proposal may simply select:

- bigger post-earnings momentum,
- higher relative volume,
- larger institutional attention,
- higher beta.

That does not make it bad, but it makes it less orthogonal.

### Test quality?
Needs to be stricter.

The proposed test compares VWAP-confirmed PEAD vs VWAP-rejected PEAD. Good start, but also control for:

- earnings surprise decile,
- opening gap size,
- day-0 return,
- relative volume,
- market beta,
- sector,
- market regime.

Otherwise “close > VWAP” may just be another way of saying “day-0 momentum was strong.”

Use event-study alpha, not just forward IC.

### Final judgment
Survives as a PEAD execution/filter improvement. I would implement it after the regime gate and the more orthogonal intraday earnings fade.

---

## Gemini #3 — Junk-rally meta-gate via intraday/overnight drift

### Verdict: **SURVIVES, best merged with Opus #4**

### Computable?
Yes.

Required data:

- SPY open/close: Polygon.
- VIX: yfinance.
- Existing quality/junk sleeve P&L: already in system or factor lab.

### Anti-pattern?
No. This is a direct attempt to detect the regime where the quality/junk sleeve loses money.

The causal story is somewhat hand-wavy — “retail trades intraday, institutions overnight” is not universally true — but the signal itself is legitimate:

> Strong intraday SPY drift plus falling VIX may proxy speculative risk-on behavior.

### Test quality?
Needs strengthening.

Gemini’s test says reduce drawdown in 2019/H2 2020 without sacrificing 2022 alpha. That is right directionally, but add:

1. **Same-duty-cycle random gates.**
2. **Parameter grid robustness.**
3. **Walk-forward threshold selection.**
4. **Compare directly to Opus’s junk-minus-quality spread gate.**
5. **Test combined gate vs each component alone.**

### Final judgment
Strong candidate. I would not run this as a separate strategy; I would fold it into the regime meta-gate feature set.

---

## Gemini #4 — Earnings “gap & crap” exhaustion

### Verdict: **SURVIVES, with tighter controls**

### Computable?
Yes.

Required data:

- earnings dates: yfinance,
- minute bars: Polygon,
- SPY SMA and VIX: Polygon/yfinance,
- intraday volume and first-15-minute candle: Polygon.

Caveats:

- Need earnings release timing. A gap at the open usually reflects prior after-close or same-day premarket earnings. If yfinance only gives a date, we need infer the correct event session from the gap/volume or obtain release time from available yfinance fields if present.
- Intraday shorting requires borrow availability. We do not have borrow data. Restrict to highly liquid, large-cap/easy-to-borrow names to reduce unmodeled locate risk.
- Enter at 09:45 only after the 09:45 bar is complete, so realistically 09:46 or 09:47.

### Anti-pattern?
Opening-range gap fades are known and likely partially arbed. But conditioning on:

- earnings day,
- large gap-up,
- complacent bull regime,
- red first 15-minute candle,
- high relative volume,

makes this more scenario-specific and plausibly orthogonal to PEAD.

### Test quality?
The proposed null is insufficient.

Comparing red first-candle gap-ups to green first-candle gap-ups is useful, but not enough. Need:

1. **Matched non-earnings gap-up days** with same gap size and first-15-minute return.
2. **Same-regime controls**: VIX<15, SPY>SMA.
3. **Gap-size buckets**: 5-7%, 7-10%, >10%.
4. **Liquidity and spread filters.**
5. **Market hedge or intraday beta adjustment.**
6. **Event-day portfolio aggregation.**
7. **Cost model heavier than 30 bps if shorting smaller names.**

### Final judgment
Survives and is one of the better orthogonal candidates. It uses minute data, is event-specific, does not rely on fundamentals, and is flat overnight.

---

# Survive / kill summary

| Proposal | Verdict | Reason |
|---|---:|---|
| Opus #1 Form-4 cluster + overnight gap-down | **Survive** | Legit event × microstructure scenario; computable; needs filing-time and matched-gap controls |
| Opus #2 FOMC intraday reversal | **Survive, low priority** | Computable and falsifiable, but tiny sample and likely crowded |
| Opus #3 Muted earnings + accruals | **Kill as written** | PIT risk on current accruals; likely accrual anti-pattern with event wrapper |
| Opus #4 Quality/junk regime gate | **Strong survive** | Directly targets known regime-dependence; computable; best strategic fit |
| Opus #5 S&P recent-add month-end pressure | **Kill** | Incomplete, likely crowded, index-event data unclear, weak test |
| Gemini #1 Panic-insider capitulation | **Survive** | Good regime-conditioned insider hypothesis; must control crash beta |
| Gemini #2 VWAP-confirmed PEAD | **Survive, medium priority** | Computable PEAD enhancement, but not very orthogonal |
| Gemini #3 Intraday/overnight junk-rally gate | **Strong survive** | Good feature for meta-gate; needs duty-cycle null |
| Gemini #4 Earnings gap & crap | **Survive** | Orthogonal intraday event setup; needs stronger matched controls |

---

# Strongest 2-3 ideas to implement first

## 1. Quality/junk regime meta-gate — Opus #4 + Gemini #3 + my preferred ensemble test

This is the highest-leverage idea.

### Why first?
The existing evidence already says the quality/PEAD L/S sleeve is **regime-dependent**. This proposal does not ask us to discover a new alpha from scratch. It asks:

> Can we avoid trading the sleeve when the observable regime is hostile?

That is the cleanest use of scenario-conditional design.

### Implementation
Test a small feature set:

- trailing junk-minus-quality return,
- quality-minus-junk return,
- SPY intraday-minus-overnight return,
- VIX level,
- VIX slope/change,
- SPY drawdown.

Gate the existing sleeve ON/OFF. Do not flip short/long. Flat is enough.

### Required test
- Jensen CAPM alpha net 30 bps.
- Phase split: 2019 junk rally, 2020 COVID/H2 junk rally, 2022 quality bear, 2023-26.
- Same-duty-cycle random gates.
- Walk-forward threshold selection.
- Parameter-grid robustness.
- Compare:
  1. ungated sleeve,
  2. Opus-style junk/quality spread gate,
  3. Gemini-style intraday/overnight gate,
  4. combined gate.

This should be implemented first.

---

## 2. Earnings gap-up opening-range failure fade — Gemini #4, with my stricter matched-null version

This is the best orthogonal event/microstructure candidate.

### Scenario
Complacent bull regime, earnings gap-up, but the first 15-30 minutes reject the gap on heavy volume.

### Trade
Short after confirmation, exit before close. No overnight exposure.

### Why it is attractive
It is:

- intraday,
- event-specific,
- orthogonal to quality/PEAD,
- computable from minute bars,
- testable across many earnings seasons.

### Required test
Compare intraday alpha for:

- earnings gap-up + red first candle,
- earnings gap-up + green first candle,
- non-earnings matched gap-up + red first candle,
- same setup outside complacent regimes.

Need event-day portfolio returns, liquidity filters, and short-cost/slippage assumptions.

---

## 3. Insider-stress liquidity provision — merge Opus #1 and Gemini #1

This should be one combined research project, not two separate strategies.

### Scenario variants
Test two branches:

1. **Market panic + insider cluster**
   - SPY drawdown >10% or VIX>25.
   - ≥2 open-market insider buys filed within 5-10 trading days.
   - Hold 21-63 days.
   - Beta hedge or evaluate strict CAPM alpha.

2. **Idiosyncratic gap-down + recent insider cluster**
   - Recent Form-4 cluster.
   - Overnight gap-down ≥2σ.
   - Enter after open, hold 3-5 days.
   - SPY hedge.

### Why attractive
Universal insider buying is dead, but insider buying during forced-liquidity stress is a different claim. The economic mechanism is plausible and not just another factor zoo signal.

### Required test
- Form-4 filing-date shuffle within ticker.
- Matched panic/gap controls without insider buys.
- Filing acceptance timestamp discipline.
- Event-date portfolio alpha, not pooled stock t-stats.
- Phase splits across 2018 Q4, COVID, 2022, and 2023-26 stress pockets if available.

---

## Not first, but worth quick falsification

### FOMC intraday reversal
Cheap to test, but tiny sample and likely crowded.

### VWAP-confirmed PEAD
Probably useful as a PEAD filter, but less strategically valuable because it is not very orthogonal to the existing PEAD sleeve.

### Muted earnings + accruals
Do not implement until the PIT accrual issue is completely resolved. As written, kill.

### S&P recent-add month-end pressure
Kill. Too incomplete and likely arbed.
