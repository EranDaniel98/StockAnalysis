# Co-design goal

> "I want to come up with a new strategy that will beat the market (SPY, net of costs)."

Start from the seed proposal below and design ONE concrete, implementable strategy.
The proposal was drafted against the *deleted* 0-100 analyzer engine and assumes
data the live stack does NOT have (`dark_pool_block_net`, intraday `amihud_illiquidity_ratio`,
options/dealer-gamma, per-analyzer 0-100 weights). Treat it as a **thesis to adapt**,
not a spec to implement: salvage the structural-inefficiency idea, discard the parts
that need unavailable data, and rebuild it on Polygon EOD + EDGAR PIT + yfinance.

## Seed proposal (Gemini): `institutional_liquidity_shock`

```json
{
  "strategies": {
    "institutional_liquidity_shock": {
      "description": "Exploits institutional accumulation footprints and liquidity constraints via high-intensity flow asymmetry.",
      "time_horizon": "3-10 days",
      "weights": {
        "technical": 0.10, "fundamental": 0.0, "pattern": 0.0,
        "statistical": 0.30, "trend": 0.0, "alpha158": 0.0,
        "insider_flow": 0.15, "catalyst": 0.0,
        "short_interest": 0.20, "sector_flows": 0.25
      },
      "emphasis": [
        "volume_fractional_shock",
        "amihud_illiquidity_ratio",
        "dark_pool_block_net",
        "institutional_accumulation"
      ],
      "min_score": 58, "min_market_cap": 3000000000,
      "prefer_profitable": false, "use_consensus_scaling": true,
      "apply_post_composite_modifiers": true, "time_stop_days": 10,
      "thresholds": {"strong_buy": 64, "buy": 55, "hold_upper": 49, "hold_lower": 42, "sell": 32}
    }
  },
  "architectural_enhancements": {
    "1_cross_sectional_ranking": "Convert raw metrics into daily cross-sectional rankings across the universe.",
    "2_nonlinear_feature_interaction": "Conditional gate filtering — a prerequisite (e.g. volume percentile) must clear before weights compound.",
    "3_asymmetric_volatility_sizing": "ATR / variance-adjusted position sizing by structural volatility."
  }
}
```

## What is actually observable on the live data layer (use these, not the above)

- **Volume / liquidity (Polygon EOD):** daily volume vs trailing distribution, dollar
  volume, **Amihud illiquidity** computed from *daily* |return|/dollar-volume (the EOD-legal
  version), Kyle-lambda-style price-impact proxies, turnover.
- **Price structure (Polygon EOD):** returns, gaps, range, realized vol, the existing
  12-1 momentum and PEAD/earnings-drift signals.
- **Fundamentals (EDGAR PIT):** quality, value (EPS bug caveat), accruals, growth.
- **Holdings / flow (EDGAR filings):** 13F institutional holdings *quarterly* (slow,
  but a real, free, PIT institutional-footprint signal), Form 4 insider transactions,
  13D/G activist stakes.
- **Regime (yfinance):** VIX, SPY trend.
- **Short interest:** semi-monthly exchange short-interest (already in `short_interest_delta.py`).

Note the seed's two best architectural ideas (#1 cross-sectional ranking, #3 vol-aware
sizing) — #1 is *already how the live system works*; #3 is a real, unbuilt gap worth
folding into the new strategy.
