# Strategy Roadmap — "earn a lot, durably" (started 2026-06-01)

## Why this exists / the diagnosis
Three independent discovery loops (tri-model panel, factor_lab permutation nulls, WF-gated phase-envelope) confirmed the **existing-data factor space is tapped**: every factor tested on daily-price + standard-EDGAR mega-cap US equities (momentum, value, quality, PEAD, accruals, net-share-issuance) is a published, crowded premium. Even a *positively-screening* new factor (NSI) added **no** incremental composite value — it's redundant with the premia already in the book. The constraint is the **dataset/universe/asset-class**, not the factor list.

**Mandate (Eran, 2026-06-01):** all markets in scope (equities L/S, options, crypto, futures/FX); budget scales with validated expected value; optimize the risk-adjusted edge, not a fixed account size.

## Operating principle
Every track gets a **pre-registered ship rule + kill criterion**, validated with the existing honest harness (phase-averaged, walk-forward-gated, permutation-nulled, delisting/lookahead-audited) on the cheapest available data BEFORE any production-data spend. Spend follows proof. The same discipline that NULL'd the equity factors applies — small-cap/crypto/options have nastier data traps (survivorship, delisting, exchange blow-ups, funding look-ahead, vol-tail) and will be NULL'd if they're noise.

## Tracks (ranked: durability × accessibility × room-for-a-solo)

### Track 1 — Small/micro-cap factor transfer  ·  STATUS: scouting
- **Thesis:** the live m+q+v+PEAD composite, run on a PIT small-cap universe, delivers 2–4× the α because institutions can't fit there.
- **Data:** ~$0 to start — reuse Polygon + EDGAR; build a PIT small-cap universe (approx via EDGAR-shares × price market-cap bands, since we now extract shares).
- **Validate:** existing snapshot → phase-envelope/WF harness on a small-cap snapshot, **net of realistic small-cap costs** (wide spreads, borrow, capacity).
- **Ship if:** cross-window CAPM-α WF-positive AND survives small-cap transaction-cost model. **Kill if:** α evaporates under realistic spreads/borrow.

### Track 2 — Crypto carry + trend  ·  STATUS: scouting
- **Thesis:** perp funding-rate harvest (long spot / short perp = collect funding) + TSMOM on liquid majors/alts. Funding carry is a large, persistent premium.
- **Data:** ~$0 — exchange public APIs (Binance/Bybit funding + OHLCV); Polygon also has crypto spot.
- **Validate:** funding-carry backtest net of fees + a basis-blowup / exchange-haircut stress; trend overlay.
- **Ship if:** carry Sharpe survives fees/slippage + stress. **Kill if:** edge is just unpriced exchange/counterparty risk.

### Track 3 — Volatility risk premium (options)  ·  STATUS: queued (fund after 1–2 validate)
- **Thesis:** sell index/earnings vol (implied > realized), tail-hedged; dispersion (short index vol / long single-name vol).
- **Data:** ~$30–200/mo Polygon options → ORATS for full surface.
- **Validate:** VRP backtest net of costs with an explicit stressed-vol drawdown bound (2018/2020/2022). **Kill if:** the tail eats the premium.

### Track 4 — Managed futures (trend + carry)  ·  STATUS: queued
- **Thesis:** TSMOM + carry across a diversified futures/FX basket; crisis-alpha that diversifies the equity book.
- **Data:** futures feed (~$). **Validate:** classic TSMOM/carry backtest, correlation-to-equity check.

### Track 5 — Alt-data equity signals  ·  STATUS: backlog
- Options-implied skew/term-structure, short-borrow fees, estimate revisions, 8-K/news NLP (panel's #1 axis). Each a sub-bet; cheapest (options-implied, 8-K NLP) first.

## Execution order
Start **Track 1 + Track 2 in parallel** (both ~free, fastest to validate). Fund Track 3 once one of them clears its ship rule. Tracks 4–5 follow.

## Log
- 2026-06-01: roadmap created. NSI factor built + screened positive but incrementally redundant (does not ship). Tracks 1 & 2 scouting.
