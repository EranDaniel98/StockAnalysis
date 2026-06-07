# StockNew precision panel (10 lenses + synthesis + red-team) — 2026-06-07

Goal: enhance the system to precisely pick the biggest risers over horizon X.

## SYNTHESIS

# StockNew Right-Tail Roadmap â€” Synthesis of the 10-Lens Panel

## 1. The honest reframe (objective + metric)

"Precise at picking the biggest risers over X" is **not** the current objective. Today the system optimizes and validates the **conditional mean**: the composite rank-blends toward mean cross-sectional ordering, the backtest scores an equal-weight top-24 on Sharpe/CAPM-alpha, and factor_lab scores symmetric Spearman IC (rewards getting the bottom half right as much as the top). The new goal is a **sparse, right-tail, horizon-specific, probabilistic** target. Concretely it means:

> At horizon **X**, label each PIT-universe name `1` if its realized forward total return (delisting-inclusive) lands in the **top decile/quintile** of that rebalance's cross-section. Optimize and validate the composite's selected top-K against that label.

**The metric to optimize/validate** (replaces mean-alpha as the acceptance criterion and kill-switch trigger):
- **precision@K** â€” fraction of held names that were actual top-decile risers.
- **upside-capture** â€” Î£(realized return of selected K) / Î£(realized return of oracle top-K).
- **NDCG@K** â€” credits putting the biggest risers at the very top.
- **lift vs a random-selection null** â€” judged **phase-averaged** (rebalance-offset sweep) **and per walk-forward fold**, reported as median/IQR + %-folds-beating-null, **never a single offset**.
- For the "CHANCE" word: a **calibrated P(top-decile riser at X)** scored by Brier/reliability, per-fold not pooled.

Brutal caveat the whole panel agrees on: a top-decile label is ~50 names over ~9 non-overlapping 63d windows. The right tail has **fewer effective independent observations** than the mean objective, so the Â±20-30pp phase-noise envelope **widens**. A system already failing WF 6/7 on the easier objective is **harder**, not easier, to validate on the tail. "Precise" must be defined conservatively, per-fold, against the random null.

---

## 2. Prioritized roadmap (merged across lenses)

Ranked by leverage-on-goal Ã— tractability Ã— robustness-safety. Eight lenses independently nominated "build the right-tail harness first" â€” that convergence decides #1.

### #1 â€” Right-tail measurement harness + WF re-instrumentation `[FOUNDATION]`
*Merges: objective-metric P1, right-tail-convexity P1, robustness P1, data-universe P1.*

- **Mechanism:** At each rebalance, dump per-name realized X-day forward returns (already in the snapshot panel), label the realized top-decile/quintile, and report precision@K / upside-capture / NDCG@K + lift-vs-random for the composite's top-K â€” phase-averaged across offsets and per WF fold, reusing `phase_envelope.py` discipline. **Critically, also fix the WF gate**: `_walk_forward_folds` (run_factor_backtest.py:503-533) currently passes only if every 5-month chunk has **absolute** Sharpe>0 and meanâ‰¥0.5 â€” a long-only Î²â‰ˆ1 book *cannot* clear that through any bear sub-period regardless of selection skill. Replace with per-fold **CAPM-alpha sign/IR** (beta-decoupled) **pooled across all 7 windows** (nâ‰ˆ35 folds) judged on the pooled distribution's t-stat. The "6/7 WF fail" headline is **partly a measurement artifact** of grading the beta path, not the selection edge.
- **Why right tail at X:** These metrics *are* the new objective. Run at Xâˆˆ{21,63,126}d so horizon is explicit.
- **Data:** None new â€” existing Polygon snapshots. **Effort:** medium. **Overfit risk:** low (measurement, not a parameter).
- **First step:** Add `precision@K`/`upside-capture` + the per-fold-alpha pooled WF to `run_factor_backtest.py` and `phase_envelope.py`; re-baseline the *current* production config on it.
- **Validation metric:** median precision@K and %-folds-beat-random vs the random-selection null; pooled CAPM-alpha t-stat.
- **Overfit guard / realistic outcome:** It's a yardstick, not a knob â€” zero added DOF. Realistic outcome: you finally *see* whether the existing edge has any tail content, and you likely discover the WF picture is less catastrophic than "6/7 fail" once you stop grading beta. Nothing downstream is trustworthy until this exists.

### #2 â€” Factor IC-decay + right-tail-hit-rate-by-horizon diagnostic `[FOUNDATION]`
*Merges: horizon-decay P1, regime-timing P1a.*

- **Mechanism:** For each factor (momentum, quality, value, PEAD) compute rank-IC **and top-decile forward-return hit-rate** at Xâˆˆ{5,21,63,126,252}d, walk-forward across the 7 windows, phase-averaged, bucketed by trend-state regime (SPYâ‰¥200-SMA / recovery / down). Output an IC(factor, horizon) matrix + per-factor half-life + P(name in forward top-decile | factor top-decile).
- **Why right tail at X:** Tells you *which factor populates the right tail at each X* (hypothesis: momentum+PEAD own the short/mid tail, quality/value lift the slow mean) â€” the prerequisite for any horizon- or regime-conditioned weighting. Answers whether the goal is even **achievable** at a given X before you build traded machinery.
- **Data:** None new. **Effort:** medium. **Overfit risk:** low.
- **First step:** `scripts/research/factor_ic_decay.py` over existing per-factor frames from `pipeline.py`.
- **Validation metric:** per-factor top-decile lift over the 10% base rate, with permutation null.
- **Guard / outcome:** Measurement only. Outcome is knowledge â€” it converts every weighting idea below from a guess into a falsifiable claim, and it may return the honest verdict "no factor has tail skill at X," which *saves* you the downstream effort.

### #3 â€” Fundamental-acceleration factor (+ 52-week-high proximity companion) `[ONE NEW SIGNAL]`
*Merges: signal-gaps P1+P2, horizon-decay P3, catalyst P2, robustness P2.*

- **Mechanism:** New `src/factors/fundamental_momentum.py` consuming `loader.history(ticker, as_of, edgar_only=True)` (already implemented) to compute the **change and acceleration** (2nd difference of YoY growth) of operating/gross margin, EPS, and revenue across the last 4 clean filings. quality.py/value.py read only the *latest* level via `loader.lookup` and throw the trajectory away â€” this is the orthogonal second-derivative they ignore. Ship alongside a cheap **52-week-high proximity** factor (`close / max(High, 252d)`, George-Hwang anchor) as the low-overfit complement. Add both as composite frames with `min_overlap` unchanged so missing-history names stay neutral.
- **Why right tail at X:** Re-ratings concentrate in the right tail â€” firms inflecting flatâ†’accelerating margins/EPS get the largest multiple expansion, drift persists 1-3 quarters (X=63-126d). Names punching through the 52w high are disproportionately the biggest subsequent risers, with a smaller crash tail than raw 12-1. Both target *who is about to move most*, not who is already good (priced in).
- **Data:** None new â€” EDGAR PIT already frozen per-snapshot; prices for the 52w-high. **Effort:** medium / low. **Overfit risk:** medium / low.
- **First step:** Build the acceleration factor, score it through the #1 harness across all 7 windows phase-averaged before wiring any weight.
- **Validation metric:** does the composite's precision@K / upside-capture beat the current equal-weight blend **per WF fold**, not just in aggregate.
- **Overfit guard / outcome:** **Freeze the weight by economic prior** (equal or 0.5Ã—, locked â€” do not tune on the 7 windows). It is genuinely orthogonal to the three level factors, so realistic outcome is a *modest honest* tail-precision lift if accepted, or a clean null. The 52w-high is the safest single addition in the whole panel.

### #4 â€” Isotonic right-tail calibration + per-name phase-stability abstention `[REFRAME OUTPUT]`
*Merges: probability-calibration P1+P3, objective-metric P3, ml-rank P2.*

- **Mechanism:** Downstream of `composite.combine`, fit **isotonic regression** (monotone, ~1 DOF) mapping composite percentile â†’ **P(top-decile riser at X)**, trained only on prior WF folds, frozen per-snapshot for determinism. Surface this probability in `daily_factor_picks` + the API instead of bare rank. Pair with **per-name phase-stability**: reuse the `phase_envelope` rebalance-offset jitter to measure how often each name stays in the top bucket across perturbations; drop phase-fragile names (top-ranked at only one offset = luck) and **abstain** (hold <24 / partial cash via existing gate plumbing) when too few names clear a confidence threshold.
- **Why right tail at X:** The output literally becomes "best CHANCE to rise the most at X." Abstention directly attacks fold-fragility â€” stop forcing a fixed top-24 when the cross-section is uninformative, which is the 6/7-fail signature.
- **Data:** None new. **Effort:** medium. **Overfit risk:** low (monotone, near-zero added DOF).
- **First step:** Isotonic layer + per-fold **reliability diagram** (never pooled).
- **Validation metric:** out-of-time Brier score + reliability curve (a name you call P=0.4 hits ~40%); precision@K of the abstaining book vs the forced top-24.
- **Guard / outcome:** Calibration manufactures no edge â€” it makes the existing modest edge *honest* and converts fragility into abstention/sizing. Realistic outcome: "still fragile, but now you know when, and you don't bet into it."

### #5 â€” Monotone-constrained LambdaMART on existing z-scores, NDCG@K, purged+embargoed WF `[INTERACTION TEST]`
*From: ml-rank P1. Do only AFTER #1-#4.*

- **Mechanism:** LightGBM `lambdarank` head with features = **only** the 4-6 z-scores already produced (momentum, quality, value, PEAD, regime, sector) â€” no feature zoo. Query = each rebalance cross-section, target = forward-X-return rank, loss = **NDCG@24** (dominated by getting the top right). Hard capacity control: `monotone_constraints` from economic priors (all +), max_depth 2-3, high min_child_samples (~5% universe), â‰¤8 leaves, strong L1/L2, ~50-100 trees. Validate **only** under Lopez-de-Prado **purged + embargoed** WF (embargo â‰¥ horizon X to kill the 63d overlapping-label leak) + phase-averaging. Ship only if it beats the linear blend under that identical protocol.
- **Why right tail at X:** NDCG@24 *is* a right-tail objective; depth-2 trees express the conjunction ("momentum counts as top-tier only when PEAD>0 and regime=on") that a linear blend structurally cannot â€” your own data shows fundamental IC flips sign by VIX regime.
- **Data:** None new. **Effort:** medium. **Overfit risk:** medium (controlled by construction).
- **First step:** Fit at X=63d under purged WF; compare NDCG@24 / precision@24 to the linear blend on the **same** folds.
- **Validation metric:** beats linear per-fold under purged+embargoed WF + phase-averaging, or it's a NULL.
- **Guard / outcome:** **Win-or-clean-null by design.** Either it turns 1-2 failing folds positive and aligns the objective, or it proves non-linearity is not the lever and stops the ML rabbit-hole. Few features + monotone signs + tiny parameter count + the protocol that already exposes fragility = the only disciplined way to test interactions. Realistic outcome: most likely a NULL â€” but a *valuable* one.

---

## 3. Graveyard handling â€” genuinely new vs re-skins (cut the re-skins)

**Genuinely NEW (kept above):**
- Fundamental acceleration (2nd derivative of EDGAR) â€” graveyard killed *price* residual momentum and 8-K text; nobody tried growth-of-growth on fundamentals.
- 52-week-high proximity â€” distinct mechanism from 12-1 (anchoring vs return ratio); unrelated to killed MAX/lottery.
- Isotonic right-tail probability + per-name phase-stability â€” every graveyard item was a new *signal*; this relabels/recalibrates the existing composite. The phase envelope was only ever a portfolio-level caveat; pushing it to per-name is new.
- Monotone LambdaMART â€” distinct from killed Kronos (no fold-fragility defense, no monotone constraints) and from hand-set regime_weights.
- The measurement harness + WF fix â€” not a signal at all; orthogonal to the entire graveyard.

**CUT as re-skins or too-fragile-to-ship:**
- **Recovery-event tilt** (regime-timing P3) â€” only ~2-3 re-entry events 2017-2026. Highest-overfit item in the panel; treat as a hypothesis to *falsify* on #2's recovery buckets, never ship on a single win.
- **Quantile-regression q90 head** (probability-calibration P4) â€” "high overfit, high effort," closest to the banned "throw ML at it." Subsumed by #5 done more safely.
- **Naked upside-semivol / dispersion-timing / breadth-weighting** (right-tail-convexity P2/P3, regime-timing P2) â€” defensibly *distinct* from killed VIX-percentile/exposure-scaling and MAX (conditioned on signal, cross-sectional not VIX), but each adds a tunable on ~2-3 regime episodes. **Demote to research arms gated behind #1+#2**; do not ship until the harness shows the unconditioned factor has tail skill to condition.
- **Russell-1000 breadth** is correctly buried; but note data-universe's sharp point: the kill measured *mean alpha on a survivorship-contaminated mega-cap window*, a different question from **PIT-clean mid-cap (S&P 400/600) scored on tail hit-rate**. That is genuinely new and is the real structural lever (see verdict) â€” but it's high-effort (EDGAR backfill ~900 names + membership oracle) and must wait until #1 proves a tail edge exists to transfer.
- **Analyst estimate-revision breadth** (signal-gaps P4) â€” the highest-ceiling signal and *not* the killed news-sentiment (numbers moving, not journalist tone), but yfinance/finviz expose only *current* estimates â†’ **unbacktestable on $79**. Start a forward-capture cron now; it can only ever be forward-paper validated. Do not let it jump the queue ahead of what survives WF.
- **Catalyst earnings-window tilt** (catalyst P1) â€” promising and explains the 0-Sharpe 8-K null (wrong tail measured), but requires freezing the earnings calendar into snapshots (PIT-proxy caveat). Worth doing *after* #1-#3, conditioned not additive, judged on precision@K.

---

## 4. Core weakness (fold-fragility) â€” per-item defense

| Item | Overfit guard | Realistic outcome |
|---|---|---|
| #1 Harness + WF fix | Zero added DOF; pooled across 7 windows; random-null floor | Reveals fragility is *partly artifact* (beta-path grading); honest baseline |
| #2 IC-decay diagnostic | Measurement only; permutation null per factor/horizon | May say "no tail skill at X" â€” that's the saving result |
| #3 Acceleration + 52w-high | Weight **frozen by economic prior**, never tuned on the 7 windows | Modestly more precise **or** clean null; orthogonal so low downside |
| #4 Isotonic + abstention | Monotone ~1 DOF; per-fold reliability, never pooled | "Still fragile but honest + abstains when fragile" |
| #5 LambdaMART | depth-2, monotone signs, â‰¤6 features, purged+embargoed WF | Most likely a **valuable NULL**; bounded by linear-blend floor |

Cross-cutting guard the panel demands: maintain a **trials ledger** and apply the **Deflated Sharpe Ratio** (Bailey-LÃ³pez de Prado) to any new candidate's pooled t-stat â€” ~30 graveyard variants were tuned on the same 7 windows, so family-wise error is severe and no correction was ever applied. **Freeze the factor set** to literature-backed priors (12-1, quality, value, PEAD, fundamental-acceleration); permit only construction/measurement changes henceforth. Embargo â‰¥ X kills the 63d overlapping-label leak.

---

## 5. Verdict (no hype)

**Can this system be made to reliably predict the biggest risers? On the current budget and universe â€” no, not "reliably."** The reframe makes the problem *harder*, not easier: the right-tail label is sparser than the mean objective the system already fails to validate fold-by-fold, and the biggest 63d S&P risers are dominated by idiosyncratic catalysts (beats, M&A, guidance) that slow rank factors don't predict. The honest realistic ceiling is **a modestly-better-than-random, calibrated, abstaining tail-ranker** â€” not a dependable biggest-riser oracle.

**The single most-promising path** is sequential and measurement-first:
1. **#1 + #2 (harness + decay diagnostic)** â€” cheap, low-overfit, and they answer the only question that matters before any signal work: *does the existing edge have tail content at any (K, X), and which factor carries it?* Most of the value of this whole roadmap is here.
2. If yes â†’ **#3 (the one new orthogonal signal: fundamental acceleration + 52w-high)** with a frozen prior weight, plus **#4 (isotonic calibration + abstention)** to make the output honest and stop betting into fragile cross-sections.
3. **#5** only as the disciplined interaction test, expecting a null.

**The real structural ceiling is the universe, not the model.** Mega-caps cannot 3-5Ã—; the right tail lives in mid/small caps the S&P-500 PIT universe excludes by construction. The genuinely unexplored lever is a **PIT-clean S&P 400/600 expansion scored on tail hit-rate** (distinct from the survivorship-contaminated Russell-1000 kill) â€” but spend that EDGAR-backfill effort **only after #1 proves a tail edge exists to transfer**, and accept it may show breadth still hurts.

Do **not** expect to "solve" biggest-risers. Expect to: (a) finally measure the tail, (b) discover the WF picture is less dire than the beta-graded "6/7 fail" suggests, (c) add one honest orthogonal signal, and (d) ship a calibrated book that **abstains when it has no edge** â€” which is a real improvement over a forced top-24 it can't defend.

---

## RED-TEAM

## Adversarial review â€” StockNew right-tail roadmap

The roadmap is unusually self-aware (it cuts its own re-skins and lands on "no, not reliably"). That makes it more dangerous, not less: the remaining flaws are the ones dressed up as "zero-DOF measurement." Per-item below, then verdict.

---

### #1 â€” Right-tail harness + WF re-instrumentation

**(a) Failure mode â€” the WF "fix" is goalpost-moving disguised as measurement.** The precision@K / upside-capture / NDCG half is genuinely zero-DOF; keep it. But "replace per-fold absolute-Sharpe>0 with **pooled** CAPM-alpha t-stat across nâ‰ˆ35 folds" is the single most dangerous line in the document. The core weakness IS fold-by-fold fragility. Pooling across folds is precisely the operation that *erases* fold-by-fold information â€” you let a 2023 win pay for a 2020 loss, which is the one thing walk-forward exists to forbid. And "nâ‰ˆ35 independent folds" is fiction: 63-day overlapping labels + 7 *overlapping* rolling windows means effective N is a small fraction of 35, so the pooled t-stat is inflated by autocorrelation. The claimed outcome ("WF picture is less dire than 6/7") is partly *manufactured by choosing a more permissive test*. The beta-grading critique has a real kernel (a long-only Î²â‰ˆ1 book can't clear absolute-Sharpe>0 in a bear sub-period â€” that conflates beta path with selection). The honest remedy is to grade each fold on **beta-neutral alpha and keep per-fold pass/fail**, then judge the *distribution* (% folds positive, sign consistency) â€” NOT collapse to one pooled t-stat.

**(b) Re-skin?** No â€” measurement is new.
**(c) Right tail at X?** The metrics half, yes. The WF-redefinition half sneaks back toward "aggregate pass," the opposite of what's needed.
**(d) Inside envelope?** It *measures* the envelope; can't shrink it. Note precision@K on ~50 top-decile names over ~9 windows has a **wider** envelope than mean-alpha (roadmap admits this) â€” so the harness is the right yardstick but every downstream "lift" it scores will sit near the floor.

### #2 â€” Factor IC-decay + right-tail-hit-rate diagnostic

**(a) Failure mode â€” null-by-underpower, misread as null-by-no-edge.** ~50 top-decile names/window Ã— 7 windows, then bucketed by 3 regimes Ã— 5 horizons â†’ per-cell N â‰ˆ 10â€“15. You cannot distinguish a 12% hit-rate from a 10% base rate at that N. The "honest verdict: no tail skill at X" is the *most likely* output **regardless of whether skill exists**, because the test has near-zero power. Cheap and worth knowing, but do not let an underpowered null be read as "no edge."
**(b)** Not a re-skin. **(c)** Honestly right-tail. **(d)** Measures inside the envelope.

### #3 â€” Fundamental-acceleration + 52-week-high

**(a) Failure mode â€” both are likely momentum in disguise, and the gain is below the detection floor.**
- *Fundamental acceleration (2nd diff of YoY growth):* second differences of noisy quarterly EDGAR data amplify restatement/seasonality/one-time noise quadratically; on a 24-name top-K the SNR is poor. Worse, the orthogonality claim is wrong-headed: **price momentum already prices in accelerating fundamentals** â€” the re-rating *is* the momentum. Expect high collinearity with the existing 12-1 factor â†’ adds nothing (echoes your own "composites add nothing" finding, `strategy_debate_candidates`).
- *52-week-high (Georgeâ€“Hwang):* genuinely near-zero-DOF and the safest single item â€” but on S&P 500 mega-caps, proximity-to-52w-high is *also* tightly correlated with 12-1 momentum. Georgeâ€“Hwang is strongest in broad universes; incremental content over momentum on 500 large-caps is thin.

**(b) Re-skin?** Acceleration: adjacent to momentum/killed-growth attempts â€” partial new-mechanism credit, but flag the collinearity. 52w-high: distinct mechanism (anchoring), not the killed MAX/lottery â€” legitimately new.
**(c) Right tail at X?** Yes if scored through the harness.
**(d) Inside envelope? YES â€” fatally.** The roadmap's own best case is "modest honest lift." A modest lift is, by the roadmap's own Â±20â€“30pp envelope, **unmeasurable per-fold**. This is the contradiction the roadmap never confronts: it greenlights a signal whose honest ceiling is *below its own mandated detection threshold*.

### #4 â€” Isotonic calibration + per-name phase-stability abstention

**(a) Failure mode â€” calibrating a non-stationary edge, and abstention = the timing the system is provably bad at.**
- *Isotonic:* the rankâ†’P(top-decile) map is assumed stationary across folds. The whole finding is that it is NOT (6/7 fail; fundamental IC flips sign by VIX). A curve fit on past folds will be *miscalibrated out-of-time exactly when it matters*. The product claim ("best CHANCE") requires a trustworthy probability â€” which a non-stationary edge structurally cannot deliver. Honest, but it undercuts the headline deliverable.
- *Abstention:* "hold <24 / partial cash" **is a market-timing decision**, and Treynor-Mazuy already shows the system has *negative* timing gamma. Per-name abstention in "uninformative" cross-sections risks being a re-derivation of the regime gate that already whipsaws in choppy bears. Also: precision@K trivially rises as you cherry-pick the most-confident names â€” you must score **upside-capture at fixed capital**, or you'll mistake "trading less" for "selecting better."
**(b) Re-skin?** Abstention-as-timing is adjacent to the killed VIX-gate/exposure-scaling; per-name phase-stability is the new part. Borderline.
**(c)** Per-name stability honestly targets fragility; calibration is honest-but-untrustworthy.
**(d)** The interesting part (abstention) directly attacks the envelope rather than fighting inside it â€” the one item here with a real structural rationale.

### #5 â€” Monotone LambdaMART, NDCG@K, purged+embargoed WF

**(a) Failure mode â€” not enough independent query groups to learn interactions.** ~9 non-overlapping cross-sections = **~9 independent ranking events**. NDCG@24 variance across 9 query groups is enormous; depth-2 interaction trees fit on 9 cross-sections will not generalize, and the "momentumÃ—PEADÃ—regime conjunction" needs those interactions *stable* across windows â€” the same non-stationarity that kills everything else. Plus family-wise error: ~30 graveyard variants already tuned on these 7 windows; a "win" here needs Deflated-Sharpe correction that NDCG doesn't cleanly admit. Most likely a null â€” but "valuable null" is generous (Kronos was also a "clean test" and still cost real effort).
**(b)** Distinct from Kronos (no neural price model; monotone + fold defense). Legit.
**(c)** NDCG@24 honestly targets the tail.
**(d)** Any per-fold win sits inside the envelope at 9 query groups. Correctly deferred.

### Universe lever (S&P 400/600) â€” the roadmap's "real structural ceiling"

Intellectually honest, operationally a trap. The right tail does live in mid/small caps â€” but so do (i) the worst EDGAR/price data quality, (ii) bid-ask spreads that make your paper fills fantasy, and (iii) the idiosyncratic catalysts (M&A, biotech readouts, squeezes) that **no slow rank factor predicts** â€” which is the roadmap's own stated reason the goal is hard. You already have direct evidence breadth HURTS this regime (-9.3% vs +9.3%). "Different question (tail hit-rate, PIT-clean)" is true but costs ~900-name EDGAR backfill + a 400/600 membership oracle, multi-month, against a strong prior-of-failure and new tradeability problems the S&P 500 doesn't have. It's not a lever; it's a harder, lower-liquidity game.

---

## The meta-flaw the roadmap won't say out loud

Its own eval discipline (Â±20â€“30pp envelope, *wider* on the sparser right tail) means nearly every **proposed gain** â€” #3 "modest," #4 "honest modest," #5 "likely null" â€” is **below its own detection floor**. The roadmap is honest enough to call the gains modest but never connects *modest < envelope = unmeasurable*. The only items that survive that logic are the ones that **measure the envelope instead of trying to beat it** (#1 metrics, #2). Everything that adds a signal or a model is, by the document's own numbers, unfalsifiable on this budget.

---

## GREEN-LIGHT (2)

**1. The measurement half of #1 + all of #2, as one sprint â€” but strip the WF-gate redefinition.**
Add precision@K / upside-capture / NDCG@K + lift-vs-random to `run_factor_backtest.py` and `phase_envelope.py`; build the factorÃ—horizon IC + top-decile-hit-rate matrix. **Keep per-fold pass/fail; just compute it on beta-neutral alpha and judge the distribution (% folds positive, IQR), never a pooled t-stat.** This is the only zero-DOF, falsifiable, envelope-aware work in the roadmap, and it answers the one gating question: *is there any tail content at any (K,X), and which factor carries it.*
- *Cheapest validation:* re-baseline the **current production config** on precision@K vs random null, phase-averaged, per fold. Days, no new data. If top-K precision doesn't beat random per-fold, nothing downstream is worth building â€” stop.

**2. The 52-week-high factor ONLY (drop fundamental-acceleration) â€” as a one-run orthogonality probe.**
Near-zero-DOF, one line, literature-backed, distinct mechanism. Worth exactly one harness run *with a pre-registered expectation of momentum-collinearity*.
- *Cheapest validation:* before scoring it, compute `corr(z_52whigh, z_momentum)` (one line). If |corr| > 0.6, **stop â€” it's momentum**. If lower, residualize on momentum and score the residual's top-decile hit-rate through #1. Freeze the weight by prior; never tune.

## CUT

- **#1's WF redefinition (pooled CAPM-alpha t-stat across 35 non-independent folds)** â€” goalpost-moving; inflated by overlap autocorrelation; hides the exact weakness it claims to expose.
- **Fundamental-acceleration (#3a)** â€” 2nd-derivative noise Ã— momentum collinearity; expected null inside the envelope at medium effort. At most, compute its IC inside #2 first; build only if it shows non-momentum-overlapping hit-rate (it won't).
- **#5 LambdaMART** â€” defer indefinitely; ~9 independent query groups cannot support interaction learning. Revisit only if #1/#2 prove real tail content *and* you have more OOS windows (i.e., the paid history tier).
- **S&P 400/600 expansion** â€” cut on this budget: data quality + slippage + breadth-hurts prior + multi-month cost. It changes the game to one with worse fills, not a lever on the current one.
- **#4 â€” split:** cut isotonic calibration as a *product* (untrustworthy probabilities on a non-stationary edge). Demote per-name phase-stability abstention to a research arm, and measure it on **upside-capture at fixed capital**, not precision@K â€” and prove it isn't just the negative-gamma timing gate in a new costume.
