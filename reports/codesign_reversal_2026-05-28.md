# Strategy Debate — 2026-05-28

- **Opus model:** `claude-opus-4-7`
- **Gemini model:** `gemini-3.1-pro-preview`
- **Rounds:** 8 · **Opener:** Gemini
- **Format:** collaborative co-design of a new strategy
- **Seed:** `scripts/debate_seed_reversal.md`

---

### Gemini
Let’s build on Theme B. The core challenge with short-horizon reversal is that while the gross Information Coefficient (IC) is often beautiful, the net portfolio alpha is usually destroyed by transaction costs. To survive a 30bps cost hurdle, we cannot simply trade a naive 1-week reversal. 

We need to isolate price dislocations driven by *temporary liquidity shocks* rather than fundamental repricing, and we must act as synthetic liquidity providers in the less-efficient tail of the broad universe.

Here is v0 of the **News-less Illiquidity Capitulation** strategy. 

### Core Thesis
Retail or institutional forced-selling creates short-term price pressure. Market makers require a premium to absorb this inventory, leading to a mean-reverting bounce. This effect is strongest in less liquid stocks and specifically when the sell-off is *not* driven by fundamental news (where price drops tend to trend due to PEAD).

### Universe & Data Definition
*   **Base Universe:** The 2,000 most liquid US equities by 90-day average dollar volume (EOD Polygon data). This ensures baseline tradeability while keeping small/mid-caps in the mix.
*   **The "No-News" Gate (Crucial):** Using EDGAR PIT and yfinance earnings dates, exclude any ticker that has had an SEC filing (8-K, 10-Q, 10-K) or an earnings release in the past 5 trading days. We only want to fade liquidity-driven drops, not toxic fundamental news.

### Signal Specification (Cross-Sectional)
For the eligible universe, compute the following EOD signals:

1.  **`amihud_20d` (Liquidity Premium):** 
    *   *Formula:* 20-day median of `|Return_t| / (Close_t * Volume_t)`. 
    *   *Logic:* Median dampens single-day outliers. Higher Amihud = less liquid = higher expected premium for providing liquidity. 
    *   *Rank:* Ascending (highest Amihud gets rank 100).
2.  **`rev_5d` (The Trigger):**
    *   *Formula:* `(Close_0 - Close_-5) / Close_-5`.
    *   *Rank:* Descending (biggest 5-day losers get rank 100).
3.  **`vol_shock_5d` (The Capitulation Catalyst):**
    *   *Formula:* `5-day Mean Dollar Volume / 60-day Mean Dollar Volume`.
    *   *Rank:* Ascending (highest relative volume gets rank 100, signaling climax selling).

**Composite Score:** Equal-weight rank sum of `amihud_20d` + `rev_5d` (inverted) + `vol_shock_5d`. We target the top 50 names. 

### The Handoff: The Cost & Turnover Boss Fight
If we naively rebalance this top 50 every 5 days, we face ~100% turnover weekly. At a conservative 15-30bps per leg, that’s a 15–30% annual drag, which will instantly kill the strategy. Furthermore, 63-day phase-luck evaluation needs adaptation for a weekly strategy.

**Opus, I need you to solve the execution and validation layer:**
1.  **Turnover Mitigation:** How do we hold these names to extract the reversal without bleeding to death on costs? Do we use time-based overlapping portfolios (e.g., 5 tranches holding for 10 days), a dynamic exit (hold until `rev_5d` > 0), or an asymmetric entry/exit rank threshold?
2.  **Validation Plan:** Since the live system's 63-day phase-envelope is too slow for this, how exactly should we define the permutation/null baseline and phase-averaged metrics to prove this survives costs and isn't just a lucky 5-day offset?

### Opus 4.7
### Opus — Execution layer + validation plan

Gemini's structure is sound. Let me solve the turnover/cost problem and pin down a falsifiable validation. I'm also tightening two signal specs that will otherwise leak.

### Fix 1: Signal hygiene before execution

- **Amihud denominator must use dollar volume, not `Close*Volume` at time t** for the return — your formula already does this, but enforce: `amihud_t = |ret_t| / ($vol_t)` with `$vol = Close*Volume`, then take the **20-day median of log(amihud)** (Amihud is heavy-tailed; median-of-log is stabler than median-of-raw). Winsorize universe at 1%/99% Amihud.
- **vol_shock as ranked is dangerous** — high relative volume often means *news we missed*. Cap it: require `vol_shock_5d` between the 60th–95th percentile. Above 95th = likely catalyst the no-news gate missed (small filings, guidance, sector news). Use as a **gate, not a ranked score**.
- **Add a price/quality floor:** Close ≥ $5, 90d ADV ≥ $5M. Penny-stock reversal is a microstructure artifact, not alpha.
- **Revised composite:** rank-sum of `amihud_20d` (asc) + `rev_5d` (desc, i.e. losers), gated by `vol_shock ∈ [P60, P95]` AND no-news gate. Top **50 equal-weight, market-beta-hedged with SPY short** sized to portfolio β=0 (estimate 60d β per name, sum, short that much SPY notional). This is the "market-neutral by construction" requirement from the seed.

### Fix 2: Turnover — overlapping tranches, not dynamic exit

Dynamic exit (`hold until rev_5d > 0`) sounds elegant but creates **path-dependent holding periods that destroy backtest reproducibility** and concentrate exits on up-days (adverse selection on the exit fill).

**Use 5 overlapping tranches, 10-day hold, rebalanced daily:**
- Each day, 1/5 of book (10 names) rolls off, 10 new names enter from today's top-50 ranking.
- Effective turnover: **20%/day on 1/5 of book = 4%/day total = ~10x/yr ≈ 1000% annual turnover**, but on small slices.
- At 30bps round-trip: 10 × 0.30% × 2 = **6% annual cost drag** (not 30%). Survivable if gross α > 10%.
- Cap incumbents: a name already held cannot re-enter a new tranche (no doubling).

### Fix 3: Sizing

Equal-weight within the 50-long book, then **scale gross exposure inversely to realized 20d portfolio vol** targeting 10% ann vol. SPY short leg sized daily to neutralize aggregate β. No single-name > 3%.

### Fix 4: Validation plan (the falsifiable part)

The 63d phase envelope is wrong for a 10-day-hold strategy. Replacement:

1. **Phase grid:** sweep entry-day offset 0–9 (10 phases) × snapshot start-date offset {0, +21, +42} days = **30 independent backtests** per config. Report **median CAPM-α, IQR, %-positive**.
2. **Permutation null:** shuffle the cross-sectional rank within each rebalance date 200× — preserves universe, dates, sector composition, gross/net exposure. Strategy α must exceed **95th percentile** of null α distribution.
3. **Cost stress:** report net α at 10/20/30/50bps round-trip. **Pre-registered kill rule: median net α at 30bps < +3%/yr across phases → ship to trash.**
4. **Regime split:** report α separately for VIX<20, 20–30, >30 buckets. Reversal should be *stronger* in high-VIX; if it's not, the mechanism story is wrong.
5. **Sanity check:** a "high-Amihud only, no reversal trigger" baseline should earn ~0 α. If it earns the same as the full signal, `rev_5d` isn't doing work.

**Decision rule, pre-registered:** ship to paper only if median 30bps-net CAPM-α ≥ +3%, permutation p < 0.05, and α positive in ≥2 of 3 VIX buckets.

Your move: sector-neutralization within the long leg (yes/no), and whether the SPY hedge should be a single-name β-hedge or a sector-ETF basket.

### Gemini
### Gemini — Sector Dynamics & The T+1 Execution Reality

Opus, the 5-tranche overlapping structure perfectly solves the turnover bleed, and the 30-phase grid with the 30bps kill rule gives us a rock-solid falsifiability framework. I accept all four of your fixes. 

To answer your prompts and finalize the physical execution layer, here is how we handle sector risk and the unavoidable reality of EOD data latency.

### Decision 1: Intra-Sector Ranking (Sector-Neutral Longs)
**Yes, we must sector-neutralize the long leg.** If we rank globally, a localized macro shock (e.g., a semiconductor crash) will fill our top 50 entirely with falling Tech knives, turning an idiosyncratic liquidity strategy into a directional sector bet. 

*   **Adjustment:** Instead of a global rank, calculate the z-score of `amihud_20d` and `rev_5d` **within each GICS sector** (using the EDGAR/Polygon metadata mapping). 
*   **Selection:** The daily 10-stock entry tranche will consist of the top 1 stock from each of the 10 major sectors (excluding Real Estate to avoid REIT yield-distortion). This guarantees a perfectly diversified long book.

### Decision 2: The Hedge (Sector-ETF Basket)
Because our longs are exactly distributed across sectors, a single SPY short leaves us exposed to sector-rotation risk. We will use a **Sector-ETF basket hedge** (XLK, XLF, XLV, etc., which are fully supported on Polygon's EOD tier).

*   **Sizing:** For the 5 stocks held in a given sector across the 5 tranches, calculate their aggregate 60-day beta against their specific sector ETF.
*   **Execution:** Short that exact dollar-beta amount of the sector ETF. This explicitly isolates the *idiosyncratic* illiquidity premium and immunizes the book against sector-level trends. 

### Fix 5: The "T+1" Latency Trap (Critical Addition)
Since our pipeline relies strictly on EOD data, the `T` close data isn't fully processed until after hours. We cannot physically execute at the `T` close. We must trade at `T+1`. 

Short-term reversal is notorious for decaying overnight (the "gap up"). If our backtest assumes execution at `T` close, it is a mirage.
*   **Execution Rule:** The Alpaca execution must route as a **`T+1` VWAP order over the first 30 minutes of trading** (09:30–10:00 AM ET). This avoids the chaotic opening auction while capturing the price before the reversal fully decays.
*   **Validation Addition:** The backtest must shift the entry price from `Close_T` to `Open_T+1`. Furthermore, add a **T+1 slippage stress test** to the validation plan: calculate the alpha decay between `Close_T` and `Open_T+1`. If >50% of the gross alpha is captured in the overnight gap, the strategy is un-tradeable and triggers the kill rule.

### Final Consolidated Blueprint
1.  **Universe:** Top 2000 liquid names (Price > $5, 90d ADV > $5M).
2.  **Gates:** `vol_shock_5d` ∈ [P60, P95] AND zero SEC filings/earnings in the last 5 days.
3.  **Signal:** Intra-sector z-score sum of `amihud_20d` (high) + `rev_5d` (losers).
4.  **Portfolio:** 50 longs (5 tranches of 10, 10-day hold). 1 stock per sector per day. Max 3% weight per name. Vol-scaled to 10% annualized.
5.  **Hedge:** Sector-ETF short basket, sized to neutralize the 60d beta of the sector's long holdings.
6.  **Validation:** 30-phase grid, `T+1` Open execution, permutation null, 30bps cost stress. Kill if median net CAPM-α < +3%.

This spec is fully constrained to our data layer, market-neutral by construction, and strictly falsifiable. We are ready to build the snapshot and run the phase envelope.

### Opus 4.7
### Opus — Closing the implementation gaps

Gemini, accepting sector-neutral longs + sector-ETF hedge + T+1 Open execution. Three real holes remain before this is buildable. Let me close them.

### Gap 1: GICS sector data — we don't have it

EDGAR has SIC codes, not GICS. Polygon $29 Stocks tier doesn't include sector classification reliably. "1 stock per sector per day" is undefined on our data layer.

**Fix:** Build sector buckets from **SIC → 10-bucket mapping** (standard crosswalk, hardcode in `config/sectors.yaml` — we already have this file). SIC is in every EDGAR submission. The 10 buckets map to the 10 sector ETFs (XLK/XLF/XLV/XLE/XLI/XLY/XLP/XLU/XLB/XLC). REITs (SIC 6798) excluded as you specified. Names with missing SIC → dropped (not silently bucketed).

**Sector-ETF history caveat:** XLC only exists since 2018-06. For pre-2018 snapshots, fold Comms into XLK. Document this; don't let it silently break.

### Gap 2: "Top 1 per sector per tranche" is too rigid

10 sectors × 5 tranches = 50 names, but some sectors will have weak signal on a given day (z-scores near zero, or no names passing the no-news gate). Forcing a pick from a sector with no signal **adds noise, not diversification**.

**Fix:** Daily entry rule:
- Within each sector, compute composite z = `z(amihud_20d_log)` + `z(-rev_5d)` (both intra-sector).
- A sector's top name **enters only if its composite z ≥ 1.0** (meaningful dislocation).
- If <10 sectors qualify, tranche is smaller that day (e.g., 7 names). **Do not force-fill.**
- Unused capital sits in cash (no SPY-long substitute — defeats market-neutrality).

This means gross exposure floats. Vol-targeting (Fix 3 from before) handles the scaling.

### Gap 3: Exit logic was underspecified

"10-day hold" is clean but ignores that **the reversal often completes in 2–3 days**, then drifts. Holding 10 days on a name that already bounced gives back α.

**Fix — soft exit overlay:**
- Hard exit at day 10 (preserves tranche structure).
- **Early exit if cumulative position return ≥ +8%** (lock the bounce) — flat to cash, slot stays empty until next tranche roll.
- **Early stop if cumulative return ≤ −6%** (this is a falling-knife, not a reversal).
- Both exits at T+1 Open, same as entry.

Asymmetric (+8/−6) because we're long losers — we expect upside skew if the thesis works.

### Gap 4: Validation — add the overnight-decay test concretely

You flagged it; let me operationalize:

- **α attribution split:** for each entry, decompose total return into `overnight_gap = (Open_T+1 − Close_T)/Close_T` and `holding_return = (Exit_Price − Open_T+1)/Open_T+1`. Report **mean overnight_gap vs mean holding_return across all trades**.
- **Kill rule addition:** if `overnight_gap / (overnight_gap + holding_return) > 0.5`, alpha is in unreachable territory — kill.
- **Sector-hedge slippage:** the daily β-rebalance of 10 sector ETFs is non-trivial. Add a 5bps/day hedge-rebalance cost on the short leg notional turnover.

### Final spec — ready to build

```yaml
universe: top 2000 by 90d ADV, Close ≥ $5, ADV ≥ $5M
sector_map: SIC → 10-bucket (config/sectors.yaml), REITs excluded
gates:
  - no 8-K/10-Q/10-K filing in last 5 trading days (EDGAR)
  - no earnings in last 5 trading days (yfinance)
  - vol_shock_5d ∈ [P60, P95]
signal:
  - amihud_20d = median_20d( log(|ret_t| / ($vol_t + 1)) ), winsorized 1/99%
  - rev_5d = (Close_0 - Close_-5)/Close_-5
  - composite_z (intra-sector) = z(amihud_20d) + z(-rev_5d)
entry:
  - daily: per sector, top name if composite_z ≥ 1.0
  - max 10 names/day (1 per sector), 5 tranches → max 50 names held
  - execution: T+1 Open, first 30min VWAP
exit:
  - hard: T+10 Open
  - soft: +8% take-profit OR -6% stop, at next T+1 Open
sizing:
  - equal-weight within active book, max 3% per name
  - gross scaled inversely to 20d realized vol, target 10% annualized
hedge:
  - per sector: short XL* sized to neutralize aggregate 60d β of that sector's longs
  - rebalanced daily at T+1 Open; 5bps/day cost on hedge turnover
validation:
  - 30-phase grid (10 entry offsets × 3 start offsets)
  - permutation null (200x, shuffle intra-sector ranks)
  - cost stress at 10/20/30/50bps round-trip + 5bps/day hedge
  - VIX regime split: <20, 20-30, >30
  - overnight-decay attribution
kill_rules (pre-registered, ALL must pass):
  - median net CAPM-α (30bps) ≥ +3%/yr across 30 phases
  - permutation p < 0.05
  - α > 0 in ≥ 2 of 3 VIX buckets
  - overnight_gap share of α ≤ 50%
  - max-DD across phases ≤ 15%
```

Ship to `scripts/build_snapshot.py` + new `src/factors/illiq_reversal.py`. If all five kill rules pass on 2022–2026 data, route to paper at 25% sizing for 90 days before scaling.

### Gemini
Opus, the spec is exceptionally tight. The 30-phase grid, the SIC mapping, and the overnight-decay kill rule perfectly adapt the live system's evaluation discipline to a high-turnover strategy. 

Before we write the Python for `src/factors/illiq_reversal.py`, I need to patch three critical mathematical and execution leaks in the current spec. If we don't fix these, the backtest will hallucinate alpha and the turnover mitigation will break.

### Fix 1: The Vol-Targeting / Turnover Paradox
**The Bug:** You specified "equal-weight within active book... gross scaled inversely to 20d realized vol." If we dynamically scale the *entire* book daily to target 10% annualized volatility, we are forcing daily trades on all 50 names. This completely destroys your 5-tranche turnover mitigation, driving transaction costs back to fatal levels.
**The Fix (Entry-Only Scaling):** Incumbent positions must float. The vol-targeting multiplier `(Target_Vol / Realized_20d_Vol)` is applied **only to the capital allocated to today's incoming tranche**. 
*   *Math:* Today's tranche gets `(Base_Equity / 5) * Vol_Scalar`. Incumbents are left untouched until their exit condition is met. This steers portfolio volatility over a 5-day smoothing window without incurring a single basis point of rebalancing drag on held names.

### Fix 2: The "Corrupted Beta" Problem
**The Bug:** We are buying stocks that just suffered a massive 5-day idiosyncratic price collapse. If we calculate the sector-ETF hedge ratio using the standard trailing 60-day beta ending at `T=0`, that covariance is heavily distorted by the very anomaly we are trading. The beta will artificially drop, leaving us under-hedged.
**The Fix (Lagged Beta):** Calculate the 60-day beta **ending at T-5**. This captures the stock's *structural* relationship with its sector ETF before the "no-news" liquidity shock distorted the price series. 

### Fix 3: Amihud Math & Soft-Exit Slippage
**The Bug (Math):** `log(|ret_t| / ($vol_t + 1))` evaluates to `-inf` on days where the close is unchanged (`ret_t = 0`). 
**The Fix:** Add a standard epsilon: `log( (|ret_t| + 1e-6) / ($vol_t + 1) )`. 

**The Bug (Simulation):** The +8%/-6% soft exits trigger based on EOD `Close_T`. If the backtest magically fills exactly at -6%, it's lookahead bias.
**The Fix:** The backtest logic must strictly evaluate the trigger at `Close_T`, but the exit fill must be `Open_T+1`. If a stock closes at -5% (no trigger), but gaps down overnight to open at -15%, the system must record a -15% realized loss. The strategy must survive this exact slippage to pass the 30bps cost stress.

### ETF History Fallback
To address your XLC (Communications) history gap pre-2018: for any sector ETF missing price history on a given snapshot date, the hedge defaults to the **SPY beta** for those specific names. 

### Ready for Implementation
The spec is now mathematically sound, strictly respects the EOD T+1 execution constraint, and protects the turnover budget. 

We have our blueprint. Let's merge this into `src/factors/illiq_reversal.py`, map the SIC codes in `config/sectors.yaml`, and fire off `scripts/build_snapshot.py` and the 30-phase grid. If it clears the pre-registered +3% net CAPM-α kill rule, we push it to Alpaca paper trading.

### Opus 4.7
### Opus — Accepting the patches, closing the last build gaps

Gemini, all three fixes accepted. Entry-only vol scaling is the right call — I was sloppy. Lagged-β at T-5 is exactly right; the contamination would have under-hedged us by ~15-25% on the entry day. Epsilon and gap-through-stop slippage are non-negotiable for honest sim.

Four final gaps before we can write the code without ambiguity. Then we ship.

### Gap A: The no-news gate's lookahead trap

EDGAR filings are timestamped, but **"filed by 4pm ET on day T"** vs **"filed after close on day T"** is the difference between knowing it at T-Close and learning it at T+1-Open. Our T+1-Open execution means we *do* see filings posted between T-Close and T+1-Open.

**Fix:** The no-news gate uses `filing_accepted_datetime ≤ T+1 Open` (08:00 ET cutoff to be safe). For backtest reproducibility, EDGAR's `acceptedDate` field is timestamped to the second — use it directly, don't truncate to date. Same for yfinance earnings (`earnings_date < T+1 Open`).

This actually *helps* the strategy: an 8-K filed at 7am on T+1 disqualifies an entry we'd otherwise make at the 9:30 open.

### Gap B: Permutation null must preserve the gates, not just the ranks

"Shuffle intra-sector ranks 200×" is too loose. If we shuffle ranks across the full eligible universe, we destroy the gate's selection effect — the null will look weaker than reality because it's picking random names, not random-among-already-gated names.

**Fix (tighter null):** For each rebalance date, **shuffle ranks only within the gated, sector-bucketed pool**. This isolates the question "does our signal beat random selection *from the same eligibility set*?" — the actual falsifiable claim. If the gated-random null already earns +2% α, then the gates are doing all the work and the signal is decoration; we should know that.

Add a **second null**: shuffle the *entry dates* (hold the same names but enter on random T's). Tests whether the timing of the signal matters vs. just owning illiquid losers chronically.

### Gap C: Tranche bookkeeping under early exits

When +8% take-profit fires on day 4 of a tranche's 10-day life, that capital sits in cash for 6 days. Over a full backtest, this could mean **15-25% of book in cash on average** — which mechanically dampens both α and vol, inflating Sharpe artificially.

**Fix:** Report two α numbers:
1. **`α_deployed`** — return on capital actually at risk (excludes cash drag). This is the *signal* quality.
2. **`α_book`** — return on total notional including idle cash. This is what we'd actually earn.

The +3% kill rule applies to **`α_book`** (the real number). `α_deployed` is diagnostic — if it's >>α_book, we should consider faster re-deployment (e.g., next-day backfill from rank #2 in that sector).

### Gap D: Snapshot scope & runtime budget

30 phases × full pipeline (daily entry, daily hedge rebalance, 5-day lookback gates, 2000-name universe, 4-year window) is **~120,000 rebalance-days of computation**. On the current snapshot machinery this is ~4-8 hours per config. Acceptable for a one-shot validation, brutal for iteration.

**Fix:** Build **two snapshots**:
- `illiq_rev_dev`: 2024-01 to 2026-01, 2000 names. Fast iteration (~30 min/phase grid). Use for parameter sanity only — **do not** tune kill-rule thresholds on this.
- `illiq_rev_validation`: 2022-01 to 2026-05, 2000 names. The real test. Run **once** after dev is frozen. This is the pre-registered evaluation.

Pre-register the dev→validation handoff: any parameter changed after seeing validation results = the run is contaminated, restart with a new snapshot id.

### Final implementation checklist

```
config/sectors.yaml          — SIC → 10-bucket map, REIT exclusion, XLC→XLK pre-2018
src/factors/illiq_reversal.py — signal + intra-sector z + gates
src/factors/sic_sector_map.py — SIC lookup from EDGAR submission metadata
src/backtest/tranche_book.py  — 5-tranche state machine, soft/hard exits, gap-through fills
src/hedge/sector_etf_hedge.py — lagged β (T-5), daily rebalance, SPY fallback
scripts/build_snapshot.py     — add sector ETFs (XLK/XLF/XLV/XLE/XLI/XLY/XLP/XLU/XLB/XLC) + SPY
scripts/run_illiq_validation.py — 30-phase grid + 2 nulls + cost stress + regime split
```

**Pre-registered ship decision (frozen as of this message):**
- median `α_book` net of 30bps + 5bps/day hedge ≥ +3%/yr across 30 phases
- permutation p < 0.05 on **both** nulls (rank-shuffle AND date-shuffle)
- α > 0 in ≥ 2 of 3 VIX buckets
- overnight_gap share of α ≤ 50%
- max-DD across phases ≤ 15%
- `α_book / α_deployed ≥ 0.6` (cash drag isn't eating the edge)

If all six pass on `illiq_rev_validation`, route to Alpaca paper at **25% sizing for 90 days**, reviewed against the live m/q/v book. If any fail, the strategy is dead — no re-tuning, no second chances on the same snapshot. Next idea.

Ship it.

### Gemini
### FINAL CONSOLIDATED SPECIFICATION: News-less Illiquidity Capitulation

Opus, the patches are flawless. We have successfully engineered a short-horizon reversal strategy that survives our strict EOD data constraints, mitigates turnover bleed, and is ruthlessly falsifiable. Here is the final, frozen blueprint.

#### 1. Thesis & Inefficiency Exploited
**The Edge:** Liquidity provision to forced sellers. When a stock suffers a rapid price collapse *without* fundamental news, the dislocation is driven by temporary flow toxicity (e.g., margin calls, fund liquidations). Market makers demand a premium to absorb this inventory in less liquid names. By acting as synthetic liquidity providers, we capture the mean-reverting bounce. The sector-ETF hedge neutralizes market/sector beta, isolating the pure idiosyncratic illiquidity premium.

#### 2. Universe & Signal Definitions (Data strictly from Polygon EOD + EDGAR/yfinance)
*   **Base Universe:** Top 2000 US equities by 90-day ADV. Filters: `Close_T >= $5`, `ADV >= $5M`. Exclude REITs (SIC 6798). Map EDGAR SIC codes to 10 sector buckets (matching XL* ETFs) via `config/sectors.yaml`. 
*   **The "No-News" Gate:** Exclude any ticker with an SEC filing (8-K/10-Q/10-K) or earnings release timestamped within the last 5 trading days up to **08:00 ET on T+1**.
*   **The Catalyst Gate:** `vol_shock_5d` (5d Mean $Vol / 60d Mean $Vol) must fall in the **[P60, P95]** percentile range. (Above P95 implies undetected news).
*   **Cross-Sectional Signal (Calculated daily at T-Close):**
    *   `amihud_20d`: `median_20d(log((|ret_t| + 1e-6) / ($vol_t + 1)))`, winsorized at 1%/99%.
    *   `rev_5d`: `(Close_0 - Close_-5) / Close_-5`.
    *   *Composite:* Intra-sector z-score sum: `z(amihud_20d) + z(-rev_5d)`.

#### 3. Execution, Sizing, and Rebalance (The 5-Tranche Book)
*   **Entry:** Daily at T+1 Open (first 30min VWAP). Select the top 1 name per sector where `composite_z >= 1.0`. Max 10 names/day.
*   **Sizing:** 5 overlapping tranches (max 50 names held). Equal-weight within the active book (max 3% per name). *Crucial:* Vol-targeting (inversely scaled to 20d realized vol, targeting 10% ann.) is applied **only to the capital allocated to today's incoming tranche**. Incumbents float.
*   **The Hedge:** Short the corresponding sector ETF (XL*) sized to neutralize the aggregate 60-day beta of that sector's longs. *Crucial:* Beta is calculated ending at **T-5** to avoid correlation distortion from the crash. (Fallback to SPY beta for XLC pre-2018). Rebalanced daily at T+1 Open.
*   **Exits (Evaluated at Close_T, Executed at Open_T+1):**
    *   *Hard:* Day 10 Open.
    *   *Soft:* +8% cumulative take-profit OR -6% stop-loss. Unused capital sits in cash until the tranche rolls.

#### 4. Pre-Registered Validation Plan
We will build `illiq_rev_validation` (2022-01 to 2026-05). The strategy must pass ALL six pre-registered kill rules to survive:
1.  **Net Alpha:** Median `alpha_book` (accounting for cash drag) >= **+3%/yr** across a 30-phase grid (10 entry offsets × 3 start offsets), net of 30bps round-trip + 5bps/day hedge cost.
2.  **Permutation Null:** p < 0.05 against TWO 200x nulls: (A) Shuffling intra-sector ranks *within the gated pool*, and (B) Shuffling entry dates.
3.  **Regime Robustness:** Alpha > 0 in >= 2 of 3 VIX buckets (<20, 20-30, >30).
4.  **Decay Limit:** `overnight_gap` (Close_T to Open_T+1) must account for **<= 50%** of total alpha.
5.  **Risk:** Max Drawdown across phases <= 15%.
6.  **Capital Efficiency:** `alpha_book / alpha_deployed >= 0.6` (cash drag from early exits cannot destroy the edge).

#### 5. Honest Verdict & Next Steps
**The Edge is Realistic:** Limits-to-arbitrage in micro-cap/illiquid names is one of the few structural anomalies that survives quantitative decay, provided you filter out toxic fundamental flow. 
**The Failure Modes:** Gap-through slippage on the -6% stop-loss, and the overnight decay (T+1 Open) eating the premium before we can execute.

**The Build Decision:** We write `src/factors/illiq_reversal.py` and run the `illiq_rev_validation` snapshot *now* to lock in the research. **However, we do NOT deploy to Alpaca yet.** The live m/q/v system is mid-validation (until 2026-08-27). Pushing a second, highly complex high-turnover strategy to the execution layer risks polluting the infrastructure and violating our multiple-comparisons discipline. 

We freeze the code, run the backtest, and if it passes all 6 kill rules, it goes on the shelf as the immediate next-in-line for the Fall 2026 paper-trading epoch. Ship it to the repo.

### Opus 4.7
### Opus — FINAL SPEC: News-less Illiquidity Capitulation (NIC-v1)

Gemini's consolidation is clean. I'm accepting it verbatim on signal/execution/validation and adding only what's needed to make this **the frozen, citable spec** — including the one piece we both danced around: the honest verdict.

---

### 1. Thesis & Inefficiency

**Claim:** In the smaller/illiquid tail of the US equity universe, sharp 5-day drawdowns *unaccompanied by SEC filings or earnings* are dominated by **forced-flow toxicity** (margin calls, fund liquidations, tax-loss dumping), not fundamental repricing. Market-makers and slow capital demand a liquidity premium to absorb this inventory, producing a 5–10 day mean-reverting bounce. By being the patient buyer at T+1 Open and hedging sector beta, we harvest the **idiosyncratic liquidity premium** — structurally distinct from momentum, value, and quality (the live m/q/v book), and **uncorrelated by construction** (β≈0 via lagged sector-ETF short).

**Why this survives where naive reversal doesn't:** the no-news gate + vol_shock ∈ [P60,P95] band excludes PEAD-trending names (where reversal *fails*) and undetected-catalyst names (where it's a trap). What's left is closer to pure microstructure.

---

### 2. Signals (frozen)

| Signal | Formula | Lookback | Direction |
|---|---|---|---|
| `amihud_20d` | `median_20d( log((|ret_t| + 1e-6) / ($vol_t + 1)) )`, winsorized 1/99% | 20d | High = illiquid (long) |
| `rev_5d` | `(Close_0 - Close_-5) / Close_-5` | 5d | Negative = loser (long) |
| `vol_shock_5d` | `mean_5d($vol) / mean_60d($vol)` | 5/60d | **Gate**, not score: must ∈ [P60, P95] |

**Composite:** intra-sector z-score sum `z(amihud_20d) + z(-rev_5d)`. Entry threshold: composite_z ≥ 1.0.

---

### 3. Universe, Entry/Exit, Sizing

- **Universe:** top 2000 by 90d ADV; `Close ≥ $5`, `ADV ≥ $5M`; SIC→10-sector map (`config/sectors.yaml`); REITs (SIC 6798) excluded.
- **Gates:** no 8-K/10-Q/10-K (EDGAR `acceptedDate` ≤ T+1 08:00 ET) and no earnings in trailing 5 trading days; vol_shock band.
- **Entry:** daily, T+1 Open 30-min VWAP. Top 1 per sector if composite_z ≥ 1.0. Max 10/day; **no force-fill** — empty slots stay empty.
- **Book:** 5 overlapping tranches × 10-day hold = up to 50 longs. Equal-weight, ≤3% per name.
- **Vol scaling (entry-only):** today's tranche notional × `min(1.5, target_vol / realized_20d_vol)`. Incumbents float untouched.
- **Hedge:** per sector, short XL* sized to neutralize aggregate **β computed on [T-65, T-5]** (lagged). Rebalanced daily T+1 Open. XLC→XLK pre-2018-06; SPY fallback if ETF history missing.
- **Exits (trigger@Close_T, fill@Open_T+1, gap-through honored):** hard T+10 Open; soft +8% TP / −6% SL.

---

### 4. Pre-Registered Validation (frozen — no re-tuning post-hoc)

**Snapshots:**
- `illiq_rev_dev` 2024-01 → 2026-01 — sanity only, no threshold tuning.
- `illiq_rev_validation` 2022-01 → 2026-05 — **one shot**.

**Phase grid:** 10 entry offsets × 3 start offsets = 30 backtests. Report median + IQR + %-positive of net `α_book`.

**Two nulls (200× each):**
- (A) Shuffle ranks within gated sector pool (does signal beat random-among-eligible?).
- (B) Shuffle entry dates (does timing matter, or are we just chronically long illiquid losers?).

**Cost stress:** 10/20/30/50 bps round-trip + 5 bps/day on hedge turnover.

**Six kill rules — ALL must pass:**
1. Median `α_book` net 30bps + hedge ≥ **+3%/yr** across 30 phases.
2. Permutation p < 0.05 on **both** nulls.
3. α_book > 0 in ≥ 2 of 3 VIX buckets (<20, 20-30, >30).
4. Overnight-gap share of α ≤ 50%.
5. Max-DD across phases ≤ 15%.
6. `α_book / α_deployed ≥ 0.6`.

**Decision rule:** all six pass → shelve until 2026-08-27 paper review of m/q/v completes, then deploy at 25% sizing for 90d. Any fail → **dead, no re-tune on same snapshot**.

---

### 5. Honest Verdict

**Realistic edge?** Plausible, not proven. The liquidity-premium-in-small-caps literature (Amihud 2002, Avramov et al. 2006) is among the most replicated anomalies, and gating out fundamental news addresses the standard "reversal = catching falling knives" failure mode. **Expected gross α: 8–15%/yr; net after costs + hedge drag: 3–6%/yr if it works at all.** Tight, but above the bar.

**Most likely failure modes, ranked:**
1. **Overnight decay eats >50% of α** (kill rule 4). This is the single highest-probability fail — reversal literature consistently finds 40-60% of the bounce in the overnight gap we can't access.
2. **Cost stress at 30bps kills it** (kill rule 1). 1000% turnover is unforgiving; ADV ≥ $5M floor may be too low.
3. **Hedge β-instability** during regime shifts — lagged β at T-5 is correct in expectation but noisy on individual names.
4. **Gated-rank null also earns +2% α** (kill rule 2A) — meaning gates do the work, signal is decoration. Diagnostic, not catastrophic.

**Worth building before 2026-08-27?** **Yes, build the code and run the validation now; do NOT deploy.** Rationale:
- Pure research work (snapshot + backtest) doesn't touch the live m/q/v paper run or contaminate its OOS test.
- The validation result is itself information: a clean fail tells us reversal-in-small-caps is dead on our data layer (kill the theme, move on). A clean pass gives us a shelved, market-neutral, **low-correlation-to-m/q/v** strategy ready for the Fall 2026 epoch — exactly when we'll want a second leg if m/q/v paper validates.
- The multiple-comparisons risk we're avoiding is **deployment**, not research. Pre-registering the six kill rules *before* seeing results is the discipline that makes this honest.

**Ship to repo. Run validation. Shelve result. Revisit 2026-08-27.**
