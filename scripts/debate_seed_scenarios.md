# Panel goal — NEW scenario-conditional trading strategies

> "Find other approaches to trading at SPECIFIC SCENARIOS." Not another universal
> cross-sectional factor — that space is exhausted (see ANTI-PATTERNS). Design
> strategies CONDITIONAL on a scenario: an event, a regime, or a microstructure state.

## Why scenario-conditional (the session's central finding)

Every *universal* cross-sectional signal tested came back null or regime-tilted. The
ONE thing that showed structure is **regime-dependence**: the PEAD+quality beta-neutral
long-short earns +2.5-3% CAPM-α in flight-to-quality/value rotations (2022-2026) but
**−2 to −3% in junk rallies** (2019 melt-up, 2020 H2) — break-even over full history.
So the frontier is not "find a factor that always works" but "find what works in a
SPECIFIC, detectable scenario, and only trade it there."

## Available data (HARD constraint — propose nothing outside this)

- **Polygon EOD + MINUTE bars, 2018-2026** (intraday IS available — VWAP, opening-range,
  overnight-vs-intraday decomposition, intraday reversal/momentum all in scope).
- **EDGAR PIT fundamentals** + raw NI/CFO/total_assets (accruals) + **Form-4 insider** +
  **8-K/10-K/10-Q text** (Postgres; 8-K corpus currently sparse — full ingest is a
  separate project).
- **FINRA short-interest** (~1.5yr, 2024-26 only).
- **yfinance VIX + earnings dates/surprise**; SPY. Postgres live.
- NOT available: paid options/dealer-gamma, analyst estimate revisions, intraday L2,
  tick data, alt-data (satellite/cards/web). Do not propose strategies needing these.

## Scenario families worth probing (suggestions, not limits)

- **Event:** earnings windows (PEAD is the core — find ORTHOGONAL event edges), guidance
  8-Ks, index add/delete, M&A targets, large-gap days, 52-week-high/low breaks.
- **Regime-conditional:** VIX state / term-structure, trend-vs-chop, post-drawdown
  re-entry, breadth thrusts. Explicitly: a META-STRATEGY that gates the existing
  long-quality/short-junk sleeve to its favorable regime (detectable ex-ante?).
- **Calendar / microstructure (EOD or minute-bar observable):** turn-of-month, FOMC-day
  drift, opex week, month/quarter-end rebalancing pressure, overnight vs intraday return
  split, opening-range behavior.
- **Cross-asset state:** SPY/VIX signals, sector-dispersion regimes.

## ANTI-PATTERNS — already FALSIFIED this session. Do NOT re-propose:

- Universal cross-sectional factor zoo: momentum, quality, value, accruals,
  gross-profitability (S&P +0.04 but DEAD on broad universe), asset-growth (era tilt),
  Δmargin, SUE-lite — all null, regime-tilted, or breadth-dead.
- Long-only PEAD + risk-managed-momentum — strong IC but loads beta, negative CAPM-α.
- Multiplicative factor interactions (e.g. accruals×PEAD "Mirage") — null.
- The beta-neutral long-short as an ALL-WEATHER strategy — it's regime-dependent
  (scenario-GATING it is allowed and encouraged; treating it as universal is not).
- Insider-cluster (CMP-2012) + short-interest-delta as cross-sectional factors — null,
  never permutation-significant.
- 8-K filing-TONE via LLM as a cross-sectional factor — null (IC ≈ 0).
- Reactive crash-timing via SMA/VIX gate or VIX-exposure scaling — makes COVID WORSE
  (de-risks into the V-shape rebound).
- Broad-universe breadth — HURTS (mega-cap-led windows); large-cap is the tradeable scope.

## The bar (every proposal ships with this)

Computable on the data layer + a FALSIFIABLE test on the SCENARIO'S OWN sample:
forward-IC or event-study + permutation null, phase-averaged across ≥3 regimes incl. a
junk-rally window, judged on **Jensen's CAPM-α net of 30bps** (not raw excess; not IC
alone). An idea indistinguishable from luck on its scenario is not a candidate.

## Deliverable

A ranked shortlist of 3-6 scenario-conditional strategies, each with: scenario trigger,
exact computable signal, entry/exit, persistence mechanism (why unarbed in THAT
scenario), and the precise test. Prefer orthogonality to the PEAD+quality core. The
panel's output feeds directly into the factor-lab / backtest harness for validation.
