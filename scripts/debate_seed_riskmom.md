# Loop iteration — beat PEAD+quality with a DEFENSIBLE, breadth-robust signal

> Discovery loop. We test candidates in `scripts/factor_lab.py` (cross-regime
> forward-IC + permutation null, 5 datasets incl. the 2000-name broad universe).
> Propose CONCRETE formulas on available fields; we test immediately.

## Where we are (validated across 5 datasets incl. broad universe)

- **PEAD** = the only sign-stable, breadth-robust POSITIVE alpha (positive in all 10
  cells, t up to 2.5 on the broad universe). Small (+0.015–0.028). Already live.
- **Momentum (12-1)** is STRONG on the broad/recent universe (t=3.5 @63d) but
  **crashes in COVID and 2022** (IC −0.01 to −0.03). Regime-fragile — the classic
  momentum-crash problem.
- **gross-profitability**: DEAD on the broad universe (S&P-only artifact). Don't reuse.
- **asset_growth**: strongest relationship but INVERTED vs CGS (high growth won
  2018-26) = a growth/era tilt, not alpha. Don't treat as edge.
- **All composites (QGF6/lean) + multiplicative interactions (Mirage): add nothing.**

## The ask — untested, economically-defensible, breadth-robust candidates

Momentum has the most signal but is fragile. The highest-value direction is to FIX
its crash risk with documented methods, and to find genuinely orthogonal small edges.
Propose exact formulas (field, lookback, sign) for, at minimum:

1. **Risk-managed / vol-scaled momentum (Barroso & Santa-Clara 2015):**
   `mom_12_1 / realized_vol_126d` (or scale each name's momentum by its own trailing
   vol). Thesis: momentum crashes are concentrated in high-vol rebound regimes;
   vol-scaling cuts the crash. Defensible, not an era tilt. Test on broad + COVID.
2. **Idiosyncratic volatility (Ang-Hodrick-Xing-Zhang 2006):** −(std of residuals
   from a market-model regression of daily returns over 60-90d). Low idio-vol
   historically outperforms. Computable from Polygon EOD + SPY.
3. **Short-term reversal, broad/small-cap:** −1-week or −1-month return — known to be
   stronger in smaller names; test specifically on the 2000-name broad universe.
4. **Seasonality / same-month return:** a stock's historical same-calendar-month
   average return (Heston-Sadka). Cheap, orthogonal.
5. **The lean combination:** the best 2-3 leg blend of {PEAD, risk-managed momentum,
   idio-vol} that LIFTS IC above PEAD alone AND is sign-consistent on the broad
   universe + ≥3 regimes. Equal-weight sector-rank sum (NOT products).

## Bar to clear (else we discard)

Sign-consistent ≥80% AND permutation p<0.05 in ≥6/8 S&P-regime cells AND on the broad
universe; mean IC ≥1.3× the PEAD+quality baseline; direction economically defensible
(not beta/era timing like low-vol or asset-growth). Rank the candidates by expected
robustness and name each one's persistence mechanism.
