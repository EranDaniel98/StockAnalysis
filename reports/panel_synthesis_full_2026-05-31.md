# Final Ranked Shortlist — Scenario-Conditional Strategies Surviving Cross-Model Scrutiny

Based on the convergent verdicts across Opus, Gemini, and GPT-5.5 critiques, the following 5 strategies survived cross-model scrutiny. Ranked by combined panel conviction (survival strength × orthogonality × computability).

---

## #1 — Quality/Junk Regime Meta-Gate
*(Merged from Opus #4 + Gemini #3; flagged as highest-priority by all three panelists)*

**Scenario trigger.** Detect ex-ante the regime transitions where the live PEAD+quality L/S sleeve bleeds alpha (junk rallies / "dash-for-trash") vs. earns its premium (flight-to-quality). Gate the existing sleeve ON/OFF — do NOT flip direction (flat is sufficient).

**Exact computable signal.**
- `junk_proxy_ret` = trailing 20d equal-weight return of bottom-quintile-by-price (or high-beta) S&P names (Polygon EOD).
- `quality_proxy_ret` = trailing 20d return of top-quintile-by-ROA (EDGAR PIT).
- `junk_premium_20d` = junk_proxy_ret − quality_proxy_ret.
- `spy_intraday_20d` = sum of (close_t/open_t − 1) over 20d (Polygon EOD).
- `spy_overnight_20d` = sum of (open_t/close_{t−1} − 1) over 20d.
- VIX level + VIX 1m–3m term-structure slope (yfinance `^VIX`, `^VIX3M`; drop term-structure clause if `^VIX3M` history insufficient).
- **Gate OFF (flat):** `junk_premium_20d` > trailing 252d median AND VIX < 20d SMA AND (`spy_intraday_20d` − `spy_overnight_20d`) > +2%.
- **Gate ON (deploy sleeve):** otherwise, OR if VIX term structure inverts.

**Entry/exit.** Daily gate evaluation on T−1 close; sleeve weight at T open = {0, 1} × base weight. No directional flip.

**Persistence mechanism.** Quality premium is a real, cyclical risk premium; junk rallies are macro-liquidity / short-squeeze / retail-FOMO driven and structurally orthogonal to fundamentals. Gating off during these regimes preserves the premium without trying to ride the squeeze. Not arbed because the sleeve itself requires holding quality through quality regimes — the gate just avoids paying the tax during hostile windows.

**Falsifiable test.**
- Run live composite (m/q/v + PEAD) 2018–2026, with and without the gate.
- Compute Jensen's CAPM-α net 30 bps round-trip.
- Phase split: 2019 melt-up, COVID 2020 H1/H2, 2022 bear, 2023 AI rally, 2024–26.
- **Same-duty-cycle random gate null** (random ON/OFF with matched % active days).
- **Walk-forward threshold selection** — no full-sample tuning.
- **Parameter-grid robustness:** ≥70% of threshold grid must beat ungated.
- **Ablation:** test components alone (spread gate vs. intraday-overnight gate vs. combined).
- **PASS bar:** gated α > ungated α by ≥ 200–250 bps/yr; %-positive years ≥ 6/8; outperforms same-duty-cycle random gates at p < 0.05; no lookahead.

---

## #2 — Overnight-Gap Reversal on Form-4 Insider Cluster Buys
*(Opus #1; survived all critiques with mandatory repairs)*

**Scenario trigger.** A name has ≥2 distinct insider open-market buys (Form-4 code `P`, direct ownership) in prior 10 trading days, OR ≥1 buy with value > $250k, AND on day t opens with overnight gap-down ≤ −2.0σ of its trailing 60d overnight-return distribution.

**Exact computable signal.**
- EDGAR Form-4: `transaction_code='P'`, `is_direct=true`, distinct CIKs in [t−10, t−1].
- **Use filing acceptance timestamp** (not transaction date); require filing accepted before T−1 close to avoid lookahead.
- Gap: `(open_t / close_{t−1}) − 1`, z-scored vs. trailing 60d.
- Liquidity gate: 20d ADV > $20M (Polygon EOD).
- β_60d vs. SPY for hedge sizing.

**Entry/exit.** Buy at first tradable minute (09:31 or 09:35, Polygon minute bar — not the auction print). Exit at close_{t+3}. SPY hedge at entry weight β_60d.

**Persistence mechanism.** Form-4 cluster alone is a falsified universal factor; quants abandoned it. But conditioning on a forced overnight gap-down creates a vacuum where indiscriminate sellers (ETF outflows, margin calls, retail stops) cross with the best-informed agents who just anchored "cheap." Overnight liquidity is the structurally hardest window to provide. Not arbed because the standalone signal trades poorly and the joint condition is rare.

**Falsifiable test.**
- Event study 2018–2026, S&P 1500 (or all Polygon common stocks passing liquidity gate, PIT-correct).
- Event-date portfolio aggregation (not pooled stock t-stats).
- **Permutation null:** shuffle Form-4 filing dates within ticker 1000×, preserving cluster frequency.
- **Matched-gap control:** compare to non-insider gap-downs matched on liquidity, gap z-score, β, prior drawdown, sector.
- Phase split: pre-2020, COVID, 2021, 2022, 2023–26.
- **PASS bar:** mean CAPM-α > 25–30 bps/trade net; %-positive phases ≥ 4/5; permutation p < 0.05; matched-gap excess α > 15 bps; N ≥ 150 events.

---

## #3 — VWAP-Confirmed PEAD (Institutional Accumulation Filter)
*(Gemini #2; survived as a PEAD enhancement with surprise-decile matching)*

**Scenario trigger.** Earnings release day with positive surprise (yfinance earnings dates/surprise).

**Exact computable signal.**
- Day 0 intraday VWAP from Polygon minute bars (use 15:50 cutoff to avoid close lookahead).
- Trigger: `Day 0 Close > Day 0 VWAP by > 1.5%` AND `Day 0 Volume > 2× 20d SMA volume`.
- Validate yfinance earnings surprise coverage; supplement from EDGAR 8-K timing where needed.

**Entry/exit.** Enter at 15:55 ET on Day 0 (or Day 1 open if Day-0 entry infeasible). Hold 21 trading days. SPY beta hedge.

**Persistence mechanism.** Large institutions cannot fill on the opening auction without market impact; they execute via TWAP/VWAP algos over multiple days. A close significantly above intraday VWAP on 2× volume is mechanical evidence that institutional algos are "falling behind" liquidity and will continue accumulating. Standard PEAD does not condition on intraday execution evidence — this is the orthogonal piece.

**Falsifiable test.**
- 2018–2026 S&P 500 earnings.
- **Surprise-decile matched comparison:** VWAP-confirmed vs. VWAP-rejected PEAD within same SUE decile, same opening gap bucket, same relative-volume bucket, same sector, same regime. This is the critical control — otherwise the signal collapses to "big-beat PEAD" relabeled.
- Event-study CAPM-α net 30 bps; event-date portfolio aggregation.
- Phase split across all earnings seasons 2018–2026.
- **PASS bar:** matched Δα > 200 bps over 21d window; t-stat > 2.5 on event-level returns; signal monotone across confirmation strength.

---

## #4 — Earnings Gap-Up Opening-Range Failure ("Gap & Crap" Exhaustion)
*(Gemini #4; survived with stricter matched controls)*

**Scenario trigger.** Complacent bull regime: SPY > 50d SMA AND VIX < 15. On earnings day, stock gaps up > 4–5% at open (Polygon minute), then opening-range rejects the gap.

**Exact computable signal.**
- Gap: `open_t / close_{t−1} − 1 > 0.04` to `0.05`.
- First 30-min VWAP (09:30–10:00) using Polygon minute bars.
- Failure condition: 10:00 ET price < 09:30 open AND 30-min VWAP < 09:30 open AND 09:30–10:00 volume > 10% of 20d ADV.
- Liquidity filter: large-cap, easy-to-borrow, ADV > $50M (proxy for borrow availability since we lack borrow-cost data).

**Entry/exit.** Short at 10:00 ET (realistically 10:01 after bar closes). Exit at 15:55 ET (strictly intraday; no overnight). Optional: hold to t+2 close in a separate variant tested independently.

**Persistence mechanism.** Retail buys headline gap-ups via market orders at open; institutions use this liquidity burst to distribute pre-earnings inventory. Intraday short capacity is constrained and risk-limits prevent systematic funds from holding unhedged earnings-day shorts. Not arbed because most fundamental funds cannot run intraday short books and the regime gate further limits the opportunity window.

**Falsifiable test.**
- Intraday event study (10:00 → 15:55) 2018–2026, S&P 500.
- **Matched controls:**
  1. earnings gap-ups with red first candle vs. green first candle (within regime),
  2. non-earnings matched gap-ups with red first candle (controls for opening-range fade alone),
  3. same setup outside complacent regime.
- Gap-size buckets: 4–7%, 7–10%, >10%.
- Event-day portfolio aggregation; intraday β adjustment.
- **PASS bar:** > 50 bps intraday α per trade net of slippage AND > 40 bps relative to matched non-earnings gap-up red-candle null; results stable across gap-size buckets; minimum N ≥ 100 events.

---

## #5 — Insider-Panic Capitulation (Market-Stress Conditioned Insider Cluster)
*(Gemini #1; survived with panic-baseline ablation; complementary to #2)*

**Scenario trigger.** Market panic regime: SPY in >10% drawdown from 252d high OR VIX > 25. Within this regime, ≥2 unique C-suite/Board open-market buys (Form-4 code P) within 5 trading days.

**Exact computable signal.**
- SPY drawdown from rolling 252d high (Polygon EOD).
- VIX level (yfinance).
- EDGAR Form-4: distinct insiders, C-suite/Board flag (from reporting-owner relationship field), code `P`, 5-day window.
- Filing acceptance timestamp must precede entry decision time.

**Entry/exit.** Enter on close of day the second qualifying Form-4 is filed (if accepted before 15:45; else next open). Hold 63 trading days. Compute CAPM-α with β estimated from pre-event window (not contaminated by rebound).

**Persistence mechanism.** Institutional PMs face career risk catching falling knives during VIX>25; they de-gross to meet risk limits. Insiders have zero short-term mark-to-market career risk AND possess asymmetric information about bankruptcy/liquidity risk. Panic-conditioned insider clusters separate the falsified universal signal from the genuine asymmetric-information event. Not arbed because the institutions who would arb it are forced sellers during the trigger regime.

**Falsifiable test.**
- Event study 2018–2026; expect small N (~3 distinct panic windows: Q4 2018, COVID 2020, 2022).
- **Critical ablation — panic-baseline null:** compare insider-cluster panic stocks vs. random panic-window stocks matched on prior drawdown, β, size, sector, liquidity. If indistinguishable, the edge is "buy panic," not "buy insider-panic" — kill.
- **Form-4 date shuffle within ticker** preserving panic-window timing.
- Separate market-panic vs. idiosyncratic-panic legs.
- Jensen's CAPM-α with pre-event β; net 30 bps.
- **PASS bar:** panic-insider α > panic-baseline α by ≥ 300 bps over 63d hold; p < 0.10 on ablation given small-N; consistent sign across all panic windows.

---

## Killed by panel consensus (for completeness):
- **Opus #2 (FOMC intraday reversal):** tiny N (~64 events), crowded by HFTs/dealer gamma, slippage will eat alpha on Alpaca execution. Optional cheap falsification only.
- **Opus #3 (muted-earnings accruals):** PIT lookahead on current-quarter CFO; accruals as universal factor already falsified — Gemini called this a disguised anti-pattern.
- **Opus #5 (S&P recent-adds month-end):** index-event PIT data unclear, heavily arbed, proposal truncated/incomplete.

## Implementation priority (panel consensus):
**Ship #1 first** (highest leverage, config-layer addition that protects live forward-paper run from junk-rally drawdown). Then build minute-bar event pipelines for **#2, #3, #4** in parallel. **#5** ships as a pre-registered hypothesis given small-N constraint.