# Live Trading Logic

Traced from the actual code (file:line citations). Three stages: **gate → select →
execute**. Entry point: `scripts/daily_factor_picks.py` → `src/factors/pipeline.py`
→ `scripts/paper_trade_factor_picks.py`.

## One-sentence summary

> If SPY is above its 75-day SMA, rank the point-in-time S&P 500 by an equal-weight
> blend of momentum + sector-neutral quality + value (+ optional PEAD), stickily hold
> the top 24 capped at 30%/sector, equal-weight, and rebalance every 63 days via
> Alpaca — otherwise sit in cash.

All parameters (top_n=24, 30% sector cap, 75-SMA gate, 0.75 hysteresis, 63-day cadence)
are config-driven (`config/*.yaml`) and were set by backtests (see the memory log).

---

## Stage 1 — Regime gate  (`scripts/daily_factor_picks.py:254-322`)

Runs **before** the factor pipeline so it short-circuits the expensive EDGAR load on
cash days. Binary risk-on / risk-off:

```
trend gate (default ON): if SPY close < its 75-day SMA  -> emit EMPTY picks, skip the rebalance (stay in cash)
optional VIX gate:       if VIX percentile > cutoff      -> empty picks
```

Below the 75-SMA = no trades that cycle. (Backed by the 2026-05-18 asymmetric-filter
backtest: +10.87pp on the 2022-2024 stress window, bit-identical on 2024-2026.)

## Stage 2 — Selection  (`src/factors/pipeline.py:run_factor_picks`, line 194)

If risk-on:

1. **Universe + prices** — PIT S&P 500 (or a frozen snapshot for backtests) (`:261`).
2. **Min-history filter** — drop names with <504 trading days of history before as_of
   (recent IPOs / spin-offs whose fundamentals are unreliable) (`:279`).
3. **Compute factor frames** (`:314-343`), each returning `ticker, raw, rank, z_score`:
   - `momentum_12_1` — Jegadeesh-Titman 12-1 price momentum
   - `quality_factor` — ROE/ROA/margins/FCF/debt, then **sector-neutralized** (ranked
     *within* GICS sector) (`:316-318`)
   - `value_factor` — earnings yield = TTM-EPS / price (TTM roll fixed 2026-05-31)
   - `pead_factor` — earnings-surprise drift, only if `--include-pead` (`:330-343`)
4. **Rank-blend** (`combine_factors`, `:350`) — equal-weight mean of each name's
   normalized rank across the factors; `min_overlap=2` (a name must appear in >=2
   frames to qualify). This mean-normalized-rank is the composite score.
5. **Hysteresis** (`:367-392`) — previously-held names get a rank bonus of
   `0.75 x top_n` (~18 slots on a 24-name book) via an effective-rank used only for
   selection ordering (displayed `rank` unchanged). Reduces churn / cost drag and
   prevents whipsaws. (+4.31pp avg cross-window alpha vs no hysteresis.)
6. **Pre-filters (opt-in)** — `min_z` and/or `require_pead`, applied before the cap
   (`:418-434`).
7. **Sector-cap selection** (`_select_with_sector_cap`, `:82-145`, called `:441`) —
   walk the ranked list, take the **top 24** subject to **<=30% per GICS sector**,
   skipping share-class duplicates (e.g. GOOG/GOOGL — highest-ranked member only).
   Under-fills rather than relaxing the cap; logs evicted names with the reason.
8. **(Long-short, optional)** — bottom names by composite become shorts, same sector
   cap on the short side (`:452+`).

## Stage 3 — Execution  (`scripts/paper_trade_factor_picks.py`)

- Equal-weight the selected picks, diff against current Alpaca paper positions,
  submit **bracket** (default) or **market** orders.
- **Dry-run by default** — prints the plan; `--execute` actually submits.
- Deterministic `client_order_id`s so a same-day re-run is idempotent.

---

## Key mechanics

- **Cross-sectional, not absolute:** selection is by *relative rank* across the
  universe each rebalance — robust across regimes, no hardcoded thresholds.
- **Point-in-time discipline:** every factor reads only data <= as_of (anything later
  is a lookahead bug). EDGAR fundamentals are as-filed (the structural edge).
- **Rebalance cadence:** 63 trading days; held names re-evaluated, hysteresis applied.
- **Risk controls:** 75-SMA trend gate (cash in downtrends), 30% sector cap,
  504-day min-history filter, equal-weight sizing.

## Caveats (from the evaluation log)

- Judge results **phase-averaged on CAPM-alpha**, never a single backtest (2yr/63d has
  a +/-20-30pp luck envelope).
- Value leg is regime-dependent (strong in value rotations, weak in growth eras); TTM
  bug fixed 2026-05-31.
- The durable edge is the small PEAD+quality core; the rest is regime-conditional.
