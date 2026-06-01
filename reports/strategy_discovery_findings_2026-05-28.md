# Strategy Discovery — Findings & Verdict (2026-05-28)

Autonomous Opus↔Gemini discovery loop + multi-regime factor lab. Branch
`feat/strategy-debate`. All numbers are **phase-averaged** (9 rebalance offsets)
**Jensen's CAPM-α**, never single-offset. Datasets: S&P-500 PIT for 2018-20,
2020-22 (COVID), 2022-24, 2024-26, plus a 2000-name broad universe (2024-26).

## Bottom line

One candidate survived to a portfolio-level edge; it is **scoped, not a home run**:

> **PEAD + quality, beta-neutral long-short, S&P-500 large-caps.**
> Robust market-neutral CAPM-α in normal regimes — **+3.3%/yr at 30bps in the
> bull, +7.4% in the bear, 100% of phases positive** — with a **documented
> factor-crash tail in COVID-type events (−3.7%) that cannot be timed away.**

Everything else tested either failed the breadth test, was a regime/beta tilt, or
had IC without portfolio alpha. **The only durable, generalizable signal remains
the small PEAD + quality core the live system already trades.** A genuinely *new*
edge needs new data (see last section), not more search on this data.

## The surviving candidate — evidence

The lever is **construction, not a new factor**: the same factor family is
negative/sub-bar long-only (loads market beta) but positive once beta is hedged
out via a dollar-neutral long-short (top/bottom decile).

| Regime / test | CAPM-α (median) | %-phases + | verdict |
|---|---|---|---|
| Bull 2024-26 @5bps | +4.2% | 100% | ROBUST |
| **Bull 2024-26 @30bps** (cost stress) | **+3.3%** | 100% | ROBUST |
| Bear 2022-24 @5bps | +7.4% | 100% | ROBUST |
| COVID 2020-22 @5bps | **−3.7%** | 0% | FRAGILE |
| Broad universe (2000 names) @5bps | **−10.7%** | 22% | FRAGILE |

**Honest caveats (do not skip):**
- **S&P-500-large-cap ONLY.** Collapses to −10.7% on the broad universe. Defensible
  as scope (market-neutral needs liquidity + shortable borrow, which small/mid-caps
  lack) — but it does not generalize.
- **COVID factor-crash tail (−3.7%).** Intrinsic to factor long-shorts (junk rips,
  short leg blows up on the V-shape rebound). **Not timing-fixable** — proven below.
- **Walk-forward pass rate is low (0–22%)** even where the phase-median is positive.
  The per-fold consistency is weaker than the phase-median suggests; treat the
  alpha as real-but-fragile, size accordingly.
- Magnitude is modest; thins further with real financing/borrow costs beyond 30bps.

**Crash-timing does NOT fix COVID (tested, both failed):**
- Regime gate (200/75-SMA + VIX): COVID −3.7% → **−7.7%** (worse).
- VIX exposure circuit-breaker (scales gross down at high VIX): COVID → **−5.0%**
  (worse), bull preserved (+4.2%), bear dented (+6.6%).
- Mechanism: both lag the 5-week crash and **de-risk into the rebound**. Reactive
  market-based crash-timing fights the V-shape and loses. The right management is
  **gross-exposure sizing + drawdown limits + disclosing the tail**, not a crash
  timer. (A live news-LLM crisis detector is a plausible *forward* overlay but is
  not backtestable here — no point-in-time historical news.)

## What failed, and why (so it isn't re-tried)

- **Mirage (accruals × PEAD interaction):** NULL across 3 regimes. The attention-
  gating adds nothing over plain accruals; interaction novelty falsified.
- **Gross profitability (Novy-Marx):** +0.04 IC on S&P but **dead on the broad
  universe** — a mega-cap artifact. The breadth test caught it.
- **Asset growth:** strongest *relationship* but **inverted** vs the textbook
  anomaly (high-growth won 2018-26) = a growth/era style tilt, not alpha.
- **PEAD + risk-managed momentum (long-only):** strong cross-sectional IC, but
  **negative ungated portfolio CAPM-α** — loads beta, no residual alpha. (RM-MOM
  itself beats raw momentum by ~+5pp CAPM-α and dampens the momentum crash — kept
  as a **momentum-leg upgrade**, available via `--momentum-flavor risk_managed`.)
- **QGF-6 / lean composites, SUE-lite, margin-CV, de-leveraging:** real but modest,
  none beats the PEAD+quality core by the required margin. Defensive legs (margin-CV)
  are positive in bear/flat regimes and negative in the bull — the mirror image of
  momentum — confirming offensive/defensive complementarity but no standalone win.
- **Every multiplicative interaction and additive multi-leg composite:** added
  nothing over the best single leg.

## Infrastructure built this session (reusable, committed)

- `scripts/strategy_debate.py` — Opus 4.7 ↔ Gemini 3.1 Pro debate orchestrator
  (`--mode critique|collab`, `--seed-file`).
- `scripts/factor_lab.py` — cross-regime forward-IC + permutation-null screener
  (the evaluator; full leg set + combos).
- `src/factors/accruals_pit.py` + `scripts/build_accruals_sidecar.py` — Postgres-free
  PIT quarterly Sloan accruals from SEC companyfacts (YTD-unpacked). `data/edgar_cache/`
  holds 1797 cached companyfacts.
- `src/factors/momentum.py:risk_managed_momentum` + `--momentum-flavor risk_managed`.
- `scripts/phase_envelope.py` — now parallelized across cores (~8× on this box).

## Differentiated data — TESTED 2026-05-29, NULL

The highest-EV untested avenue (and a prematurely-closed one — the insider data was
fine, 97.7% of 316K rows in 2018-26; the "corrupted" call was a min/max-glance error).
Wired Postgres **insider-cluster** (CMP-2012 distinct open-market buyers, PIT) +
**short-interest-delta** into the lab and tested 2024-26 S&P + broad × 5 horizons:

- **insider_cluster:** faintly positive on the broad universe at long horizons
  (+0.02..+0.04, H21-63) but **permutation p = 0.43-0.57 — never significant**;
  negative/noisy on the S&P (only 5-8 names cluster). The famous CMP-2012 effect does
  **not** replicate here.
- **short-interest-delta:** mostly null. One cell (BROAD/H63 +0.047, p=0.01; SP/H5
  p=0.04) but **2-of-10 ≈ chance**, adjacent horizons don't corroborate, and the SI
  data is only ~1.5yr (2024-26) so it **can't be regime-validated**.

→ Neither carries tradeable cross-sectional alpha here. The last numeric-data stone is
turned, and it reinforces the verdict: no differentiated edge beyond PEAD+quality.

## What would still unlock a genuinely new edge (needs spend, not more search)

1. **LLM-as-alt-data (#3, OpenAI):** the one genuinely-*different* approach — but a
   coverage check (2026-05-29) found the `filings_corpus` has only **54 tickers**
   (~3% of broad), almost all **8-K**, with 10-K/10-Q text from **1 ticker each**. Not
   buildable as a cross-sectional factor without first ingesting filings for the full
   universe (500-2000 tickers) — a real data-engineering project + OpenAI extraction
   cost. Deferred: needs universe-wide filing ingestion before it's even testable.
2. **Analyst-estimate revisions** — the robust anomaly we have no clean proxy for.
3. **Options / dealer-gamma flow** — where the institutional-footprint ideas died for
   lack of data.
4. **Longer-history short-interest** (current is ~1.5yr) — would let the faint
   BROAD/H63 short-covering whisper be regime-tested instead of dismissed as noise.

## Tooling perf (this session)

`factor_lab` is now process-parallel per cell + a vectorized permutation null (one
matmul vs n_perm scipy calls, verified to ~1e-17): a 10-cell battery runs in ~146s
(~9 cores) vs ~15-20min single-core. `phase_envelope` parallelizes its offset
subprocesses. Cores used = number of independent cells; finer-grained chunking was
tried and reverted (redundant Ctx builds cost more than the parallelism saved).

## Status of the live system (unchanged)

The forward paper run (shipped config, started 2026-05-27) is the un-overfittable
OOS test, reviewed ~2026-08-27. **Nothing here was deployed** — deploying mid-OOS
would contaminate it. If the long-short clears further scrutiny (longer windows,
borrow-cost modeling, gross-sizing for the tail), it is a candidate for a
**market-neutral sleeve** *after* the August review — not a replacement for the core.
