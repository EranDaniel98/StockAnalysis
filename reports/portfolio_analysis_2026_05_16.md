# Portfolio Analysis — 2026-05-16

**Strategy:** `composite_d05_r63` (composite m+q+v, top 5%, quarterly rebalance)
**Portfolio equity:** $41,042.60 | **Positions:** 24 equal-weight (4.2% each)
**Next rebalance:** ~2026-08-12 (63 trading days)

## Portfolio-level expectations

- Average position target return: **+8.0%** over 63 trading days
- Average position stop: -7.0% (reward/risk ratio: 1.41×)
- Portfolio target equity at exit: $44,326.05 (P&L $3,283.41)

**Honest caveats:**
- The +8% per-pick median is the strategy's BACKTESTED 63-day median across two 2-year windows. Real-world drift is real.
- Equal-weight allocation reduces single-name blow-up risk but trails a market-cap SPY in megacap-led regimes.
- Backtest avg cross-window alpha is +2.77%/yr vs SPY — not the 5-8% headline you might want, but defensible and walk-forward-clean.

## Sector breakdown

| Sector | Count | % of portfolio |
|---|---|---|
| Financial Services | 10 | 41.7% ⚠️ |
| Healthcare | 3 | 12.5% |
| Basic Materials | 3 | 12.5% |
| Energy | 2 | 8.3% |
| Communication Services | 2 | 8.3% |
| Technology | 1 | 4.2% |
| Consumer Defensive | 1 | 4.2% |
| Real Estate | 1 | 4.2% |
| Utilities | 1 | 4.2% |

⚠️ **Sector concentration warning.** One sector exceeds 30% of the portfolio — single-sector drawdowns will hit harder than the broad market.

## Portfolio-wide risk summary

- Earnings within 14 days: DELL(12d)
- >30% above 200d SMA (overbought): APA, VTRS, GOOG, GOOGL, DELL, CF, DOW

---

## Per-stock analysis

Each pick below has: factor breakdown that earned it the spot, technical setup, fundamentals from the latest EDGAR filing, a specific trading plan with entry/stop/target, and risk flags. Stops are sized off 20-day ATR (2.5×) so they breathe with the stock's normal volatility instead of tripping on noise.

### #1. **APA** — Energy

_APA sits at composite z=+2.90. Top by strong momentum (rank #24, +123% past year) + cheap valuation (rank #14, earnings yield 11.4%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$38.96** | Composite z: **+2.90** | Analyst tgt: $41.92 (+7.62%) — *hold* | β=0.37

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 24 | — |
| Quality | — | ROE 6.9%; D/E 0.02 |
| Value | 14 | earnings yield 11.45% |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $27.52 (+41.56%)
- **50-day SMA:** $38.16 (+2.09%)
- **20-day ATR:** $1.52 (3.9% of price) — stop sized off this
- **52-week range:** $15.50 – $45.36 (currently -14.11% from high, +151.25% from low)
- **Returns:** 1M +3.47% | 3M +40.46% | 12M +123.32%
- **Liquidity:** $251.38M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-07 (edgar_10q)
- EPS growth +31.3% YoY | ROE 6.9% | D/E 0.02 | Current 0.92

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $38.96 | Market at next open. Position: 43 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $35.15 | -9.8% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $42.07 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 0.82× | risk $3.81/sh, reward $3.11/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $42.07
- Bull case (75th pct): +17.6% → ~$45.81
- Bear case (25th pct): -1.5% → ~$38.36

**Risk flags**
- ⚠️ Extended >30% above 200d SMA — pullback risk

---

### #2. **VTRS** — Healthcare

_VTRS sits at composite z=+2.38. Top by strong momentum (rank #41, +105% past year). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$16.49** | Composite z: **+2.38** | Analyst tgt: $17.50 (+6.16%) — *buy* | β=0.87

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 41 | — |
| Quality | — | OpMargin -2.3%; D/E 0.85 |
| Value | 78 | earnings yield -15.23%; revenue TTM $3.52B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $12.14 (+35.82%)
- **50-day SMA:** $14.47 (+13.93%)
- **20-day ATR:** $0.56 (3.4% of price) — stop sized off this
- **52-week range:** $7.90 – $17.53 (currently -5.96% from high, +108.63% from low)
- **Returns:** 1M +17.67% | 3M +5.43% | 12M +104.91%
- **Liquidity:** $214.83M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-07 (edgar_10q)
- Revenue $3.52B (+8.1% YoY) | OpMargin -2.3% | D/E 0.85 | Current 1.60

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $16.49 | Market at next open. Position: 103 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $15.08 | -8.5% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $17.80 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 0.94× | risk $1.40/sh, reward $1.31/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $17.80
- Bull case (75th pct): +17.6% → ~$19.39
- Bear case (25th pct): -1.5% → ~$16.24

**Risk flags**
- ⚠️ Extended >30% above 200d SMA — pullback risk

---

### #3. **GOOG** — Communication Services

_GOOG sits at composite z=+2.24. Top by strong momentum (rank #27, +137% past year) + high quality (rank #44, op-margin 36%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$393.24** | Composite z: **+2.24** | Analyst tgt: $418.47 (+6.42%) — *strong_buy* | β=1.27

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 27 | — |
| Quality | 44 | ROE 13.1%; OpMargin 36.1%; D/E 0.16 |
| Value | 135 | earnings yield 3.33%; revenue TTM $109.90B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $291.01 (+35.13%)
- **50-day SMA:** $330.78 (+18.88%)
- **20-day ATR:** $9.77 (2.5% of price) — stop sized off this
- **52-week range:** $162.96 – $399.93 (currently -1.67% from high, +141.31% from low)
- **Returns:** 1M +18.17% | 3M +28.59% | 12M +136.56%
- **Liquidity:** $6.80B avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-04-30 (edgar_10q)
- Revenue $109.90B (+21.8% YoY) | EPS growth +81.9% YoY | ROE 13.1% | OpMargin 36.1% | NetMargin 56.9% | D/E 0.16 | Current 1.92

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $393.24 | Market at next open. Position: 4 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $368.82 | -6.2% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $424.70 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.29× | risk $24.42/sh, reward $31.46/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $424.70
- Bull case (75th pct): +17.6% → ~$462.38
- Bear case (25th pct): -1.5% → ~$387.20

**Risk flags**
- ⚠️ Extended >30% above 200d SMA — pullback risk

---

### #4. **GOOGL** — Communication Services

_GOOGL sits at composite z=+2.24. Top by strong momentum (rank #25, +141% past year) + high quality (rank #44, op-margin 36%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$396.64** | Composite z: **+2.24** | Analyst tgt: $427.89 (+7.88%) — *strong_buy* | β=1.27

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 25 | — |
| Quality | 44 | ROE 13.1%; OpMargin 36.1%; D/E 0.16 |
| Value | 138 | earnings yield 3.30%; revenue TTM $109.90B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $291.06 (+36.28%)
- **50-day SMA:** $332.73 (+19.21%)
- **20-day ATR:** $10.09 (2.5% of price) — stop sized off this
- **52-week range:** $161.64 – $403.70 (currently -1.75% from high, +145.39% from low)
- **Returns:** 1M +18.04% | 3M +29.83% | 12M +140.68%
- **Liquidity:** $10.29B avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-04-30 (edgar_10q)
- Revenue $109.90B (+21.8% YoY) | EPS growth +81.9% YoY | ROE 13.1% | OpMargin 36.1% | NetMargin 56.9% | D/E 0.16 | Current 1.92

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $396.64 | Market at next open. Position: 4 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $371.43 | -6.4% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $428.38 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.26× | risk $25.21/sh, reward $31.74/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $428.38
- Bull case (75th pct): +17.6% → ~$466.37
- Bear case (25th pct): -1.5% → ~$390.54

**Risk flags**
- ⚠️ Extended >30% above 200d SMA — pullback risk

---

### #5. **DELL** — Technology

_DELL sits at composite z=+2.21. Top by strong momentum (rank #38, +122% past year). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$242.80** | Composite z: **+2.21** | Analyst tgt: $197.04 (-18.85%) — *buy* | β=1.06

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 38 | — |
| Quality | 93 | ROE -240.3%; OpMargin 7.2%; D/E -12.75 |
| Value | 77 | earnings yield 2.85%; revenue TTM $113.54B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $146.32 (+65.93%)
- **50-day SMA:** $190.19 (+27.66%)
- **20-day ATR:** $12.49 (5.1% of price) — stop sized off this
- **52-week range:** $104.79 – $263.99 (currently -8.03% from high, +131.71% from low)
- **Returns:** 1M +26.13% | 3M +107.30% | 12M +122.02%
- **Liquidity:** $1.38B avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-03-16 (edgar_10k)
- Revenue $113.54B (+374.4% YoY) | EPS growth +303.7% YoY | ROE -240.3% | OpMargin 7.2% | NetMargin 5.2% | D/E -12.75 | Current 0.91

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $242.80 | Market at next open. Position: 7 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $211.58 | -12.9% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $262.22 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 0.62× | risk $31.22/sh, reward $19.42/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $262.22
- Bull case (75th pct): +17.6% → ~$285.49
- Bear case (25th pct): -1.5% → ~$239.07

**Risk flags**
- Earnings in 12 days (outside blackout but worth tracking)
- ⚠️ Extended >30% above 200d SMA — pullback risk

---

### #6. **CF** — Basic Materials

_CF sits at composite z=+2.16. Top by high quality (rank #51, op-margin 43%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$125.04** | Composite z: **+2.16** | Analyst tgt: $122.58 (-1.97%) — *hold* | β=0.42

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 76 | — |
| Quality | 51 | ROE 12.7%; OpMargin 43.5%; D/E 0.60 |
| Value | 97 | earnings yield 8.31%; revenue TTM $1.99B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $95.26 (+31.26%)
- **50-day SMA:** $124.14 (+0.72%)
- **20-day ATR:** $5.35 (4.3% of price) — stop sized off this
- **52-week range:** $75.02 – $141.96 (currently -11.92% from high, +66.68% from low)
- **Returns:** 1M +0.26% | 3M +32.09% | 12M +48.83%
- **Liquidity:** $379.10M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-07 (edgar_10q)
- Revenue $1.99B (+19.4% YoY) | EPS growth +115.1% YoY | ROE 12.7% | OpMargin 43.5% | NetMargin 34.0% | D/E 0.60 | Current 3.54

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $125.04 | Market at next open. Position: 13 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $111.67 | -10.7% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $135.04 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 0.75× | risk $13.37/sh, reward $10.00/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $135.04
- Bull case (75th pct): +17.6% → ~$147.02
- Bear case (25th pct): -1.5% → ~$123.12

**Risk flags**
- ⚠️ Extended >30% above 200d SMA — pullback risk

---

### #7. **NEM** — Basic Materials

_NEM sits at composite z=+2.16. Top by strong momentum (rank #18, +127% past year). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$108.85** | Composite z: **+2.16** | Analyst tgt: $144.01 (+32.30%) — *buy* | β=0.45

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 18 | — |
| Quality | 101 | ROE 9.3%; D/E 0.15 |
| Value | 100 | earnings yield 7.53%; revenue TTM $7.31B |

**Technical setup**
- **Trend:** long-term up, short-term pullback (above 200d, below 50d)
- **200-day SMA:** $98.09 (+10.97%)
- **50-day SMA:** $111.74 (-2.58%)
- **20-day ATR:** $4.83 (4.4% of price) — stop sized off this
- **52-week range:** $47.78 – $134.61 (currently -19.14% from high, +127.82% from low)
- **Returns:** 1M -4.02% | 3M -13.30% | 12M +126.60%
- **Liquidity:** $805.94M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-04-23 (edgar_10q)
- Revenue $7.31B (+45.8% YoY) | EPS growth +78.6% YoY | ROE 9.3% | NetMargin 44.6% | D/E 0.15 | Current 2.44

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $108.85 | Market at next open. Position: 15 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $96.79 | -11.1% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $117.56 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 0.72× | risk $12.06/sh, reward $8.71/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $117.56
- Bull case (75th pct): +17.6% → ~$127.99
- Bear case (25th pct): -1.5% → ~$107.18

---

### #8. **DOW** — Basic Materials

_DOW sits at composite z=+2.13. Picked on cross-factor consistency rather than any single factor extreme. Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$38.76** | Composite z: **+2.13** | Analyst tgt: $43.06 (+11.11%) — *buy* | β=0.45

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 95 | — |
| Quality | — | ROE -3.5% |
| Value | 64 | earnings yield -5.88%; revenue TTM $9.79B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $27.94 (+38.72%)
- **50-day SMA:** $38.45 (+0.78%)
- **20-day ATR:** $1.62 (4.2% of price) — stop sized off this
- **52-week range:** $19.59 – $42.74 (currently -9.32% from high, +97.88% from low)
- **Returns:** 1M -2.92% | 3M +20.70% | 12M +37.15%
- **Liquidity:** $451.30M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-04-24 (edgar_10q)
- Revenue $9.79B (-6.1% YoY) | EPS growth -68.2% YoY | ROE -3.5% | NetMargin -5.4% | Current 1.85

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $38.76 | Market at next open. Position: 44 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $34.71 | -10.4% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $41.86 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 0.77× | risk $4.05/sh, reward $3.10/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $41.86
- Bull case (75th pct): +17.6% → ~$45.57
- Bear case (25th pct): -1.5% → ~$38.16

**Risk flags**
- ⚠️ Extended >30% above 200d SMA — pullback risk

---

### #9. **RF** — Financial Services

_RF sits at composite z=+2.09. Top by cheap valuation (rank #23, earnings yield 8.7%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$26.64** | Composite z: **+2.09** | Analyst tgt: $30.69 (+15.20%) — *hold* | β=1.03

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 143 | — |
| Quality | — | ROE 3.0%; D/E 0.17 |
| Value | 23 | earnings yield 8.75% |

**Technical setup**
- **Trend:** long-term up, short-term pullback (above 200d, below 50d)
- **200-day SMA:** $26.45 (+0.72%)
- **50-day SMA:** $26.95 (-1.14%)
- **20-day ATR:** $0.62 (2.3% of price) — stop sized off this
- **52-week range:** $19.96 – $31.23 (currently -14.70% from high, +33.44% from low)
- **Returns:** 1M -4.58% | 3M -9.56% | 12M +23.75%
- **Liquidity:** $261.08M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-07 (edgar_10q)
- EPS growth +21.6% YoY | ROE 3.0% | D/E 0.17

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $26.64 | Market at next open. Position: 64 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $25.10 | -5.8% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $28.77 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.38× | risk $1.54/sh, reward $2.13/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $28.77
- Bull case (75th pct): +17.6% → ~$31.32
- Bear case (25th pct): -1.5% → ~$26.23

---

### #10. **SYF** — Financial Services

_SYF sits at composite z=+2.02. Top by cheap valuation (rank #10, earnings yield 13.4%). Price is BELOW the 200-day SMA — countertrend pick, respect the stop._

**Snapshot**
Price: **$71.22** | Composite z: **+2.02** | Analyst tgt: $89.59 (+25.79%) — *buy* | β=1.36

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 167 | — |
| Quality | — | ROE 4.9%; D/E 1.00 |
| Value | 10 | earnings yield 13.37% |

**Technical setup**
- **Trend:** potential trend change (above 50d but below 200d)
- **200-day SMA:** $73.64 (-3.29%)
- **50-day SMA:** $70.73 (+0.70%)
- **20-day ATR:** $1.86 (2.6% of price) — stop sized off this
- **52-week range:** $54.76 – $88.05 (currently -19.11% from high, +30.08% from low)
- **Returns:** 1M -4.86% | 3M +0.19% | 12M +18.52%
- **Liquidity:** $301.91M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-04-23 (edgar_10q)
- EPS growth +20.1% YoY | ROE 4.9% | D/E 1.00

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $71.22 | Market at next open. Position: 24 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $66.58 | -6.5% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $76.92 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.23× | risk $4.64/sh, reward $5.70/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $76.92
- Bull case (75th pct): +17.6% → ~$83.74
- Bear case (25th pct): -1.5% → ~$70.13

---

### #11. **GS** — Financial Services

_GS sits at composite z=+2.01. Picked on cross-factor consistency rather than any single factor extreme. Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$949.92** | Composite z: **+2.01** | Analyst tgt: $947.60 (-0.24%) — *hold* | β=1.27

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 69 | — |
| Quality | — | ROE 4.6% |
| Value | 108 | earnings yield 5.77% |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $837.13 (+13.47%)
- **50-day SMA:** $881.23 (+7.80%)
- **20-day ATR:** $22.31 (2.3% of price) — stop sized off this
- **52-week range:** $570.68 – $979.54 (currently -3.02% from high, +66.45% from low)
- **Returns:** 1M +5.55% | 3M +5.50% | 12M +58.53%
- **Liquidity:** $1.65B avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-01 (edgar_10q)
- EPS growth +24.3% YoY | ROE 4.6%

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $949.92 | Market at next open. Position: 1 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $894.15 | -5.9% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $1,025.91 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.36× | risk $55.77/sh, reward $75.99/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $1,025.91
- Bull case (75th pct): +17.6% → ~$1,116.93
- Bear case (25th pct): -1.5% → ~$935.32

---

### #12. **BK** — Financial Services

_BK sits at composite z=+2.01. Picked on cross-factor consistency rather than any single factor extreme. Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$134.99** | Composite z: **+2.01** | Analyst tgt: $142.64 (+5.67%) — *buy* | β=1.07

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 62 | — |
| Quality | — | ROE 3.6%; D/E 0.73 |
| Value | 116 | earnings yield 5.65% |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $114.39 (+18.01%)
- **50-day SMA:** $125.75 (+7.35%)
- **20-day ATR:** $2.73 (2.0% of price) — stop sized off this
- **52-week range:** $85.80 – $138.60 (currently -2.60% from high, +57.34% from low)
- **Returns:** 1M +0.51% | 3M +15.11% | 12M +56.39%
- **Liquidity:** $474.08M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-01 (edgar_10q)
- EPS growth +41.8% YoY | ROE 3.6% | D/E 0.73

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $134.99 | Market at next open. Position: 12 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $128.17 | -5.0% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $145.79 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.58× | risk $6.82/sh, reward $10.80/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $145.79
- Bull case (75th pct): +17.6% → ~$158.72
- Bear case (25th pct): -1.5% → ~$132.92

---

### #13. **OXY** — Energy

_OXY sits at composite z=+1.89. Picked on cross-factor consistency rather than any single factor extreme. Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$59.60** | Composite z: **+1.89** | Analyst tgt: $64.33 (+7.93%) — *hold* | β=0.17

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 125 | — |
| Quality | 80 | ROE 8.6%; D/E 0.38 |
| Value | 80 | earnings yield 8.07%; revenue TTM $5.23B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $47.45 (+25.62%)
- **50-day SMA:** $58.47 (+1.94%)
- **20-day ATR:** $1.78 (3.0% of price) — stop sized off this
- **52-week range:** $38.62 – $67.45 (currently -11.63% from high, +54.35% from low)
- **Returns:** 1M +4.81% | 3M +29.99% | 12M +38.97%
- **Liquidity:** $685.69M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-05 (edgar_10q)
- Revenue $5.23B (-23.1% YoY) | EPS growth +306.5% YoY | ROE 8.6% | NetMargin 64.2% | D/E 0.38 | Current 1.21

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $59.60 | Market at next open. Position: 28 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $55.15 | -7.5% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $64.37 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.07× | risk $4.46/sh, reward $4.77/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $64.37
- Bull case (75th pct): +17.6% → ~$70.08
- Bear case (25th pct): -1.5% → ~$58.68

---

### #14. **MS** — Financial Services

_MS sits at composite z=+1.89. Picked on cross-factor consistency rather than any single factor extreme. Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$192.50** | Composite z: **+1.89** | Analyst tgt: $203.29 (+5.60%) — *buy* | β=1.21

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 84 | — |
| Quality | — | ROE 4.9%; D/E 3.18 |
| Value | 113 | earnings yield 5.69% |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $166.53 (+15.60%)
- **50-day SMA:** $175.89 (+9.44%)
- **20-day ATR:** $4.12 (2.1% of price) — stop sized off this
- **52-week range:** $120.96 – $197.50 (currently -2.53% from high, +59.14% from low)
- **Returns:** 1M +3.32% | 3M +13.08% | 12M +50.45%
- **Liquidity:** $929.67M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-05 (edgar_10q)
- EPS growth +31.9% YoY | ROE 4.9% | D/E 3.18

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $192.50 | Market at next open. Position: 8 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $182.19 | -5.3% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $207.90 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.49× | risk $10.31/sh, reward $15.40/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $207.90
- Bull case (75th pct): +17.6% → ~$226.34
- Bear case (25th pct): -1.5% → ~$189.54

---

### #15. **USB** — Financial Services

_USB sits at composite z=+1.87. Picked on cross-factor consistency rather than any single factor extreme. Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$53.13** | Composite z: **+1.87** | Analyst tgt: $63.48 (+19.46%) — *buy* | β=1.02

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 137 | — |
| Quality | — | ROE 3.0% |
| Value | 63 | earnings yield 8.54%; revenue TTM $7.29B |

**Technical setup**
- **Trend:** long-term up, short-term pullback (above 200d, below 50d)
- **200-day SMA:** $50.82 (+4.55%)
- **50-day SMA:** $53.83 (-1.28%)
- **20-day ATR:** $1.13 (2.1% of price) — stop sized off this
- **52-week range:** $40.49 – $60.56 (currently -12.27% from high, +31.22% from low)
- **Returns:** 1M -4.23% | 3M -6.94% | 12M +25.23%
- **Liquidity:** $470.34M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-04 (edgar_10q)
- Revenue $7.29B (+4.7% YoY) | EPS growth +14.6% YoY | ROE 3.0% | NetMargin 26.7%

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $53.13 | Market at next open. Position: 32 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $50.32 | -5.3% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $57.39 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.51× | risk $2.82/sh, reward $4.26/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $57.39
- Bull case (75th pct): +17.6% → ~$62.47
- Bear case (25th pct): -1.5% → ~$52.31

---

### #16. **TFC** — Financial Services

_TFC sits at composite z=+1.87. Top by cheap valuation (rank #32, earnings yield 8.3%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$46.91** | Composite z: **+1.87** | Analyst tgt: $55.68 (+18.69%) — *buy* | β=0.91

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 169 | — |
| Quality | — | ROE 2.3%; D/E 0.65 |
| Value | 32 | earnings yield 8.31% |

**Technical setup**
- **Trend:** long-term up, short-term pullback (above 200d, below 50d)
- **200-day SMA:** $46.42 (+1.06%)
- **50-day SMA:** $47.44 (-1.11%)
- **20-day ATR:** $1.05 (2.2% of price) — stop sized off this
- **52-week range:** $36.61 – $55.06 (currently -14.79% from high, +28.14% from low)
- **Returns:** 1M -4.09% | 3M -8.65% | 12M +18.94%
- **Liquidity:** $349.17M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-01 (edgar_10q)
- EPS growth +25.3% YoY | ROE 2.3% | D/E 0.65

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $46.91 | Market at next open. Position: 36 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $44.30 | -5.6% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $50.67 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.43× | risk $2.62/sh, reward $3.76/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $50.67
- Bull case (75th pct): +17.6% → ~$55.16
- Bear case (25th pct): -1.5% → ~$46.19

---

### #17. **MO** — Consumer Defensive

_MO sits at composite z=+1.81. Top by high quality (rank #12, op-margin 54%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$73.01** | Composite z: **+1.81** | Analyst tgt: $69.45 (-4.87%) — *hold* | β=0.52

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 173 | — |
| Quality | 12 | ROE -68.0%; OpMargin 54.5%; D/E -7.66 |
| Value | 128 | earnings yield 6.51%; revenue TTM $5.43B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $62.34 (+17.12%)
- **50-day SMA:** $67.05 (+8.89%)
- **20-day ATR:** $1.67 (2.3% of price) — stop sized off this
- **52-week range:** $52.91 – $74.56 (currently -2.08% from high, +37.99% from low)
- **Returns:** 1M +12.43% | 3M +10.38% | 12M +38.73%
- **Liquidity:** $680.81M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-04-30 (edgar_10q)
- Revenue $5.43B (+3.2% YoY) | EPS growth +106.3% YoY | ROE -68.0% | OpMargin 54.5% | NetMargin 40.2% | D/E -7.66 | Current 0.62

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $73.01 | Market at next open. Position: 23 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $68.84 | -5.7% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $78.85 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.40× | risk $4.17/sh, reward $5.84/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $78.85
- Bull case (75th pct): +17.6% → ~$85.85
- Bear case (25th pct): -1.5% → ~$71.89

---

### #18. **MTB** — Financial Services

_MTB sits at composite z=+1.78. Top by high quality (rank #17). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$205.31** | Composite z: **+1.78** | Analyst tgt: $233.53 (+13.74%) — *hold* | β=0.59

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 193 | — |
| Quality | 17 | ROE 2.4%; D/E 0.40 |
| Value | 109 | earnings yield 8.04%; revenue TTM $418.00M |

**Technical setup**
- **Trend:** long-term up, short-term pullback (above 200d, below 50d)
- **200-day SMA:** $201.44 (+1.92%)
- **50-day SMA:** $210.30 (-2.37%)
- **20-day ATR:** $4.25 (2.1% of price) — stop sized off this
- **52-week range:** $171.92 – $237.35 (currently -13.50% from high, +19.42% from low)
- **Returns:** 1M -5.37% | 3M -9.61% | 12M +14.08%
- **Liquidity:** $195.42M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-05 (edgar_10q)
- Revenue $418.00M (+5.3% YoY) | EPS growth +24.4% YoY | ROE 2.4% | NetMargin 158.9% | D/E 0.40

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $205.31 | Market at next open. Position: 8 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $194.69 | -5.2% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $221.73 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.55× | risk $10.62/sh, reward $16.42/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $221.73
- Bull case (75th pct): +17.6% → ~$241.41
- Bear case (25th pct): -1.5% → ~$202.15

---

### #19. **HCA** — Healthcare

_HCA sits at composite z=+1.77. Top by high quality (rank #50). Price is BELOW the 200-day SMA — countertrend pick, respect the stop._

**Snapshot**
Price: **$422.96** | Composite z: **+1.77** | Analyst tgt: $513.10 (+21.31%) — *buy* | β=1.19

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 127 | — |
| Quality | 50 | ROE -25.7%; D/E -7.04 |
| Value | 140 | earnings yield 6.48%; revenue TTM $19.11B |

**Technical setup**
- **Trend:** downtrend (below 50d + 200d)
- **200-day SMA:** $460.30 (-8.11%)
- **50-day SMA:** $475.61 (-11.07%)
- **20-day ATR:** $13.01 (3.1% of price) — stop sized off this
- **52-week range:** $328.43 – $555.69 (currently -23.89% from high, +28.78% from low)
- **Returns:** 1M -12.43% | 3M -21.60% | 12M +15.87%
- **Liquidity:** $566.84M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-04-29 (edgar_10q)
- Revenue $19.11B (+4.3% YoY) | EPS growth +10.9% YoY | ROE -25.7% | NetMargin 8.5% | D/E -7.04 | Current 0.83

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $422.96 | Market at next open. Position: 4 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $390.44 | -7.7% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $456.80 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.04× | risk $32.52/sh, reward $33.84/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $456.80
- Bull case (75th pct): +17.6% → ~$497.32
- Bear case (25th pct): -1.5% → ~$416.46

---

### #20. **HST** — Real Estate

_HST sits at composite z=+1.73. Picked on cross-factor consistency rather than any single factor extreme. Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$21.39** | Composite z: **+1.73** | Analyst tgt: $22.88 (+6.97%) — *buy* | β=1.12

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 98 | — |
| Quality | 127 | ROE 7.2%; OpMargin 19.4% |
| Value | 93 | earnings yield 7.58%; revenue TTM $1.65B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $17.91 (+19.42%)
- **50-day SMA:** $20.10 (+6.40%)
- **20-day ATR:** $0.44 (2.1% of price) — stop sized off this
- **52-week range:** $13.70 – $22.39 (currently -4.49% from high, +56.13% from low)
- **Returns:** 1M +3.96% | 3M +8.66% | 12M +45.66%
- **Liquidity:** $153.77M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-08 (edgar_10q)
- Revenue $1.65B (+3.2% YoY) | EPS growth +105.7% YoY | ROE 7.2% | OpMargin 19.4% | NetMargin 30.0%

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $21.39 | Market at next open. Position: 79 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $20.28 | -5.2% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $23.10 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.55× | risk $1.11/sh, reward $1.71/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $23.10
- Bull case (75th pct): +17.6% → ~$25.15
- Bear case (25th pct): -1.5% → ~$21.06

---

### #21. **AES** — Utilities

_AES sits at composite z=+1.71. Top by cheap valuation (rank #29, earnings yield 10.3%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$14.46** | Composite z: **+1.71** | Analyst tgt: $15.11 (+4.50%) — *hold* | β=0.96

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 197 | — |
| Quality | — | ROE 11.0% |
| Value | 29 | earnings yield 10.30%; revenue TTM $3.18B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $13.85 (+4.40%)
- **50-day SMA:** $14.17 (+2.04%)
- **20-day ATR:** $0.07 (0.5% of price) — stop sized off this
- **52-week range:** $9.00 – $17.44 (currently -17.06% from high, +60.71% from low)
- **Returns:** 1M +0.95% | 3M -10.08% | 12M +21.43%
- **Liquidity:** $172.78M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-05 (edgar_10q)
- Revenue $3.18B (+8.7% YoY) | EPS growth +871.4% YoY | ROE 11.0% | NetMargin 15.3% | Current 0.73

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $14.46 | Market at next open. Position: 118 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $14.28 | -1.3% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $15.62 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 6.34× | risk $0.18/sh, reward $1.16/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $15.62
- Bull case (75th pct): +17.6% → ~$17.00
- Bear case (25th pct): -1.5% → ~$14.24

---

### #22. **INCY** — Healthcare

_INCY sits at composite z=+1.70. Picked on cross-factor consistency rather than any single factor extreme. Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$95.30** | Composite z: **+1.70** | Analyst tgt: $108.50 (+13.85%) — *buy* | β=0.80

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 61 | — |
| Quality | 116 | ROE 5.4%; OpMargin 23.7% |
| Value | 149 | earnings yield 6.74%; revenue TTM $1.27B |

**Technical setup**
- **Trend:** long-term up, short-term pullback (above 200d, below 50d)
- **200-day SMA:** $94.85 (+0.47%)
- **50-day SMA:** $95.39 (-0.10%)
- **20-day ATR:** $2.99 (3.1% of price) — stop sized off this
- **52-week range:** $61.11 – $112.29 (currently -15.13% from high, +55.95% from low)
- **Returns:** 1M -0.02% | 3M -5.74% | 12M +55.82%
- **Liquidity:** $139.46M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-04-28 (edgar_10q)
- Revenue $1.27B (+20.9% YoY) | EPS growth +83.7% YoY | ROE 5.4% | OpMargin 23.7% | NetMargin 23.8% | Current 3.68

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $95.30 | Market at next open. Position: 17 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $87.83 | -7.8% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $102.92 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.02× | risk $7.48/sh, reward $7.62/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $102.92
- Bull case (75th pct): +17.6% → ~$112.05
- Bear case (25th pct): -1.5% → ~$93.84

---

### #23. **C** — Financial Services

_C sits at composite z=+1.69. Top by strong momentum (rank #40, +68% past year) + cheap valuation (rank #22, earnings yield 5.9%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$123.34** | Composite z: **+1.69** | Analyst tgt: $146.84 (+19.05%) — *buy* | β=1.12

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 40 | — |
| Quality | 250 | ROE 6.7%; D/E 1.49 |
| Value | 22 | earnings yield 5.91%; revenue TTM $85.22B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $107.96 (+14.25%)
- **50-day SMA:** $119.65 (+3.08%)
- **20-day ATR:** $3.08 (2.5% of price) — stop sized off this
- **52-week range:** $70.06 – $134.65 (currently -8.40% from high, +76.05% from low)
- **Returns:** 1M -4.19% | 3M +11.78% | 12M +67.53%
- **Liquidity:** $1.37B avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-02-20 (edgar_10k)
- Revenue $85.22B (+5.0% YoY) | EPS growth +17.7% YoY | ROE 6.7% | NetMargin 16.8% | D/E 1.49

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $123.34 | Market at next open. Position: 13 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $115.64 | -6.2% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $133.21 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.28× | risk $7.70/sh, reward $9.87/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $133.21
- Bull case (75th pct): +17.6% → ~$145.02
- Bear case (25th pct): -1.5% → ~$121.44

---

### #24. **STT** — Financial Services

_STT sits at composite z=+1.64. Picked on cross-factor consistency rather than any single factor extreme. Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$152.88** | Composite z: **+1.64** | Analyst tgt: $160.54 (+5.01%) — *buy* | β=1.46

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 72 | — |
| Quality | — | ROE 2.8% |
| Value | 164 | earnings yield 6.20%; revenue TTM $3.80B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $123.65 (+23.64%)
- **50-day SMA:** $137.46 (+11.22%)
- **20-day ATR:** $3.34 (2.2% of price) — stop sized off this
- **52-week range:** $91.62 – $156.18 (currently -2.11% from high, +66.86% from low)
- **Returns:** 1M +7.74% | 3M +20.26% | 12M +60.85%
- **Liquidity:** $310.19M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-04-29 (edgar_10q)
- Revenue $3.80B (+15.6% YoY) | EPS growth +22.1% YoY | ROE 2.8% | NetMargin 20.1%

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $152.88 | Market at next open. Position: 11 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $144.54 | -5.5% from entry — 2.5×ATR below or fixed 8%, whichever is bigger |
| **PROFIT TARGET** | $165.11 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.47× | risk $8.34/sh, reward $12.23/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $165.11
- Bull case (75th pct): +17.6% → ~$179.76
- Bear case (25th pct): -1.5% → ~$150.53

---
