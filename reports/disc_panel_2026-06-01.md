# 3-Model Deep-Thinking Panel — 2026-06-01

- Panel: Opus `claude-opus-4-7` · Gemini `gemini-3.1-pro-preview` · OpenAI `gpt-5.5`
- Seed: `reports/_disc_seed.md`


## FINAL SYNTHESIS (ranked shortlist)

# FINAL SHORTLIST — Scenario-Conditional Strategies (Synthesis)

All three panelists converged on a small consensus set, with one strategy unanimously surviving, two surviving with required modifications, and most others killed for shared reasons (data-layer violations, anti-patterns in disguise, or execution-cost fantasy). Below is the ranked shortlist. Each entry includes only specifications all three panelists' critiques agreed on as testable.

---

## #1 — Distressed-Insider Cluster Buy (Opus #1 ∩ GPT-5.5 #1)
**Unanimous survivor. Build first.**

**Scenario trigger.** A specific firm enters a state of idiosyncratic capitulation AND informed insiders deploy personal cash. On date `t`:
- `resid_63 = R_i[-63,-1] − β_i · R_SPY[-63,-1] ≤ −20%` (idiosyncratic, not beta-driven)
- `drawdown_126 ≤ −25%` from trailing 126-day high
- Within trailing 10 calendar days: ≥2 unique `reportingOwnerCik` OR CEO/CFO/Chair filed Form-4 transaction code `P` (open-market buy), via **filing acceptance timestamp** (NOT transaction date)
- Total purchase value ≥ max($100k, 0.25% · ADV20$)
- Exclude codes M/A, option exercises, gifts, 10%-owner-only filings

**Exact computable signal.**
```
B = log1p(buy_value_10d / ADV20$)
C = log1p(unique_buyers_10d)
D = abs(resid_63)
S = z(B) + 0.5·z(C) + 0.5·z(D)
```

**Entry/exit.** Long at next open after the 2nd qualifying Form-4 acceptance. Hold 20 trading days (primary), with 10d/40d as robustness. No pyramiding. Equal-weight, cap 8 concurrent.

**Persistence mechanism.** Insider open-market buys are costly, legally constrained, and decision-relevant only in capitulation states because (a) mandate-bound funds can't buy fresh-crash names, (b) Form-4 filings are under-monitored outside mega-caps, (c) insiders have information edge on solvency/demand the public lacks. Capacity is bounded by event sparsity — that's why it persists.

**Falsifiable test.** Event study, 2018+, on Polygon liquid universe (price ≥$5, ADV20$ ≥$10M), universe re-resolved per event date.
- Primary: `α₂₀ = R_i[t+1, t+20] − β_i[-252,-21]·R_SPY[t+1, t+20] − 0.003`
- **Matched-control null**: for each event, sample 20 pseudo-dates on the same ticker that satisfy capitulation conditions but have NO Form-4 P-buy within ±30 days. Tests the *insider signal*, not the capitulation-reversal baseline.
- **Permutation null**: within each calendar year, permute cluster labels across capitulated firm-dates.
- **Decision rule (ship):** median α₂₀ > +3%, %-positive ≥ 55%, permutation p < 0.05, positive sign in ≥2 of {10, 20, 40}d horizons, NOT driven by COVID (Feb–May 2020) alone (leave-COVID-out subsample remains positive).

---

## #2 — Adverse-Material 8-K Underreaction Short (GPT-5.5 #4, hardened)
**Survives with two hard constraints: ≥$1B market cap and borrow-cost realism.**

**Scenario trigger.** EDGAR 8-K filing on date `t` matching adverse-material items:
- **Item 4.02** (non-reliance on prior financials)
- **Item 2.04** (covenant/default/acceleration)
- **Item 2.06** (material impairment)
- **Item 5.02** with negative language (abrupt CEO/CFO/auditor departure: "resigned", "dismissed", "disagreement", "reportable event")
- 8-K text contains accounting-control phrases: "material weakness", "restatement", "should no longer be relied upon", "audit committee concluded"

**Exclusions (critical):**
- 8-K within ±1 trading day of earnings
- Initial reaction `AR[t, t+1] ≤ −15%` (too repriced — chase, not edge)
- Market cap < $1B (borrow availability + locate cost destroys α at small-cap)
- Not within ±1 trading day of another material 8-K

**Exact computable signal.**
```
severity = 3·I(4.02) + 2·I(auditor/CFO adverse 5.02) + I(material weakness) + I(restatement) + I(2.04 or 2.06)
underreaction = max(0, AR[t, t+1] + 0.05)
S = severity + 2·underreaction
```

**Entry/exit.** Short at next open after the filing-acceptance timestamp is public AND after measuring `AR[t, t+1]`. Primary exit: 20 trading days. Secondary: 63 days. Force-close on corrective filing or auditor-resolution 8-K.

**Persistence mechanism.** Legal/accounting-integrity disclosures are written in low-salience legalese, often filed after market hours, slow to map to cash-flow models, and trigger forced selling only after internal risk/legal review at holders. Hribar/Jenkins, Files et al. documented multi-month post-restatement drift. Borrow constraints are *why* it persists — most quants can't short these cleanly.

**Falsifiable test.** Event study 2018+, EDGAR 8-K corpus.
- Primary: `short_α₂₀ = −R_i[entry, entry+20] + β_i·R_SPY[entry, entry+20] − 0.005` (use **50bps**, not 30bps — borrow + spread)
- **Matched-control null**: other 8-Ks from same sector/year/market-cap decile WITHOUT adverse-item language, matched on initial AR bucket.
- **Permutation null**: within all 8-K filing dates, randomly assign adverse-shock labels preserving sector/year counts.
- **Decision rule (ship):** short-side α₂₀ net 50bps positive, permutation p < 0.05, **survives ≥$1B-cap restriction**, not concentrated in one sector or one year. Single item-type attribution: at least 2 of {4.02, 2.04/2.06, adverse 5.02} contribute positively.

---

## #3 — Guidance-Cut T+5 Reversal (Opus #2, hardened)
**Provisional survivor. Promote to production only after the interaction null passes.**

**Scenario trigger.** 8-K Item 2.02 or 7.01 with explicit downward guidance regex match:
- `lower(ing|ed)? (our )?(full[- ]year|FY|Q[1-4]) (guidance|outlook|forecast)`
- `withdraw(ing)? (full[- ]year|FY)? guidance`
- `below (the )?(low end|previously) (issued|provided)`
AND event-day return ≤ −10% (mapped to correct session: filings after close → event = next session)
AND realized 5-day return after event is in the bottom decile of all guidance-cut events in trailing 2 years
AND universe: Russell 1000 by ADV proxy

**Entry/exit.** Long at the open of day T+5. Hold 15 trading days. Exit early on −7% from entry. Equal-weight, max 5 concurrent.

**Persistence mechanism.** Information re-rating happens in the first 30 minutes; mandate-driven forced selling (long-only managers, quality-screen drops, vol-target deleveraging) plays out over days 1–5. The 1-week reversal is flow-exhaustion, not information correction — structurally different from PEAD (drift, not reversal). Persists because it looks like catching a falling knife and most books prohibit it.

**Falsifiable test.** Manual validation of regex false-positive rate on 30 random hits (target <15%) before running.
- Primary: `α[T+5, T+20] = R_i − β_i·R_SPY − 0.003`
- **The required interaction null (GPT-5.5's modification):** compare to:
  1. Same-stock universe with matched D0 return and matched D0→D+5 path, but NO guidance-cut language.
  2. Negative 8-Ks (non-guidance) with similar initial selloff.
  3. Guidance cuts WITHOUT extreme follow-through.
- **Decision rule (ship):** median α > +2.5%, %-positive > 55%, permutation p < 0.05, AND **the interaction is monotone in initial gap severity** AND **guidance-cut extreme-selloffs beat mat


---

## Phase 1 — Independent proposals


### Opus

# Opus — 5 Scenario-Conditional Strategy Hypotheses

Constraint check first: I'm avoiding (a) any universal cross-section, (b) the NULL list (accruals×attention, residual mom, overnight, breadth, asset-growth, QGF-6, beta-neutral L/S variants), and (c) PEAD/quality re-skins. Each below is **conditional on a specific state** — outside that state, no position.

---

## 1. "Insider cluster-buy into a fresh 52-week-low drawdown"

**Scenario trigger.** Stock is in a ≥30% drawdown from its trailing 252-day high AND has printed a new 63-day low within the last 10 trading days AND ≥2 distinct Form-4 filers (officers/directors, NOT 10%-owners) report *open-market purchases* (transaction code P) totaling ≥$250k within a 15-day window. SPY 200-SMA filter OFF — this is a contrarian micro-event, not a market call.

**Signal (computable).** Polygon EOD for drawdown/lows. Form-4 from EDGAR (`form-4` + parsed `nonDerivativeTransaction` blocks; we already have insider history in Postgres). Field set: `transactionCode='P'`, `isDirectorOrOfficer=true`, `transactionShares*transactionPricePerShare` summed by `filedAt` within 15 cal-days. Cluster = ≥2 unique `reportingOwnerCik`.

**Entry/exit.** Equal-weight enter at next open after the 2nd P-cluster filing. Hold 60 trading days OR exit on +25% / −15% / break of the pre-event 63-day low by 7%. Cap 8 concurrent names.

**Persistence mechanism.** Insiders trading on personal account into a public drawdown are (i) information-rich (they see Q-end financials a quarter before we do via EDGAR) and (ii) self-selected for conviction (open-market cash, not grant exercise). The "deep drawdown" filter is what makes this NOT the generic insider-buy factor (which is well-arbed): in a drawdown, the prior is "broken, headed lower," so the marginal trader on the other side is forced/panic; insiders are the natural informed liquidity provider. Academic base: Cohen-Malloy-Pomorski "decoded" insider trades — opportunistic buys earn ~9% alpha. The drawdown gate isolates the opportunistic subset.

**Falsifiable test.** Build event sample 2019–2024 on PIT R3000 (universe-resolved per event date, not frozen). Compute CAPM-α (β vs SPY estimated on the prior 252d) on the 60-day forward return per event. Permutation null: 1000 random draws of same-size baskets from R3000 names with matched drawdown bucket but no cluster-buy. **Decision rule:** ship iff median event α > +3% AND p(α ≤ permuted) < 0.05 AND %positive ≥ 55% AND COVID (Feb–May 2020) subsample isn't the entire driver.

**Orthogonality.** Not in NULL list. Not PEAD (no earnings trigger). Not quality (no fundamental ranking). Event-conditional, sparse — naturally low correlation to the m/q/v book.

---

## 2. "Post-8K-guidance-cut overreaction reversal (1-week)"

**Scenario trigger.** Company files an 8-K Item 2.02 or 7.01 containing **explicit downward guidance language** (regex over: "lower(ing|ed)? (our )?(full[- ]year|FY|Q[1-4]) (guidance|outlook|forecast)", "withdraw(ing)? guidance", "below (the )?(low end|previously)"), AND same-day return ≤ −10%, AND realized 5-day return after the event is in the bottom decile of all 8-K guidance-cut events in the trailing 2 years. Universe: Russell 1000 (liquidity).

**Signal.** EDGAR 8-K full text + item codes (we have raw 10-K/8-K text). Polygon daily returns. Minute bars (we have event cache) for confirming the gap was at the open, not a slow bleed (filters out fundamentally re-rated names from one-day flush dynamics).

**Entry/exit.** Enter at the open of day **T+5** (one trading week after the gap). Hold 15 trading days. Exit early on −7% from entry. Equal-weight, max 5 concurrent.

**Persistence mechanism.** Guidance cuts trigger forced selling from (i) mandate-bound long-only managers ("can't hold lowered-guidance names"), (ii) systematic earnings-quality screens dropping the name same week, (iii) options dealers hedging puts bought into the print. By T+5 the mandated flow is exhausted but sentiment overshoot remains; the *fundamental* re-rating has happened in the first 30 min, the *flow* re-rating in days 1–5. The 1-week reversal is a flow-exhaustion trade, structurally different from PEAD (which is drift, not reversal) and not the same as overnight-return (which is universal). The reason this isn't arbed: it's small-N (~50 events/yr), looks like "catching a falling knife," and most quant books explicitly prohibit it.

**Falsifiable test.** Tag every 8-K guidance-cut event 2019–2024 via the regex (manually validate 30 hits for false-positive rate; target <15%). Compute T+5 → T+20 CAPM-α per event. Permutation null: same trigger but ON A RANDOM 8-K filing date for the same name (controls for "this stock just reverts"). **Ship iff** median α > +2.5%, %positive > 55%, p < 0.05, AND the effect is monotone in initial gap severity (placebo: shallow gaps should show weaker reversal — that's the falsifier of "it's not flow exhaustion").

**Orthogonality.** Pure event-reversal, opposite sign and different horizon than PEAD-drift. Will fire in a different name-set than the live core.

---

## 3. "Crowded-short squeeze on FINRA short-interest spike + price stabilization"

**Scenario trigger.** Bi-monthly FINRA short-interest report shows `short_interest / float` ≥ 20% AND short-interest grew ≥ +30% over the prior 2 reports (1 month) AND the stock's trailing 20-day realized vol has *contracted* (current 20d vol < 0.7 × prior 20d vol from one month before) AND price is ≥ 0% over those same 20 days. This is the "shorts piled in, but the bleed stopped" state.

**Signal.** Postgres FINRA SI table (we have ~1.5yr). Polygon daily close for vol and return. Vol = stdev of log returns, 20d.

**Entry/exit.** Enter at the close of the SI-publication day +1. Hold until the *next* SI report (≈2 weeks), exit unconditionally on publication. Equal-weight, max 6 names. Stop −10%.

**Persistence mechanism.** Short-squeezes need a catalyst, but the *setup* — high SI + stopped bleeding — is what informed long buyers wait for; once price refuses to fall, marginal shorts cover into thin float. The vol-contraction filter is what isolates this from the generic "high SI" factor (which is mildly negative on average — bad-business signal). Vol contraction means the fundamental narrative has stabilized; remaining short interest is now positioning, not thesis. The publish-cycle exit is critical: each SI release is a coordination event for both sides.

**Falsifiable test.** Walk-forward 2019–2024 on the FINRA universe. Per event: T0→T+14 CAPM-α. Compare to a placebo cohort: same SI≥20% + growth≥+30% but WITHOUT vol-contraction (these should NOT outperform — and if they do, the vol-contraction filter is spurious). **Ship iff** median α > +2% on the contraction cohort, %pos > 55%, AND the contraction cohort beats the non-contraction cohort by ≥1.5% with p<0.10 (this is the real test — the interaction, not the level).

**Orthogonality.** Uses SI data the live core ignores entirely. Holding period 2 weeks, not 63 days.

---

## 4. "Earnings-day IV-crush realized-vol fade (single-name, post-print)"

**Scenario trigger.** On scheduled earnings date `D` (yfinance earnings cache), the stock's `D-1 → D` close-to-close abs-return is in the **top quintile** of its own trailing 8 earnings prints AND `D+1` open-to-close range is in the **top quintile** of the trailing 60 days. We don't have options data, but we don't need it: this is "the post-print first day was huge in


### Gemini

As Gemini, I’ll take the lead on defining strictly **event-driven, scenario-conditional** strategies. The cross-sectional factor space (ranking the S&P 500 every 63 days) is saturated and highly vulnerable to the phase-noise envelope you described. To find a new edge, we must move from *continuous time* (always holding 24 stocks) to *discrete time* (only holding a stock when a specific microstructure or behavioral dislocation occurs). 

Here are 4 scenario-conditional hypotheses that are computable entirely within our existing data layer (Polygon, EDGAR PIT, FINRA SI, yfinance, Postgres) and orthogonal to the live m/q/v core.

---

### Hypothesis 1: The "Trapped Bear" Duration Extension (PEAD × SI Microstructure)
**The Concept:** PEAD is fundamentally an information-absorption anomaly. But when high short interest is involved, it becomes a mechanical *liquidity-duration* anomaly. We isolate earnings beats where short-sellers are forced to cover, but cannot do so in a single day due to volume constraints.

1. **Exact Scenario Trigger:** A positive earnings gap-up event where the pre-event Short Interest requires > 3 days of average volume to cover.
2. **Data-Layer Signal:** 
   * *Event:* yfinance earnings date (T). 
   * *Gap:* Polygon EOD open(T) > close(T-1) by > 5%. 
   * *Condition:* FINRA Short Interest (latest available PIT) / Polygon 20-day SMA Volume > 3.0 (Days to Cover).
3. **Entry/Exit:** Enter Market-On-Close (MOC) on day T. Exit MOC on T+5. 
4. **Persistence Mechanism:** Forced covering is volume-constrained. Short sellers facing margin calls cannot buy back their entire book on the open of day T without pushing prices to infinity. They must VWAP their covering over several days. This creates a mechanical, non-fundamental upward drift that persists precisely because liquidity providers demand a premium to sell to desperate shorts.
5. **Falsifiable Test:** Event study. 
   * *Treatment group:* Gap-ups with Days-to-Cover > 3. 
   * *Control group:* Gap-ups of the *exact same magnitude* but Days-to-Cover < 1. 
   * *Null:* The T+1 to T+5 return distributions are identical. 
   * *Metric:* Jensen’s CAPM-α net of 30bps over the 5-day hold. If the treatment group doesn't outperform the control group by > 50bps, the edge is just standard PEAD, not a SI squeeze.

### Hypothesis 2: The "Panic Bid" Insider Cluster (Macro-Dislocation × Form 4)
**The Concept:** Insider buying is notoriously noisy and heavily scheduled. However, *clustered* open-market buying during a macro volatility spike signals severe dislocation between the market's liquidity-driven panic and the firm's actual solvency.

1. **Exact Scenario Trigger:** The VIX spikes into the top decile of its 3-year rolling history, AND multiple unique insiders buy their own stock.
2. **Data-Layer Signal:**
   * *Macro State:* yfinance `^VIX` > 30 (or > 90th percentile of 3yr rolling).
   * *Micro Signal:* Postgres Form-4 parsing. >= 3 unique insiders file 'P' (Open Market Purchase) transactions within a 5-day window.
   * *Filter:* Exclude automatic 10b5-1 plans (identifiable via SEC footnote flags in the EDGAR text).
3. **Entry/Exit:** Enter MOC on the day the 3rd Form-4 is filed. Exit when VIX drops below its 50th percentile (regime normalization), or a hard T+21 days.
4. **Persistence Mechanism:** During VIX spikes, institutional funds de-risk mechanically (VaR shocks, margin calls), indiscriminately dumping shares regardless of fundamentals. Insiders, constrained by capital and blackout windows, only step in with personal cash when the mispricing is absurd and bankruptcy/liquidity risk is zero. Fast-money algos cannot arb this because their risk models explicitly forbid adding exposure during VaR shocks.
5. **Falsifiable Test:** Phase-averaged event study. 
   * *Null:* Clustered insider buys during VIX > 30 yield the same CAPM-α as clustered insider buys during VIX < 15. 
   * *Metric:* Measure Jensen's α against the S&P over the holding period. If the alpha is identical across VIX regimes, the "panic absorption" mechanism is false.

### Hypothesis 3: Intraday "Algo Exhaustion" on 8-K Filings (Microstructure Mean-Reversion)
**The Concept:** Natural Language Processing (NLP) algorithms often trigger indiscriminate selling on complex 8-K filings containing negative keywords, creating a temporary liquidity vacuum that human fundamental traders take minutes to hours to absorb.

1. **Exact Scenario Trigger:** An intraday 8-K filing that causes an immediate price crash, followed by volume exhaustion.
2. **Data-Layer Signal:**
   * *Event:* EDGAR 8-K timestamp (e.g., 10:30 AM EST).
   * *Initial Shock:* Polygon minute bars show a drop of > 3% from minute T to T+5.
   * *Exhaustion Condition:* Polygon minute bars from T+5 to T+15 show volume dropping below the pre-event 30-minute average, and price stabilizing (variance of minute closes drops).
3. **Entry/Exit:** Enter at T+15 minutes. Exit at the EOD closing cross.
4. **Persistence Mechanism:** Information processing latency. Fast algos read "Item 1.02 Termination of a Material Definitive Agreement" and short instantly. Fundamental analysts need 15-30 minutes to read the contract and realize the termination was mutual, expected, or immaterial. The fast algos run out of inventory, and the slow fundamental money bids the price back to VWAP.
5. **Falsifiable Test:** Intraday permutation test. 
   * *Null:* The T+15 to EOD drift is zero, indistinguishable from random 3% intraday drops that *lack* an SEC filing. 
   * *Metric:* Intraday excess return vs SPY, net of 30bps round-trip slippage (critical for minute-bar strats).

### Hypothesis 4: "News-less" Liquidation Absorption (Price Action × PIT Quality)
**The Concept:** Extreme single-name sell-offs without associated news are usually artifacts of forced institutional liquidation (e.g., a fund blowing up, index deletion, or margin cascades). If the underlying company is a high-quality cash generator, this is a pure liquidity-provision premium.

1. **Exact Scenario Trigger:** A stock drops > 15% in 3 days with NO earnings and NO SEC filings, while possessing top-quartile fundamentals.
2. **Data-Layer Signal:**
   * *Price Action:* Polygon EOD 3-day return < -15%.
   * *News Filter:* NO yfinance earnings within +/- 5 days. NO EDGAR 8-K/10-K/10-Q filed in the last 5 days.
   * *Quality Filter:* EDGAR PIT `fundamentals_pit.json` shows Operating Cash Flow (CFO) > 0 and ROA in the top 25% of the S&P 500.
3. **Entry/Exit:** Enter MOC on the 3rd day of the drop. Exit MOC on T+10.
4. **Persistence Mechanism:** The seller is price-insensitive (forced liquidation). Arbitrageurs hesitate to step in because they fear "asymmetric information" (insider trading ahead of bad news). By explicitly conditioning on *no filings* and *high PIT cash flow*, we isolate events where the asymmetric information risk is lowest, allowing us to safely harvest the liquidity premium.
5. **Falsifiable Test:** Event study + Phase averaging. 
   * *Null:* The T+1 to T+10 return of "News-less Drops + High Quality" is identical to "News-less Drops + Low Quality" (negative CFO). 
   * *Metric:* Jensen's α net of 30bps. If high-quality doesn't drastically outperform low-quality in this specific setup, the liquidation-absorption thesis is invalid (it's just a dead-cat bounce).

---

### Summary & Orthogonality
None of these are continuous cross-sectional factors. They will sit in cash 90% of the time and only fire when the specific structural dislocation occurs. 
* **H1** isolates the *mechanical volume constraint* of shorts, orthogonal to standard PEAD (which is purely informational). 
* **H2** isolates *macro panic*, orthogonal to standard insider-buying factors. 
* **H3** isolates *intraday NLP latency*, entirely orthogonal to our EOD daily pipeline. 
* **H4** isolates *forced liquidations*, acting as a discrete event-driven value play rather than a continuous value factor (dodging the EPS-TTM bug you mentioned, as it relies purely on CFO/ROA). 

All four are highly testable today using the exact `scripts/build_snapshot.py` and `scripts/run_factor_backtest.py` architecture, provided we write them as event-trigger scripts rather than 63-day rankers.


### GPT-5.5

Below are five **scenario-conditional** hypotheses that are computable with the stated stack. None is meant as another always-on cross-sectional factor; each only trades after a specific event/regime/microstructure state.

Common assumptions for all tests: liquid US common stocks only, price ≥ $5, ADV20$ ≥ $10m unless noted; adjusted Polygon bars; no lookahead; filing acceptance timestamps respected; subtract **30 bps round-trip**; report both event-level beta-adjusted returns and daily Jensen CAPM α vs SPY.

---

## 1. Distressed-stock insider “all-clear” cluster

### 1) Scenario trigger

A stock has suffered an **idiosyncratic capitulation**, then insiders make open-market purchases.

Trigger on date `t` when all are true:

- `resid_63 = R_i[-63,-1] - beta_i * R_SPY[-63,-1] <= -20%`
- `drawdown_126 = Close_t / max(Close[-126,-1]) - 1 <= -25%`
- A Form 4 accepted by EDGAR at or before `t` reports open-market purchase code `P`.
- Purchase cluster within last 10 calendar days:
  - Either ≥ 2 unique insiders buying, or CEO/CFO/chair buying.
  - Total purchase value ≥ max(`$100k`, `0.25% * ADV20$`).
- Exclude transaction codes `M`, `A`, option exercises, gifts, indirect-only tiny transfers.

Optional but pre-specified sub-sample if FINRA SI exists: require `days_to_cover = short_interest / ADV20_shares >= 5` or top-quintile SI/float.

### 2) Data-layer signal

Fields:

- Form 4 transaction code, shares, price, owner title, direct/indirect flag.
- Polygon daily close/volume.
- SPY daily returns.
- Latest PIT shares outstanding if using market-cap scaling; otherwise ADV scaling.

Formula:

```text
buy_value_10d = sum(shares_purchased * transaction_price) over Form-4 P buys in last 10 calendar days
B = log1p(buy_value_10d / ADV20$)

C = log1p(number_unique_buyers_10d)

D = abs(resid_63)

S = z(B) + 0.5*z(C) + 0.5*z(D)
```

If short-interest data is available:

```text
S = S + 0.5*z(days_to_cover)
```

Rank only among triggered events, not the whole universe.

### 3) Entry / exit

- Enter long at next open after the Form 4 acceptance timestamp is public.
- Primary hold: 20 trading days.
- Secondary robustness holds: 10 and 40 trading days.
- If multiple Form 4s occur during an active position, do not pyramid; reset holding clock only if new cluster value is larger than the original.

### 4) Persistence mechanism

Open-market insider buying is a costly, legally constrained signal. It is most informative **after a capitulation**, when public investors face uncertainty about solvency, litigation, demand collapse, or accounting quality. Insiders have superior information about whether the market has over-inferred disaster. The edge should persist specifically in this scenario because:

- Many funds cannot buy fresh crash names immediately due mandate/risk limits.
- Insider filings are delayed and under-monitored outside famous mega-caps.
- In high-short-interest cases, incremental good news can force cover demand.
- Signal capacity is limited; events are sparse and idiosyncratic.

This is not the live quality/PEAD core: it is an event-driven post-crash reversal conditional on insider behavior.

### 5) Falsifiable test

Event study from 2018+ Form 4 history.

Primary dependent variable:

```text
alpha_20 = R_i[t+1, t+20] - beta_i[-252,-21] * R_SPY[t+1, t+20] - 0.003
```

Tests:

1. Build all triggered events.
2. Equal-weight top-half by `S`; also test continuous forward-IC between `S` and `alpha_20`.
3. Matched-control null:
   - For each event, sample 20 pseudo-dates for the same ticker that also satisfy the idiosyncratic capitulation conditions but have no Form 4 purchase in ±30 days.
4. Permutation null:
   - Within each calendar year, permute insider-buy cluster labels across eligible capitulated firm-dates.
5. Report:
   - Mean/median `alpha_10`, `alpha_20`, `alpha_40`.
   - Clustered t-stat by event month.
   - Jensen α of overlapping-position portfolio.
   - Subsample excluding microcaps.
   - Subsample with FINRA high-SI condition where available.

Pass condition: `alpha_20` net of 30 bps is positive with permutation `p < 0.05`, and the sign is positive in at least two of three horizons: 10, 20, 40 days.

---

## 2. Broad-panic residual-liquidity reversal

### 1) Scenario trigger

A market-wide liquidation day, where ETF/de-risking flow likely overwhelms stock-level price discovery.

Market trigger on day `t`:

- `SPY_ret_t <= -2.25%`
- `VIX_pct_change_t >= +10%`
- `VIX_close_t >= 20`
- At least 75% of PIT S&P 500 constituents have negative daily returns.

Stock-level trigger:

- No earnings date in `[t-1, t+1]`.
- No firm-specific 8-K accepted on `t` or `t-1`.
- Compute pre-event beta over `[-252, -21]`.
- One-day residual:

```text
eps_i,t = r_i,t - beta_i * r_SPY,t
```

- Candidate longs are bottom decile of `eps_i,t` within the panic-day universe.
- Require abnormal volume:

```text
vol_z = zscore(log(volume_t / median(volume[-20,-1])), lookback=252)
vol_z >= 1.0
```

- Require close near low:

```text
CLV = (Close - Low) / max(High - Low, small_eps)
CLV <= 0.25
```

### 2) Data-layer signal

Fields: Polygon daily OHLCV, SPY, VIX, earnings dates, EDGAR 8-K timestamps.

Signal among candidates:

```text
S = rank_pct(-eps_i,t)
    + 0.30 * rank_pct(vol_z)
    + 0.20 * rank_pct(0.25 - CLV)
```

Higher `S` = stronger forced-liquidation candidate.

### 3) Entry / exit

- Enter long at next open `t+1`.
- Hold 5 trading days, exit close `t+5`.
- Primary portfolio: equal-weight top 20 or top decile names by `S`.
- Risk-control version: short SPY notional equal to ex-ante portfolio beta, rebalanced daily during the 5-day hold.
- No discretionary stop in the test; fixed exit only.

### 4) Persistence mechanism

On broad panic days, selling pressure is often **flow-driven**, not firm-specific: ETF redemptions, vol-target de-risking, margin calls, and risk-parity deleveraging hit baskets. Liquidity providers require high compensation when VIX spikes, so the most aggressively sold residual losers can overshoot. This is not a generic reversal factor; it only trades when market-wide liquidity provision is impaired.

Why not arbed away:

- The trade requires buying when risk budgets are actively shrinking.
- It has crash-tail risk and ugly mark-to-market.
- Capacity is episodic.
- Many managers cannot add gross exposure immediately after large VIX shocks.

### 5) Falsifiable test

Use all panic days from 2018+.

Primary event return:

```text
alpha_5 = R_i[t+1 open, t+5 close]
          - beta_i * R_SPY[t+1 open, t+5 close]
          - 0.003
```

Tests:

1. Cross-sectional forward-IC between `S` and `alpha_5` within each panic day.
2. Event portfolio: long top decile by `S`, beta-hedged with SPY.
3. Permutation null:
   - Within each panic day, randomly permute `S` across eligible stocks 10,000 times.
   - Preserve the number of longs per day.
4. Crisis-cluster robustness:
   - Leave-one-crisis-out: 2018 Q4, COVID, 2022 inflation selloff, later VIX shocks.
5. Compare against same signal on non-panic high-down days:
   - SPY down days that fail the VIX/breadth trigger.

Pass condition: beta-hedged 5-day Jensen α net of 30 bps is positive, permutation `p < 0.05`, and not entirely driven by a single crisis cluster.

---

## 3. Failed earnings-gap opening-drive fade

This one is intentionally earnings-adjacent but **not PEAD**. It trades an intraday microstructure failure after the earnings gap, not the medium-horizon drift in the direction of surprise.

### 1) Scenario trigger

First regular session after a reported earnings date.

At open on session `t`:

```text
gap = Open_t / Close_{t-1} - 1
```

Trigger:

- `abs(gap) >= max(4%, 1.25 * ATR20 / Close_{t-1})`
- First-hour relative volume:

```text
RVOL_60 = volume[09:30-10:30] / median(volume[09:30-10:30] over prior 20 same sessions)
RVOL_60 >= 2.5
```

Opening-drive failure by 10:30:

For gap up:

- `Price_10:30 < Open_t`
- `Price_10:30 < VWAP_09:30-10:30`
- `Price_10:30 < Low_09:30-09:45`

For gap down:

- `Price_10:30 > Open_t`
- `Price_10:30 > VWAP_09:30-10:30`
- `Price_10:30 > High_09:30-09:45`

### 2) Data-layer signal

Fields: yfinance earnings dates, Polygon minute bars, Polygon daily ATR.

Let:

```text
dir = sign(gap)
drive_fail = -dir * (Price_10:30 - Open_t) / ATR20_dollars
```

Signal:

```text
S = abs(gap) * log1p(RVOL_60) * drive_fail
```

Higher `S` = stronger failed gap.

### 3) Entry / exit

- Enter at 10:31 in direction opposite the gap.
  - Gap up failure → short.
  - Gap down failure → long.
- Primary exit: 15:55 same day.
- Secondary robustness exit: next day close.
- No stop in primary research test; include optional 0.75 ATR stop only as robustness, not as the main reported result.

### 4) Persistence mechanism

Earnings gaps attract crowded overnight repricing: retail orders, news-driven momentum, stop-outs, and analyst/PM reaction at the open. The first hour reveals whether real institutional demand supports the gap. If a large, high-volume gap cannot extend and reverses through VWAP/opening range, the marginal flow has likely exhausted.

Why it can persist:

- Very short horizon; capacity limited.
- Requires minute-level execution and event alignment.
- Many slower investors trade after reading headlines, while faster liquidity providers demand large spread/impact compensation during earnings volatility.
- It is conditional on **gap failure**, not a generic earnings drift.

### 5) Falsifiable test

Use all earnings sessions with available minute bars from 2018+.

Primary return:

```text
alpha_intraday = position_return[10:31,15:55]
                 - beta_i * SPY_return[10:31,15:55]
                 - 0.003
```

Where beta is estimated from daily returns `[-252,-21]`.

Tests:

1. Event portfolio equal-weight all triggered failures; cap one trade per ticker per earnings event.
2. Forward-IC between `S` and intraday beta-adjusted return.
3. Permutation null:
   - Within each earnings date bucket, permute failure labels among large-gap earnings events.
   - Preserve gap direction and gap-size decile.
4. Placebo:
   - Same large-gap rule on non-earnings days.
   - Same earnings gaps without opening-drive failure.
5. Robustness:
   - Entry at 10:45 instead of 10:31.
   - Exit same day and next close.
   - Separate gap-up shorts and gap-down longs.

Pass condition: same-day CAPM-adjusted α net of 30 bps is positive with permutation `p < 0.05`, and the effect is stronger in failed-drive earnings gaps than in placebo non-earnings gaps.

---

## 4. Accounting-integrity 8-K delayed repricing short

### 1) Scenario trigger

A company files an 8-K indicating accounting integrity risk.

Trigger on EDGAR 8-K acceptance when any is true:

- Item 4.02: non-reliance on previously issued financial statements.
- Item 4.01 with negative language:
  - “resigned”
  - “dismissed”
  - “disagreement”
  - “reportable event”
  - “adverse opinion”
  - “scope limitation”
- 8-K text contains new accounting-control phrases:
  - “material weakness”
  - “internal control over financial reporting”
  - “restatement”
  - “should no longer be relied upon”
  - “audit committee concluded”

Exclude:

- 8-K filed within ±1 trading day of earnings.
- Initial reaction already catastrophic:

```text
AR_0_1 = R_i[filing close to next close] - beta_i * R_SPY
AR_0_1 <= -15%
```

The intent is to catch **underpriced accounting risk**, not chase a fully repriced collapse.

### 2) Data-layer signal

Fields: EDGAR 8-K text/items, Polygon daily bars, SPY.

Severity score:

```text
severity =
    3 * I(Item 4.02)
  + 2 * I(auditor resignation/disagreement/reportable event)
  + 1 * I(material weakness phrase)
  + 1 * I(restatement / no-longer-rely phrase)
  + 1 * I(NT 10-K or NT 10-Q filed in prior 90 days, if available)
```

Underreaction adjustment:

```text
underreaction = max(0, AR_0_1 + 0.05)
```

Final short signal:

```text
S = severity + 2 * underreaction
```

Higher `S` = stronger short.

### 3) Entry / exit

- Enter short at next open after filing is public and after measuring initial reaction window.
- Primary exit: 20 trading days.
- Secondary: 63 trading days.
- If a corrective restated filing or auditor resolution appears before exit, close at next open after that filing.

### 4) Persistence mechanism

Accounting-integrity events change the distribution of future cash flows, litigation risk, financing access, and institutional ownership eligibility. The market often underreacts because:

- 8-K language is legalistic and low-attention.
- Many investors wait for restated numbers before acting.
- Some holders are forced sellers only after internal risk/legal review.
- Shorting is risky and borrow-constrained precisely in names with accounting uncertainty.

This is not a quality factor. It trades a discrete disclosure shock.

### 5) Falsifiable test

Event study from 2018+ EDGAR 8-K corpus.

Primary short alpha:

```text
short_alpha_20 = -1 * R_i[entry, entry+20]
                 + beta_i * R_SPY[entry, entry+20]
                 - 0.003
```

Tests:

1. All accounting-integrity 8-Ks satisfying trigger.
2. Rank by `S`; test top half vs bottom half.
3. Matched controls:
   - Other 8-Ks from same sector/year/market-cap decile with no accounting-integrity language.
4. Permutation null:
   - Within all 8-K filing dates, randomly assign accounting-shock labels while preserving sector/year counts.
5. Robustness:
   - Exclude stocks below $1bn market cap.
   - Exclude events with `AR_0_1 < -8%`.
   - Test 5, 20, 63 trading-day horizons.

Pass condition: short-side 20-day CAPM α net of 30 bps is positive with permutation `p < 0.05`, and remains positive excluding microcaps.

---

## 5. Unpriced 10-K risk-factor novelty short

### 1) Scenario trigger

Annual 10-K contains a large new risk disclosure that the stock does not immediately price.

Trigger on 10-K acceptance date `t`:

- Current and previous 10-K both have extractable Item 1A Risk Factors.
- Not within ±2 trading days of earnings.
- Initial market reaction is muted:

```text
abs(R_i[t, t+1] - beta_i * R_SPY[t, t+1]) <= 3%
```

- Prior tape is complacent:

```text
resid_63 = R_i[-63,-1] - beta_i * R_SPY[-63,-1] >= 0
```

- Risk-factor novelty is extreme.

### 2) Data-layer signal

Fields: EDGAR 10-K text, Polygon daily bars, SPY.

Compute Item 1A text features using only filings known before `t`.

Text features:

```text
novelty = 1 - cosine_similarity(vector(Item1A_current), vector(Item1A_previous))
```

Use hashing vectorizer or PIT TF-IDF fit only on historical filings.

Negative new-risk phrase density:

Count current Item 1A sentences containing terms that were absent from prior Item 1A:

```text
risk_terms = [
  "material weakness",
  "substantial doubt",
  "going concern",
  "default",
  "covenant",
  "liquidity",
  "impairment",
  "investigation",
  "subpoena",
  "litigation",
  "cybersecurity",
  "data breach",
  "ransomware",
  "customer concentration",
  "supplier",
  "recall",
  "tariff",
  "regulatory approval",
  "adverse effect"
]
```

```text
neg_new_density = new_negative_sentences / total_sentences
length_growth = log(words_current / words_previous)
```

Scenario condition:

- `novelty` in top 5% of same year/SIC2.
- `neg_new_density` in top quartile.

Signal:

```text
S = z(novelty) + z(neg_new_density) + 0.5*z(length_growth) + 0.5*z(resid_63)
```

Higher `S` = stronger short candidate.

### 3) Entry / exit

- Enter short at next open after 10-K acceptance.
- Primary exit: 42 trading days.
- Secondary exit: 63 trading days or next earnings date, whichever comes first.
- Do not trade if another major 8-K or earnings event occurs before entry.

### 4) Persistence mechanism

Risk-factor changes are legally meaningful but low-salience. A new or heavily expanded risk section can reveal litigation, customer concentration, covenant, cybersecurity, regulatory, or going-concern issues that were not prominent in the earnings release. The delayed effect should be strongest when the stock had a complacent prior tape and the immediate filing reaction is small.

Why it persists:

- 10-Ks are long, slow to parse, and often filed after the main earnings narrative.
- Many investors rely on summaries and may not diff annual risk language.
- Legal disclosure changes are intentionally cautious and not framed as “news.”
- The edge is sparse and text-processing heavy.

This is orthogonal to the live PEAD/quality core because it uses **textual disclosure deltas**, not accounting ratios or earnings drift.

### 5) Falsifiable test

Event study over all 10-Ks from 2018+.

Primary short alpha:

```text
short_alpha_42 = -1 * R_i[entry, entry+42]
                 + beta_i * R_SPY[entry, entry+42]
                 - 0.003
```

Tests:

1. Compare triggered top-5% novelty events to all other 10-Ks.
2. Matched controls:
   - Same SIC2, year, market-cap decile, prior 63-day residual-return decile.
3. Permutation null:
   - Within each SIC2/year bucket, permute the novelty scores across 10-K filing dates.
4. Placebo:
   - High novelty but no negative-new-risk phrases.
   - Negative text in non-risk sections only.
5. Robustness:
   - 20, 42, 63-day horizons.
   - Exclude companies with same-day 8-Ks.
   - Exclude stocks below $1bn market cap.

Pass condition: 42-day short CAPM α net of 30 bps is positive with permutation `p < 0.05`, survives matched controls, and is not concentrated in one sector/year.

---

## My implementation priority

1. **Failed earnings-gap opening-drive fade** — best sample size, clean minute-level falsification, most orthogonal to daily factor core.  
2. **Broad-panic residual-liquidity reversal** — strong economic mechanism, but few regimes; must pass leave-one-crisis-out.  
3. **Distressed insider all-clear cluster** — plausible and testable; especially interesting with short-interest overlay.  
4. **Accounting-integrity 8-K short** — likely high signal per event, but sparse and shorting/borrow practicalities matter.  
5. **10-K risk-factor novelty short** — potentially valuable, but highest NLP/specification risk; test only after simple event strategies above.


---

## Phase 2 — Cross-critiques


### Opus

# Opus critique: cutting through the panel

I'll be adversarial. Several proposals are dressed-up versions of known-arbed effects or have falsification tests that won't isolate the claimed mechanism. A few are genuinely worth building.

---

## Gemini's proposals

### H1 — Trapped Bear (PEAD × SI × Days-to-Cover) — **SURVIVES, modified**
**Verdict:** Computable, mechanism is real, test is good. The control-group design (same-magnitude gap, low DTC) is the right falsification — it explicitly subtracts the PEAD baseline, isolating the squeeze component.

**Caveats Gemini glossed:**
- FINRA SI is bi-monthly with ~2-week reporting lag. The "pre-event SI" is stale by 1–14 days. That's actually fine for the mechanism (positioning doesn't unwind that fast) but must be modeled honestly.
- 30 bps is **too generous** for the high-DTC subsample. These names have wide spreads and tape impact precisely *because* they're squeeze-prone. Use 50 bps round-trip minimum.
- Sample size will be small. High-DTC + earnings gap + S&P 500ish liquidity ≈ tens of events/year. Power test before celebrating.

### H2 — Panic Bid Insider Cluster — **KILL as specified, salvageable**
**Verdict:** The exit rule ("hold until VIX < 50th pct or T+21") **smuggles in a regime-timing bet** that contaminates the test. You can't tell whether α came from insider signal or from VIX mean-reversion beta.

**Also:** "Exclude 10b5-1 via SEC footnote flags" — Form 4 has an explicit 10b5-1 checkbox (added 2022), but pre-2022 it's footnote text parsing, inconsistent. Acknowledge this.

**Salvage:** Fixed T+20 hold, no VIX-conditional exit. Then test cleanly.

### H3 — 8-K Algo Exhaustion (minute bars) — **KILL**
**Verdict:** This is the most arbed corner of the market. Every HFT shop has an 8-K NLP pipeline. Claiming "humans take 15–30 min to read" in 2026 is generous by ~14 minutes.

Worse: 30 bps round-trip on a minute-bar trade after a 3% crash is **wildly optimistic**. Real spread + impact on a stressed name post-shock is 50–150 bps. The test's pass bar is set where the strategy can't fail honestly.

Also, our "event-only minute-bar cache" likely doesn't cover every 8-K timestamp historically — coverage gap = selection bias.

### H4 — News-less Liquidation Absorption — **SURVIVES, with skepticism**
**Verdict:** Computable, orthogonal, decent mechanism. But the falsification test (high-CFO vs low-CFO) is weak — it only tests whether quality moderates dead-cat-bounce, not whether the strategy beats SPY on a risk-adjusted basis. Add: matched-control of -15% drops *with* 8-Ks, to confirm the news-filter is doing real work.

**Hidden risk:** "No 8-K" can mean "8-K coming Monday" (delisting from index, fund failure announced after close). Selection on absence of news inside a forward window is fine; on absence at decision time is honest but may not match the mechanism Gemini described.

---

## GPT-5.5's proposals

### #1 — Distressed insider all-clear cluster — **SURVIVES, strongest of the panel**
Cleanest spec on the table. The matched-control null (same-ticker pseudo-dates with capitulation but no insider buy) is exactly right — it controls for the post-capitulation reversal baseline, isolating the insider signal. Permutation within calendar year handles regime confounding.

One critique: requiring `buy_value ≥ 0.25% * ADV20$` for S&P names filters most insider buys out (insider buys are typically 0.01–0.1% of ADV). Either drop this floor or pre-specify it'll mostly fire on smaller-cap names.

### #2 — Broad-panic residual-liquidity reversal — **KILL as specified**
**The fatal flaw:** Cross-sectional residual-loser reversal on panic days is **well-documented since Lehmann (1990) and Khandani-Lo (2007)**. The 1-day reversal on high-vol days is the textbook example of a strategy that *was* alpha and is now liquidity-provision compensation for HFT market-makers.

GPT-5.5's mechanism ("flow-driven selling, capacity episodic") is correct — but the capacity is filled by Citadel and Two Sigma, not us, with millisecond execution. We enter at next-day open, after the overnight repricing.

**Sample size problem #2:** Trigger requires SPY ≤ -2.25% AND VIX +10% AND VIX ≥ 20 AND breadth ≥75%. That's maybe 20–40 days since 2018, dominated by COVID + 2022. Leave-one-crisis-out will gut it.

### #3 — Failed earnings-gap opening-drive fade — **KILL**
GPT-5.5 ranked this #1. I'd kill it.

**Problems:**
1. **30 bps round-trip on a minute-entry, same-day-exit trade in an earnings name is fantasy.** Earnings-day spreads are 2–5x normal. Realistic cost is 40–80 bps. The proposed α budget is consumed by execution.
2. **Polygon minute bars on $29 tier** cover ~5 years and have known consolidation/tape quality issues vs SIP. VWAP from these bars is approximate.
3. **The setup is the most-studied intraday pattern in retail-quant land** — opening range breakout/failure on earnings has been published, productized (TradeIdeas), and arbed. Asking "does opening-drive failure mean-revert intraday?" in 2026 is asking a question every prop desk solved a decade ago.

The falsification test is rigorous, which makes it dangerous — it'll find statistical significance on a sample that won't survive paper-trade slippage.

### #4 — Accounting-integrity 8-K short — **SURVIVES, with capacity caveat**
Best of GPT-5.5's NLP plays. Mechanism is real (post-restatement drift documented in Hribar/Jenkins, Files et al.). Item 4.02 is rare, severe, and specifically known to be slowly absorbed.

**Caveats:**
- **Borrow cost** on these names is the killer. A post-restatement microcap can cost 20–200% to borrow. The 30 bps assumption is irrelevant if the locate fee is 5% over the hold.
- Must require ≥$1bn market cap (GPT-5.5 lists this as robustness; make it primary).
- Sample is small (Item 4.02 fires ~50–100x/year market-wide, far fewer in our universe).

### #5 — 10-K risk-factor novelty short — **KILL for now**
The mechanism is plausible, but: NLP specification space is huge (vectorizer choice, term list, similarity metric), the trigger conjunction is narrow (top-5% novelty × top-quartile neg-density × muted reaction × complacent prior), and the 42-day short horizon makes the test sensitive to drift in unrelated factors. **Too many researcher degrees of freedom**. Cohen-Malloy-Nguyen (2020) found this effect but with much larger samples and economist-curated term lists. Park until simpler events are built.

---

## My own proposals — self-critique

I haven't been given mine in this turn, so I'll be honest: the panel's strongest ideas above are likely stronger than what I'd add. I'd resist the temptation to propose more.

---

## The shortlist — 3 ideas worth building first

Ranked by **edge × testability × capacity within our data layer**:

### 1. Distressed insider all-clear cluster (GPT-5.5 #1)
Best spec on the panel. Cleanest matched-control falsification. Mechanism (informed buying after forced-seller exhaustion) is theoretically anchored and empirically supported (Cohen-Malloy-Pomorski 2012, Jeng-Metrick-Zeckhauser 2003). Build first.

### 2. Trapped Bear: PEAD × Days-to-Cover (Gemini H1)
The DTC control vs same-magnitude-gap-low-DTC is a *genuine* mechanism isolation. Orthogonal to live PEAD (which doesn't condition on positioning). Squeeze mechanics are real and recur (GME, AMC, regional banks 2023, etc.). Use 50 bps cost assumption, not 30.

### 3. Accounting-integrity 8-K short (GP


### Gemini

Here is my ruthless critique of the panel’s proposals, strictly enforced against our data layer, the known anti-patterns, and market microstructure reality. 

### 1. Critique of Opus’s Proposals

*   **1. Insider cluster-buy into a fresh 52-week-low drawdown:** **SURVIVES.** Both you and GPT-5.5 independently converged on this, and for good reason. Generic insider-buying is an arbed anti-pattern, but gating it by a *deep idiosyncratic drawdown* changes the microstructure. You are isolating events where the marginal public trader is a forced/panicked seller, and the insider is stepping in with personal cash as the liquidity provider of last resort. It is perfectly computable on our EDGAR Form-4 + Polygon data.
*   **2. Post-8K-guidance-cut overreaction reversal:** **KILL.** You are trying to catch a falling knife in front of a steamroller. The academic PEAD literature explicitly shows that guidance cuts cause *multi-month downward drift*. The "mandate-bound flow exhaustion" at T+5 is immediately replaced by fundamental managers slowly sizing down over the quarter. 
*   **3. Crowded-short squeeze on FINRA short-interest spike:** **KILL (Constraint Violation).** You proposed a walk-forward test from 2019–2024. Read the brief's data constraints: we only have **~1.5 years** of FINRA short-interest data in Postgres. You cannot run a 5-year backtest on data we do not possess.
*   **4. Earnings-day IV-crush realized-vol fade:** **KILL.** Your prompt cut off, but more importantly, the brief explicitly bans strategies requiring options data/dealer-gamma. 

### 2. Critique of GPT-5.5’s Proposals

*   **1. Distressed-stock insider “all-clear” cluster:** **SURVIVES.** (Merged with Opus #1). Excellent addition of the residual-return beta-adjustment to ensure the crash is idiosyncratic, not just a broad market beta-drawdown.
*   **2. Broad-panic residual-liquidity reversal:** **SURVIVES.** This is a highly defensible, purely flow-driven macro setup. When VIX spikes >20% and SPY dumps, risk-parity and vol-target funds puke indiscriminately. Buying the highest-volume residual losers is classic liquidity provision. It is sparse (maybe 15-20 days in 5 years), but it serves as a perfect tactical cash-deployment sleeve when the main system is gated.
*   **3. Failed earnings-gap opening-drive fade:** **KILL (Microstructure Fantasy).** You are proposing an intraday stat-arb strategy (enter 10:31 AM, exit 15:55) on a stock that just gapped 4% on earnings, and you are assuming a **30 bps round-trip cost**. That is dangerously naive. At 10:31 AM on a massive earnings gap, spreads are wide, book depth is hollowed out, and market-impact slippage will easily exceed 100-150 bps. 
*   **4. Accounting-integrity 8-K delayed repricing short:** **KILL.** While the mechanism is solid, accounting blowups (Item 4.02) are extremely rare in the S&P 500 / Russell 1000 universe. If you drop into micro-caps to find sample size, borrow costs and locate-constraints will destroy the paper alpha.
*   **5. Unpriced 10-K risk-factor novelty short:** **KILL (Academic Anti-Pattern).** This is a direct rip-off of the well-known 2020 paper *"Lazy Prices"* (Cohen, Malloy, Nguyen). It is heavily arbed by NLP quant pods. Furthermore, diffing raw 10-K Item 1A text across years is a massive infrastructure build fraught with lookahead/parsing bugs, which we don't need to take on.

---

### 3. Gemini's Proposal: The Highest-Leverage Fix

You both proposed idiosyncratic stock-level events. I am going to propose a direct, structural fix to the biggest documented failure in the live system's architecture: **"Regime whipsaw cost -6.46% α... parked the book in cash through SPY +6.11%."** 

Moving-average regime gates (like our 200-SMA / 75-SMA) provide slow-bear insurance, but they structurally fail in V-shaped recoveries. We don't need a new factor; we need a conditional scenario-override to bypass the SMA latency.

**"The V-Shape Whipsaw Override: VIX-Crush into Quality-Beta"**
*   **Scenario trigger:** The live system is currently REGIME GATED (parked in cash because SPY < 200-SMA). Suddenly, SPY prints a 10-day return ≥ +4% AND yfinance `^VIX` closes at least 20% below its trailing 20-day high. 
*   **Signal (Computable now):** Do not wait for the 75-SMA crossover. Immediately run the existing EDGAR PIT Quality factor. Filter to the top quintile of Quality, then **sort descending by trailing 63-day SPY Beta**. 
*   **Entry/Exit:** Enter the top 15 names equal-weight at the next open. Hold until either (a) SPY crosses above the 75-SMA (handing control back to the normal 63-day live core), or (b) SPY closes below the low of the trigger day (failed recovery, stop out).
*   **Persistence mechanism:** When panic breaks (the VIX crush), systemic risk-parity funds, CTA short-covering, and dealer hedging mechanically bid up the market. High-beta, high-quality names act as a "rubber band," capturing the maximum upside of this mechanical re-leveraging. This is not a stock-picking alpha; it is a structural flow-capture that patches the exact blind spot of our trend-following gate.
*   **Falsifiable test:** Isolate all days 2018+ where SPY < 200-SMA. Trigger the VIX-crush event. Compute the forward Jensen's α and absolute return of the Quality-Beta basket vs. staying in cash (the default system behavior) up to the 75-SMA crossover. *Ship iff* this override adds > +3% absolute return over cash during whipsaw windows, with a max drawdown < 0.5x the SPY drawdown.

---

### 4. The Final Consensus Shortlist (Top 3 to Implement)

These three survive scrutiny, use only data we already have, do not overlap with the live PEAD/Quality core, and target distinct market states.

1.  **The Distressed-Stock Insider Cluster (Opus #1 + GPT-5.5 #1)**
    *   *Why:* The cleanest idiosyncratic event edge. Gating insider buys with a severe beta-adjusted drawdown isolates forced-liquidation events where insiders are the informed liquidity providers. Completely orthogonal to the live core.
2.  **The V-Shape Whipsaw Override (Gemini)**
    *   *Why:* The highest-leverage fix for the portfolio. It directly solves the -6.46% whipsaw drag using existing data and factors (Quality + Beta), turning a known system weakness (crash latency) into a tactical offensive weapon.
3.  **Broad-Panic Residual-Liquidity Reversal (GPT-5.5 #2)**
    *   *Why:* A pure microstructure trade. When the VIX spikes and broad breadth collapses, firm-specific pricing breaks down. Buying the highest-volume residual losers is a highly defensible, episodic 5-day cash-deployment strategy that thrives exactly when the live system's 63-day cadence is too slow to react.


### GPT-5.5

## Bottom line

**True survivors from Opus/Gemini:**  
1. **Opus #1 — Insider cluster-buy into fresh drawdown:** survives, with test hardening.  
2. **Opus #2 — Post-guidance-cut overreaction reversal:** survives only as a research candidate, with a much stricter control/null.  
3. **Gemini #1 — “Trapped Bear” PEAD × short-interest:** not a genuinely new edge, but survives as a **diagnostic PEAD/SI overlay** if we accept the short FINRA history limitation.

**Kills:**  
- **Opus #3** as specified: not computable historically on current SI data; needs float / longer SI history.  
- **Opus #4**: truncated/underspecified; “IV crush” not observable without options; likely PEAD/reversal in disguise.  
- **Gemini #2**: too sample-starved and crisis-beta-contaminated.  
- **Gemini #3**: intraday SEC-filing mean reversion is latency-arbed and not reliably executable/testable with minute bars only.  
- **Gemini #4**: “news-less” is not computable without a real news feed; also quality + short-term reversal in disguise.

My top 3 to implement first across all ideas:

1. **Opus #1: cluster insider buying after deep idiosyncratic drawdown.**  
2. **My own: adverse-material 8-K underreaction short basket** — Item 4.02 / 2.04 / 1.02 / auditor/CFO resignation / material impairment drift.  
3. **Opus #2: guidance-cut T+5 reversal**, but only after replacing the weak null with matched-path controls.

If forced to stay only within the submitted proposals, replace my #2 with **Gemini #1**, but I would treat it as a PEAD interaction study, not a new standalone strategy.

---

# Critique of Opus proposals

## Opus #1 — Insider cluster-buy into fresh 52-week-low drawdown

### Verdict: **SURVIVES**

This is the cleanest proposal from either panelist.

### Computability

Mostly computable now:

- **Drawdown / 63-day lows:** Polygon EOD, yes.
- **Form 4 open-market purchases:** Postgres insider history / EDGAR Form 4, yes.
- **Distinct filers:** yes if `reportingOwnerCik` is parsed.
- **Officer/director vs 10% owner:** usually available in Form 4 owner relationship flags, but parsing needs care.
- **Entry at next open after second filing:** computable using EDGAR accepted timestamp.

Caveats:

- Do **not** use transaction date as the event date. Form 4s are filed up to two business days after trade date. The tradable signal is the **filing acceptance timestamp**.
- “PIT R3000” is probably not available. Use:
  - PIT S&P 500 if we want strict universe discipline, or
  - all Polygon common stocks passing liquidity/price filters if we accept no index-membership filter.
- The $250k threshold may be too low for mega-caps and too high for small caps. Freeze it initially, but test robustness across dollar/ADV-scaled variants without tuning.

### Is it an anti-pattern?

Not obviously.

Generic insider buying is known and partially arbed. But **clustered discretionary open-market buying after a large drawdown** is a more specific scenario:

- insiders buying against visible negative price action;
- multiple independent insiders;
- personal capital, not grants/exercises;
- post-drawdown panic/liquidity regime.

That is sufficiently different from the live m/q/v + PEAD core and from the known-null factor lab.

### Does the test isolate scenario edge?

Good start, but needs strengthening.

Opus’s matched drawdown-bucket permutation is the right direction. I would require controls matched on:

- event date / month;
- drawdown bucket;
- prior 20d/60d return;
- dollar ADV / liquidity;
- beta;
- sector;
- VIX bucket or market regime.

Also test:

- one-insider buy versus two-plus-insider cluster;
- insider dollar-size monotonicity;
- director-only versus officer/CEO/CFO purchases;
- leave-COVID-out and leave-2022-out.

### Final judgment

**Implement.** This is the highest-quality submitted idea.

---

## Opus #2 — Post-8-K guidance-cut overreaction reversal, T+5 to T+20

### Verdict: **PROVISIONAL SURVIVOR**

Promising but fragile. This can easily become generic “catch the falling knife after bad news” unless the test is tightened.

### Computability

Mostly computable:

- **8-K Item 2.02 / 7.01:** EDGAR, yes.
- **Guidance-cut regex:** yes, but false positives will matter.
- **Same-day / five-day return:** Polygon EOD, yes.
- **Minute bars to confirm gap/open flush:** possible if the minute cache is available/fetchable for the events.

Important timestamp issue:

Many guidance updates are filed after market close. The “same-day return” must be mapped to the correct **event session**:

- if filing accepted before open or during market hours: event day = same session;
- if filing after close: event day = next session.

Otherwise the test will mix pre-announcement and post-announcement returns.

### Is it an anti-pattern?

Risky.

This could be:

- generic short-term reversal after extreme negative returns;
- earnings-announcement reversal;
- PEAD with opposite sign;
- small-cap liquidity bounce;
- beta rebound after a crash.

The mechanism is plausible — forced selling after lowered guidance — but the proposed signal is close to a known crowded setup.

### Does the proposed test isolate the edge?

Not enough.

The proposed null — random 8-K filing dates for the same name — is too weak. It controls for ticker behavior but not for:

- a −10% crash;
- a guidance cut;
- five-day collapse path;
- liquidity shock;
- earnings proximity.

Better controls:

1. **Matched-path control:** same stock universe, same period, same D0 and D0→D+5 return bucket, but no guidance-cut language.  
2. **Negative 8-K control:** adverse 8-Ks with similar initial selloff but not guidance cuts.  
3. **Guidance-cut non-extreme control:** guidance cuts without bottom-decile follow-through.  
4. **Permutation within event month:** avoid macro-regime contamination.

The falsifier should be the interaction:

> T+5 reversal must be stronger for guidance-cut extreme-flow events than for equally severe non-guidance crashes.

Not merely positive after crashes.

### Final judgment

**Survives as research, not yet as a shippable strategy.** Worth implementing after Opus #1 because the data exists and the event count should be larger than pure insider clusters.

---

## Opus #3 — Crowded-short squeeze on SI spike + price stabilization

### Verdict: **KILL AS SPECIFIED / DEFER WITH NEW DATA**

### Computability

Not as written.

Problems:

1. **FINRA short-interest history is only ~1.5 years.**  
   Opus proposes 2019–2024. We cannot run that test on current data.

2. **`short_interest / float` requires float.**  
   Float is not in the stated data layer. EDGAR shares outstanding is not free float. Polygon EOD does not give float.

3. **Short-interest publication lag matters.**  
   Need exact settlement date and dissemination date. Signal must use only reports public by entry date.

4. **High-SI small caps have borrow/halts/gap-risk problems.**  
   We lack borrow cost and hard-to-borrow availability.

### Is it an anti-pattern?

High short interest / squeeze setups are extremely crowded and path-dependent. Without:

- borrow cost;
- options positioning;
- float;
- securities lending data;
- catalyst classification;

this is likely a meme/squeeze lottery, not a repeatable edge.

The vol-contraction interaction is a decent idea, but not enough to overcome data limitations.

### Does the test isolate the edge?

The proposed interaction test — SI spike with versus without vol contraction — is directionally right.

But because current SI history is too short, any “success” would likely be one or two meme episodes.

### Final judgment

**Kill for current implementation.** Revisit only if we buy/build longer SI + float/borrow data. A watered-down DTC version can be explored, but it should not enter the implementation shortlist.

---

## Opus #4 — Earnings-day IV-crush realized-vol fade

### Verdict: **KILL**

The proposal is truncated, but based on the title and partial description, the likely issues are severe.

### Computability

We do not have options data. Therefore we cannot observe:

- implied volatility;
- IV crush;
- skew;
- straddle pricing;
- dealer positioning;
- option volume/open interest.

Using realized range/absolute return as a proxy for “IV crush” is not the same thing.

### Is it an anti-pattern?

Likely yes.

If the trade is directional after earnings, it is probably one of:

- PEAD;
- post-earnings reversal;
- overnight-return effect;
- realized-vol mean reversion.

Those are either already central to the live system or in the known-null neighborhood.

### Does the test isolate the edge?

Not enough information. But without options data, the proposed mechanism cannot be directly tested.

### Final judgment

**Kill.** If someone wants an earnings-volatility trade, we need options data. Otherwise this is just another post-earnings price-action variant.

---

# Critique of Gemini proposals

## Gemini #1 — “Trapped Bear” PEAD × Days-to-Cover

### Verdict: **SURVIVES ONLY AS A PEAD/SI DIAGNOSTIC, NOT AS A NEW STRATEGY**

### Computability

Partially computable:

- **Earnings date:** yfinance, yes, though timestamp quality is imperfect.
- **Gap-up:** Polygon open vs prior close, yes.
- **Days-to-cover:** FINRA short interest / Polygon ADV, yes.
- **Entry MOC on event day:** possible only if the gap is observed at the open.

Timestamp caveat:

If earnings are after close on date T, the tradable gap is on T+1. The strategy must define event day as the **first session whose open reflects the earnings information**, not blindly use the yfinance earnings date.

Major limitation:

- FINRA history is only ~1.5 years, so the sample is likely underpowered.

### Is it an anti-pattern?

It is explicitly **PEAD × short interest**.

That does not make it useless, but it violates the spirit of “not another PEAD re-skin.” The live system already has a PEAD overlay. This would be an interaction/position-sizing overlay, not a genuinely orthogonal strategy.

That said, the mechanism is real enough:

- positive surprise/gap traps shorts;
- days-to-cover creates mechanical buying pressure;
- covering may persist for several days.

### Does the test isolate the scenario edge?

Gemini’s proposed test is actually one of the better ones:

- treatment: gap-ups with high DTC;
- control: same-magnitude gap-ups with low DTC;
- measure T+1 to T+5 incremental alpha.

That directly asks whether high short interest adds something beyond ordinary PEAD.

I would harden it by matching on:

- gap size;
- pre-event beta;
- ADV/liquidity;
- market cap proxy / dollar volume;
- prior 20d return;
- earnings-time classification if available.

Also require:

- high-DTC gap-ups beat low-DTC gap-ups;
- low-DTC gap-ups still show normal PEAD but weaker;
- effect not driven by one meme-stock month.

### Final judgment

**Researchable, but not first-tier.** Good diagnostic. Not a new orthogonal strategy. Underpowered with current SI history.

---

## Gemini #2 — Panic Bid insider cluster during VIX spike

### Verdict: **KILL AS STANDALONE; MERGE INTO OPUS #1 AS A REGIME TAG**

### Computability

Mostly computable:

- VIX from yfinance, yes.
- Form 4 cluster buys, yes.
- Open-market purchases, yes.

But the proposed exclusion of 10b5-1 plans is not robust historically. Form 4 10b5-1 flags are much better post-2023 than pre-2023. Footnote parsing is noisy.

### Is it an anti-pattern?

It overlaps heavily with Opus #1. The difference is macro panic rather than stock-specific drawdown.

The problem: VIX spikes create very few independent samples:

- COVID;
- 2022 inflation/rate shock;
- 2025/2026 if present;
- a handful of smaller episodes.

This will be dominated by crisis rebounds and beta exposure.

### Does the test isolate the edge?

No.

Comparing cluster buys during VIX > 30 versus VIX < 15 does not isolate insider skill. It confounds:

- macro rebound beta;
- forced de-risking reversal;
- sector exposure;
- size/liquidity;
- crisis-specific policy response;
- VIX mean reversion.

A proper test would need matched drawdown and event-date controls within the same VIX episode. But then the sample becomes tiny.

### Final judgment

**Kill as standalone.** Keep VIX state as a diagnostic variable inside Opus #1, not as the primary trigger.

---

## Gemini #3 — Intraday “Algo Exhaustion” on 8-K filings

### Verdict: **KILL**

### Computability

The raw ingredients are partly available:

- EDGAR 8-K accepted timestamp, yes.
- Polygon minute bars, maybe yes for event windows.
- Intraday price/volume shock, yes.

But practical computability is not the same as tradability.

Problems:

1. **Latency.**  
   This edge, if it exists, is competed for by SEC-feed/NLP firms operating at much lower latency.

2. **Minute bars are not enough.**  
   We do not have bid/ask, spread, depth, halts, auction imbalance, or trade condition data.

3. **Execution assumption is optimistic.**  
   Entering at T+15 using minute bars will likely overstate fill quality. A 30bps cost assumption may be too low for names moving 3% in 5 minutes.

4. **Filing timestamps are messy.**  
   Many 8-Ks are after hours. Intraday filings are a subset and may be biased.

### Is it an anti-pattern?

It is not a classic cross-sectional factor, but it is a classic latency/microstructure alpha. Without low-latency infrastructure and richer intraday data, we are the slow participant.

### Does the test isolate the edge?

The proposed random 3% intraday-drop control is insufficient unless matched on:

- time of day;
- spread/liquidity;
- prior volatility;
- market/sector movement;
- halt status;
- filing item type;
- initial volume shock.

Even if the backtest works, fill/slippage realism is the main failure mode.

### Final judgment

**Kill.** This is not where this architecture has an advantage.

---

## Gemini #4 — “News-less” liquidation absorption, price action × PIT quality

### Verdict: **KILL**

### Computability

The price and SEC/earnings filters are computable:

- 3-day drop > 15%, yes.
- no earnings within ±5 days, yes.
- no EDGAR filings, yes.
- CFO/ROA quality, yes.

But the key condition — **“news-less”** — is not computable with our data.

Absence of EDGAR filings and earnings does not rule out:

- FDA news;
- litigation;
- analyst downgrades;
- product failures;
- regulatory actions;
- management interviews;
- major customer losses;
- sector shocks;
- social-media/press reports;
- M&A rumors;
- credit events.

We lack a news feed. Therefore we cannot distinguish forced liquidation from unobserved public information.

### Is it an anti-pattern?

Yes.

This is basically:

- short-term reversal after extreme selloff;
- filtered by quality.

That is close to a quality/value re-skin and a generic liquidity-reversal trade.

The live system already uses quality. The known-null list also warns against broad price-action/factor recombinations.

### Does the test isolate the edge?

No.

Comparing high-quality versus low-quality after “news-less” drops does not validate the forced-liquidation mechanism because the news filter is incomplete.

A high-quality bounce could simply be:

- lower distress beta;
- sector composition;
- quality factor rebound;
- lower bankruptcy risk;
- generic reversal.

### Final judgment

**Kill unless we add a real news/event feed.**

---

# Strongest implementation shortlist

## 1. Opus #1 — Cluster insider buying after deep drawdown

### Why first

- Fully within current data layer.
- Long-only.
- Mechanism is intuitive and durable.
- Orthogonal to live PEAD/quality core.
- Event-driven, sparse, not a universal rank factor.
- Test can be made clean with matched drawdown controls.

### Required implementation discipline

- Use Form 4 **filing acceptance timestamp**, not transaction date.
- Require open-market code `P`.
- Exclude grants, exercises, derivative transactions, 10% owners if possible.
- Matched permutation by drawdown, beta, ADV, sector, date/VIX regime.
- Report event-level and portfolio-level Jensen alpha net 30bps.
- Leave-COVID-out and leave-year-out robustness.

---

## 2. My candidate — Adverse-material 8-K underreaction short

This is the one I would add from my own list.

### Scenario

A company files a legally serious negative 8-K, but the market does not fully price it immediately.

Trigger on specific adverse items/text:

- **Item 4.02** — non-reliance on prior financial statements;
- **Item 2.04** — covenant/default/acceleration event;
- **Item 1.02** — termination of material definitive agreement;
- **Item 2.06** — material impairment;
- **Item 5.02** — abrupt CEO/CFO/auditor resignation, especially with negative language;
- auditor resignation / going-concern / internal-control phrases.

Entry:

- short next tradable open after the 8-K accepted timestamp;
- only if initial reaction is not already catastrophic, e.g. D0/D+1 return > −8%, to isolate underreaction rather than gap-chasing.

Exit:

- hold 10–20 trading days;
- cover on +10% adverse move or after fixed horizon.

Universe:

- liquid common stocks only;
- price > $5;
- dollar ADV threshold;
- preferably S&P 1500 / high-liquidity Polygon universe.

### Why it is different

This is not PEAD, not quality, not value, not momentum. It is an **EDGAR legal-event underreaction** trade.

The mechanism is that some filings are legally material but operationally complex. Investors underreact because the implications are hard to map immediately into earnings, credit risk, litigation, or covenant pressure.

### Test

Treatment:

- adverse-material 8-K events.

Controls:

- same-name random 8-Ks;
- non-adverse 8-Ks matched on date/liquidity;
- adverse-keyword but non-item-control filings;
- matched D0 return controls.

Metric:

- short-side Jensen CAPM alpha net at least 30bps;
- block bootstrap by filing week;
- item-level attribution;
- no single item/year drives the result.

Caveat:

This requires shorting. If borrow availability is unavailable, restrict to very liquid large/mid caps and treat results conservatively. If the system remains long-only, this becomes an avoid/hedge signal rather than a standalone strategy.

---

## 3. Opus #2 — Guidance-cut T+5 reversal, hardened version

### Why third

It is computable and event-driven, but the risk of “generic crash reversal” is high. Still, the data exists, and the mechanism is plausible enough to test.

### Required changes before implementation

Do not use random same-name 8-K dates as the main null.

Use matched controls:

- same initial selloff severity;
- same D0→D+5 path;
- same liquidity/volatility;
- same event month;
- non-guidance negative 8-Ks;
- guidance cuts without extreme follow-through.

The edge must be the **interaction**:

> extreme post-guidance-cut selloff reverses more than equally extreme non-guidance selloffs.

If it fails that, kill it.

---

# Secondary / not-first but worth small diagnostic

## Gemini #1 — PEAD × Days-to-Cover

I would run this only as a small add-on diagnostic to the existing PEAD research:

- Does high DTC increase T+1 to T+5 post-gap drift?
- Does high DTC beat low DTC after matching on gap size?
- Is the result robust outside one meme period?

But I would not market it as a new strategy. It is a **PEAD interaction**, and current FINRA history is too short for a high-confidence production decision.

---

# Final survive/kill table

| Proposal | Verdict | Reason |
|---|---:|---|
| Opus #1: insider cluster-buy after drawdown | **SURVIVE** | Computable, orthogonal, real mechanism, testable with matched drawdown controls |
| Opus #2: guidance-cut T+5 reversal | **PROVISIONAL SURVIVE** | Computable but needs stronger null to avoid generic crash-reversal artifact |
| Opus #3: SI spike + stabilization | **KILL / DEFER** | Current SI history too short; float unavailable; squeeze setup crowded/path-dependent |
| Opus #4: earnings IV-crush realized-vol fade | **KILL** | No options data; likely PEAD/reversal in disguise; underspecified |
| Gemini #1: trapped bear PEAD × SI | **DIAGNOSTIC ONLY** | Good interaction test, but PEAD re-skin and SI sample is short |
| Gemini #2: VIX panic insider cluster | **KILL AS STANDALONE** | Too few independent VIX-panic samples; crisis beta contamination |
| Gemini #3: intraday 8-K algo exhaustion | **KILL** | Latency-arbed; minute bars insufficient for execution realism |
| Gemini #4: news-less liquidation absorption | **KILL** | “No news” not observable without news feed; quality + reversal anti-pattern |
