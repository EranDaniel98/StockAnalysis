# Dispersion Trade Scope — Short Index Vol / Long Single-Name Vol

**Date:** 2026-06-01
**Author:** scoping pass (Claude agent), no code modified
**Context:** Naked short-vol harvest just NULL'd (Sharpe 0.33, ~−450% COVID tail). Dispersion is the *correlation-priced*, largely crash-neutral cousin: it harvests the **index variance risk premium** by selling expensive index vol and buying cheaper single-name vol, hedged so the residual exposure is **short implied correlation**, not short the level of vol. The question is whether a solo can survivably build and validate it.

**TL;DR recommendation:** Spend **$0** first. The premium-existence test is fully free — CBOE publishes 20 years of implied-correlation history on a public CDN, and we already have S&P 500 PIT constituent prices to compute realized correlation. Run that gate. Only if implied-corr systematically exceeds subsequent realized-corr (it almost certainly does — that's a documented, robust risk premium) do we buy data. The minimum validation tier is **Polygon Options Developer at $79/mo** (4yr history, EOD aggregates + IV/Greeks for all names), which is the same vendor/bill we already pay for equities. That is the entire first real $-commitment.

---

## 1. Premium-Existence Test — FREE, no spend

### 1a. Implied correlation: FREE from CBOE's CDN (verified live 2026-06-01)

yfinance is a **dead end** for this — `^COR1M` / `^COR3M` return only a single delayed quote row (no downloadable history via the API), and the value is scale-mangled. stooq does not carry the symbol at all. **But CBOE publishes the full daily history as a free, no-auth CSV on its CDN.** Verified retrievable today:

| Index | CBOE CSV URL (verified 200 OK) | History start | Rows | Latest (05/29/26) |
|---|---|---|---|---|
| COR1M (1-mo implied corr) | `cdn.cboe.com/api/global/us_indices/daily_prices/COR1M_History.csv` | **2006-01-03** | ~5,130 | 6.33 |
| COR3M (3-mo implied corr) | `…/COR3M_History.csv` | **2006-01-03** | ~5,120 | 8.60 |
| COR6M | `…/COR6M_History.csv` | 2006-01-03 | ~5,130 | 12.06 |
| COR1Y | `…/COR1Y_History.csv` | 2006-01-03 | ~5,130 | 14.46 |
| **DSPX** (Cboe Dispersion Index) | `…/DSPX_History.csv` | **2014-06-19** | ~3,000 | 42.01 |

All return `DATE,OPEN,HIGH,LOW,CLOSE` (MM/DD/YYYY). ~20 years of implied correlation, plus the purpose-built DSPX dispersion index back to 2014, for **$0**. (Scale note: COR* is quoted in points ~10–90 = implied avg pairwise correlation 0.10–0.90; the current ~6–9 reflects the May-2026 low-vol regime — confirm the divisor against the CBOE white paper before trusting absolute levels, but the *time series* is what the test needs.)

These are the modern replacements for the retired rotating tickers (ICJ→KCJ→JCJ); `^KCJ` / `^ICJ` are delisted and not needed.

### 1b. Realized correlation: computable from data we ALREADY have

We hold PIT S&P 500 constituent daily prices (Polygon, deterministic). Verified locally: `data/snapshots/<id>/prices.parquet` carries ~480 tickers of daily OHLCV (one snapshot spans 2021-05→2024-09; the `data/ohlcv/` parquet store covers 2021→2026). That is exactly the input for **realized average pairwise correlation**.

The CBOE implied-correlation methodology is a cap-weighted *average pairwise* correlation of the top-50 SPX names. The cheap realized proxy uses the index-vs-constituent variance identity (no need for all N×N pairs):

```
realized_corr ≈ (σ²_index − Σ wᵢ² σᵢ²) / ( (Σ wᵢ σᵢ)² − Σ wᵢ² σᵢ² )
```

where σ_index = realized vol of SPY, σᵢ = realized vol of constituent i over the horizon, wᵢ = index weight. Compute σ from log-returns over a trailing/forward window matched to the implied tenor (21d for COR1M, 63d for COR3M).

### 1c. The exact existence test (free first gate)

**Hypothesis:** implied correlation at time *t* systematically exceeds realized correlation over the *subsequent* matched window → negative correlation risk premium exists and is harvestable.

Procedure:
1. Pull `COR3M_History.csv` (CBOE CDN) → daily implied-corr series, 2006→now. Re-scale to [0,1] per the white-paper divisor.
2. From `data/ohlcv/` build top-50 SPX constituents + weights as-of each date (use existing PIT universe loader; weights can be approximated equal- or cap-weight for the gate — the spread is robust to weighting).
3. For each date *t*, compute **forward 63-day realized correlation** via the identity above (this is the realized number the 3-mo implied was pricing).
4. Form the spread `s_t = implied_corr_t − realized_corr_{t→t+63}`.
5. **Gate metrics:** mean(s) > 0, t-stat of mean(s) (Newey-West, lag 63 for overlap), % of days positive, and behavior in stress windows (does the spread *widen* into crashes? — that is the documented payoff signature). Also chart implied-vs-forward-realized.

**Expected result (literature anchor):** S&P 500 implied ≈ 39.5% vs realized ≈ 32.5% → ~7pp persistent gap; documented negative correlation risk premium. If our free reconstruction reproduces a positive, significant spread → **GO to §2**. If it doesn't (data/methodology error or regime), **STOP — do not buy options data.**

Cost of this entire section: **$0** and ~1 day of code. This is the gate that protects all downstream spend.

---

## 2. Data for the Tradeable Construction

### What you actually need
The existence test needs only indices + equity prices. **Trading/backtesting the construction needs single-name + index option data.** Minimum viable:

- **ATM IV per name is enough to START** (vega-neutral straddle dispersion only needs the ATM vol of the index and of each constituent leg + their vegas). You do **not** need full surfaces for the first validation — surfaces matter only for skew-aware variants and precise hedge ratios.
- **How many names:** the trade works with a **liquid subset** of the index, not all 500. Standard practice: 30–50 of the largest, most option-liquid SPX names capture the bulk of the dispersion (top-50 is literally what COR* indexes). For a solo, **~25–40 names** is the realistic execution ceiling (see §3 execution burden).
- **History for a credible backtest:** matched to our evaluation discipline — **need ≥1 full stress cycle**. 4 years (2022 bear + 2024-25 bull) is the minimum; 10+ years (incl. 2020 COVID, 2018 Volmageddon) is *strongly* preferred because the whole thesis is tail behavior. EOD (not intraday) IV is adequate for a daily-rebalanced dispersion backtest.

### Vendor survey — real 2026 pricing

| Vendor / product | What you get | Monthly cost | History depth | Good enough for dispersion? |
|---|---|---|---|---|
| **CBOE CDN (COR*/DSPX CSV)** | Daily implied-corr + dispersion *indices* (not per-name options) | **$0** | 2006 (COR*), 2014 (DSPX) | ✅ for §1 existence + as a benchmark/overlay signal. ✗ for trading legs. |
| **Polygon Options Starter** | All US option tickers, EOD/minute aggregates, **Greeks/IV/OI**, 15-min delayed | **$29** | **2 yr** | ⚠ IV present but only 2yr — too short for a tail-credible backtest. OK for a smoke test. |
| **Polygon Options Developer** | Same + **second aggregates, trades**, deeper history | **$79** | **4 yr** | ✅ **MINIMUM VIABLE.** Per-name ATM IV/Greeks for all SPX names, 4yr incl. 2022 bear. Same vendor we already use for equities. |
| **Polygon Options Advanced** | Tick history, real-time IV/Greeks, SLA | **$199** | full | ✅ overkill for backtest; needed only if going live with intraday hedging. |
| **ORATS Data API (historical)** | Cleaned EOD surfaces, IV/Greeks, **5,000+ symbols, ~14-min-before-close snap** | **$99/mo** trading-tools, or **~$2,000 one-time** for full 2015→present historical pack | 2007 (EOD), 2015+ (full hist pack) | ✅✅ **best fit for the backtest** — purpose-built cleaned IV surfaces; the $2k one-time gives a deep, tail-rich panel. Contact for exact API tiering. |
| **CBOE DataShop — Option EOD Summary** | Raw EOD OHLC/VWAP per option; **IV+Greeks are a paid add-on** at 15:45 snap | quote-based (not public; per-symbol/per-year à la carte, call sales) | **2012→present** | ✅ authoritative/cleanest, but à-la-carte pricing is opaque and assembling a 40-name panel is fiddly. Best if you want exchange-of-record data. |
| **IVolatility** | Raw IV + option prices/Greeks all expiries/strikes; pay-per-use + ~$150/yr Data Download tool | ~**$150/yr** entry; enterprise = contact | **2005→present** | ✅ deep history, retail-friendly entry; good fallback if Polygon IV quality disappoints. |
| **OptionMetrics (IvyDB)** | Academic gold-standard surfaces | institutional ($$$$), not public | 1996+ | ✗ overkill/expensive for a solo. |

**Read:** the contest is **Polygon Developer ($79/mo, recurring, already-integrated)** vs **ORATS one-time historical (~$2,000, cleaner surfaces, deeper tail)**. Start Polygon (cheap, reversible, same bill); escalate to ORATS only if (a) the §1 gate passes AND (b) Polygon IV quality proves too noisy for the leg-level backtest.

---

## 3. Construction, Risks, Capacity, Execution Burden

### Mechanics (textbook vega-neutral dispersion)
- **Index leg:** SELL index volatility — short an SPX/SPY ATM straddle (or strangle / variance proxy). This is the expensive leg you're harvesting.
- **Single-name leg:** BUY a basket of ATM straddles on ~25–40 large SPX constituents, weighted so the **basket vega = index vega** (vega-neutral). Weighting choices: equal-vega, index-weight-matched, or "dirty" (correlation-weighted). The IBKR/Moontower "dirty" version skips precise weighting and just sizes to vega — adequate for a solo.
- **Residual exposure after vega-neutralizing = SHORT IMPLIED CORRELATION.** P&L ≈ (realized dispersion of single names) − (cost of index vol). You win when single names move a lot *relative to* the index — i.e. when realized correlation comes in *below* what was implied.
- **Delta-hedge** both legs (daily) so the trade is about vol/correlation, not direction. This is the bulk of the ongoing work.

### The risk — and why it's the OPPOSITE tail from naked short-vol
- Dispersion is **short correlation**. It loses **when correlations SPIKE** — i.e. in a crash, everything sells off together, the index straddle you're short blows out *more* than your single-name basket gains, because in a panic single-name idiosyncratic vol gets swamped by the common factor (corr → ~1).
- **Contrast with the naked short-vol harvest that just NULL'd:** that lost in a *vol-level* spike (COVID ~−450% tail). Dispersion is *long* single-name vol, so a pure vol-level spike is partially self-hedged — but a *correlation* spike (which usually accompanies crashes) is the kill. So it trades one tail for another. It is **largely crash-neutral relative to naked short-vol, but NOT crash-immune** — the failure mode is "correlation goes to 1," classically 2008 / Aug-2011 / Feb-2018 / Mar-2020. **Quantify this explicitly in the backtest** (§4): expect the worst drawdowns to cluster exactly on the COR* index's biggest up-spikes.
- Secondary risks: vega-neutral ≠ gamma/theta-neutral (the basket typically pays more theta than the index collects — negative carry days), dividend/earnings jumps on single names, and **basis risk** (your 40-name basket ≠ the true 500-name index).

### Capacity & execution burden for a solo — HONEST assessment
- **Leg count:** one index straddle + ~25–40 single-name straddles = **50–80 option legs open simultaneously**, each needing daily delta-hedging in the underlying. This is a *materially* heavier operational load than the equity-factor book (which is ~24 stock positions rebalanced every 63 days).
- **Rebalancing:** straddles drift off-ATM as underlyings move; vega ratios drift as IVs move. Realistic cadence = at least weekly roll/re-strike, daily delta-hedge. That is a meaningful daily chore for one person.
- **Margin:** short index straddle is margin-intensive (naked short option margin or SPAN). The long single-name basket offsets some but not all. Expect significant buying-power usage; size small.
- **Capacity (the good news):** dispersion is *capacity-rich* at institutional scale, so a solo's size is a non-issue for market impact. The binding constraint is **operational/attention bandwidth and execution slippage on 50–80 legs**, not capital.
- **Solo verdict:** feasible to *backtest* cleanly; *live execution is the real bottleneck.* Recommend validating first as a **DSPX-tracking / correlation-signal overlay** before committing to hand-managing 80 legs. Consider whether a simplified expression (e.g. trade DSPX-linked products if/when listed, or a much smaller 10-name "dirty" basket) gets most of the premium at a fraction of the operational load.

---

## 4. Validation Plan + Pre-Registered Ship Rule

### Backtest (once §1 passes and data is bought)
1. **Reconstruct the trade daily** from EOD IV: short index ATM straddle, long vega-matched basket of N≈30 names, delta-hedged at EOD close. Use realistic fills (mid − half-spread) and model option transaction costs explicitly.
2. **Cost model:** options spreads are wide. Charge per-leg bid/ask crossing + commission; stress at 1×, 2× modeled spread. Dispersion P&L is thin — costs are make-or-break, so this must be conservative.
3. **Evaluate phase-averaged, never single-offset** (house rule from `project_phase_luck_capstone`): sweep rebalance/start-date phase, report mean/median ± spread and %-positive, not one headline.
4. **Stress decomposition:** isolate P&L in correlation-spike windows (2018-Q4, 2020-Q1 if data depth allows, 2022 bear, any 2025 stress). Tabulate drawdown vs concurrent COR* level.

### Pre-registered SHIP RULE (set BEFORE looking at backtest output)
Ship to paper only if **ALL** hold:
- **Net-of-cost Sharpe ≥ 0.5** at 2× modeled spreads, **phase-averaged median** (not best phase). (Literature post-cost Sharpes land ~0.3–0.4 passive, ~0.9 active — so 0.5 net is a real but achievable bar; below it the operational burden isn't worth it.)
- **Correlation to the equity-factor core < 0.3** (full-sample return correlation). The entire point of adding dispersion is diversification — if it just re-loads on the same equity beta, reject.
- **Crash behavior bounded:** max drawdown in the worst correlation-spike window **better than the naked-short-vol tail it replaces** (i.e. nothing resembling −450%), and the strategy must *survive* (no margin-call wipeout) a re-run of the 2020 or 2018 correlation spike. If the worst stress drawdown exceeds a pre-set −40% of allocated capital, reject.
- **%-of-phases-positive ≥ 60%.**

Fail any → no-go; archive the finding (don't re-test without new data/structure), exactly as prior NULLs were handled.

---

## 5. Recommendation — Cheapest Go/No-Go Path

**Yes — test premium existence FREE first, then buy the minimum tier only on a pass.** Two-stage, gated:

**Stage 0 — $0 (do this now):**
Pull COR3M (and DSPX) from the CBOE CDN, reconstruct forward realized correlation from our existing `data/ohlcv/` SPX prices, and run the §1c existence test. One day of work, no spend. **Gate:** positive, significant implied−realized spread that widens into stress.
→ If FAIL: stop. The premium isn't reproducible on our data; don't buy options.
→ If PASS: proceed to Stage 1.

**Stage 1 — first real $-commitment: $79/mo, Polygon Options Developer.**
- **What it buys:** per-name ATM IV/Greeks + EOD/minute option aggregates for all SPX constituents and SPX/SPY, **4 years history** (covers the 2022 bear + 2024-25 bull). Same vendor and billing rail we already use for equities — minimal integration friction, fully reversible (cancel anytime).
- **What it lets us do:** run the full §4 leg-level backtest end-to-end and evaluate against the pre-registered ship rule.
- **Why not start at ORATS ($2k one-time):** the $2k is the *right* tool for a deep, clean, tail-rich panel, but it's a large, non-reversible commitment to make *before* we've reproduced the premium on cleaner-but-shorter Polygon data. Escalate to ORATS only if the §1 gate passes AND Polygon's 4yr/IV quality proves insufficient (too short to clear the crash-behavior ship rule, or too noisy at the leg level). That keeps the first hard commitment at **$79**, not $2,000.

**Net first commitment:** **$0 now (Stage 0)**, then **$79/mo (one month = $79) on a Stage-0 pass.** Total at-risk to reach a credible leg-level backtest verdict: **under $100.** Only escalate to ~$2k (ORATS) if both gates demand deeper history.

---

### Honest caveats
- Implied-corr *absolute level* from the free CSVs needs the white-paper divisor to map to [0,1]; the *time-series spread* (what the gate uses) is robust to this, but don't quote absolute correlation numbers until the scale is confirmed.
- The §1 realized-corr identity is a top-50 approximation; weighting choices shift the level but the literature shows the *sign and significance* of the spread are robust.
- The real risk to this whole idea is not the premium (it's well-documented) — it's the **solo execution burden of 50–80 delta-hedged legs**. Budget for the possibility that the backtest passes but live operation is impractical, in which case a simplified small-basket or index-product expression is the fallback.

### Sources
- [CBOE Implied Correlation Indices](https://www.cboe.com/us/indices/implied/) · CBOE CDN CSVs verified live 2026-06-01 (COR1M/COR3M/COR6M/COR1Y from 2006, DSPX from 2014)
- [Polygon options pricing](https://polygon.io/pricing?product=options) (Starter $29 / Developer $79 / Advanced $199)
- [ORATS](https://orats.com/) ($99/mo tools; ~$2,000 one-time historical 2015→present) · [Nasdaq Data Link ORATS](https://data.nasdaq.com/databases/OSMV)
- [CBOE DataShop — Option EOD Summary](https://datashop.cboe.com/option-eod-summary) (2012→present; IV/Greeks paid add-on; pricing via sales)
- [IVolatility historical options data](https://www.ivolatility.com/historical-options-data/) (2005→present; ~$150/yr entry)
- [Quantpedia — Dispersion Trading](https://quantpedia.com/strategies/dispersion-trading) · [Moontower — Dispersion for the Uninitiated](https://medium.com/@moontower/dispersion-trading-for-the-uninitiated-f96d9f6d6c7a) · [IBKR — Dispersion in Practice (the "dirty" version)](https://www.interactivebrokers.com/campus/ibkr-quant-news/dispersion-trading-in-practice-the-dirty-version/) · [Resonanz — Dispersion & the DSPX Index](https://resonanzcapital.com/insights/dispersion-trading-and-the-dspx-index)
