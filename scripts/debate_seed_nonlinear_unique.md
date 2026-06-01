# Co-design goal — a UNIQUE edge via nonlinear feature interaction

> "Keep debating until we find something unique." Not another mined factor.

This session builds on Gemini's architectural concept #2: **Nonlinear Feature
Interaction / Conditional Gate Filtering** — a prerequisite must clear before
weights compound; factor A's payoff flips sign or magnitude *conditional on* B.
A true interaction, `signal = f(A, B)`, NOT an additive z-sum.

## The hard demand (read carefully)

The previous co-design (IAS: signed-dollar-volume + Amihud + short-interest) was
buildable but, by its own verdict, *"may already be partially arbed"* — those live
in every quant's factor zoo. **That is exactly what we do NOT want this time.**

- The novelty must live in the **STRUCTURE** — a nonlinear / conditional interaction
  that a standard *linear* multi-factor model (what every quant runs) structurally
  cannot capture — not in some exotic new input.
- Use ONLY the existing data layer (Polygon EOD + EDGAR PIT fundamentals & filings
  + yfinance VIX/earnings + semi-monthly short interest + Alpaca). No dark-pool,
  options, intraday, or paid alt-data.
- The system's real moat is **EDGAR point-in-time-from-filings** (fundamentals as
  originally filed, before wide dissemination / restatement). Interactions between
  PIT-fundamental *surprises or revisions* and the subsequent price/liquidity
  reaction are far less mined than pure price-volume. Lean here.

## Rules for this session

1. **Generate 2-3 candidate conditional/nonlinear edges each, then KILL the ones
   that are already arbed or that a linear model already captures.** Be ruthless.
   Don't fall in love with the first plausible idea (that's how we got IAS).
2. **Converge on ONE edge only if you can name its PERSISTENCE MECHANISM** — the
   structural reason it survives arbitrage: data latency, capacity limit, behavioral
   constraint, market segmentation, accounting opacity, attention scarcity. *"It
   backtests well" is NOT a mechanism.* No mechanism → not unique → say so.
3. The interaction must be expressible as `signal = f(A, B)` where the dependence on
   A **flips sign or magnitude conditional on B** (a genuine interaction). State the
   exact conditional form (gate, product, regime-switch, non-monotonic decile map).
4. Still EOD-buildable + must ship with the phase-averaged + permutation-null +
   placebo validation plan from the prior session.

## Candidate territory worth probing (suggestions, not mandates)

- **PIT-fundamental revision × liquidity/attention state:** does a quality or
  earnings-quality revision pay *more* when liquidity is thin or analyst attention
  is low (slow diffusion)?
- **Cross-sectional dispersion regimes:** factor X only pays when cross-sectional
  return/fundamental dispersion is high (or low) — condition payoffs on the regime.
- **As-filed accounting asymmetries** that need PIT data to even observe: accrual
  reversals, restatements, footnote-driven quality shifts the consensus hasn't
  repriced.
- **Non-monotonic responses:** extreme deciles behave *opposite* to the linear slope
  (a linear model averages this to ~zero and misses it entirely).

## Required end state

ONE conditional-interaction strategy with: a NAMED persistence mechanism, the exact
conditional math, and a validation plan — **OR** an honest null: *"everything we
generated is already arbed, and here's the structural reason why."* A defensible null
beats a dressed-up known factor.
