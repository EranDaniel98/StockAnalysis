# Portfolio Analysis — 2026-05-17

**Strategy:** `composite_d05_r63` (composite m+q+v, top 5%, quarterly rebalance)
**Portfolio equity:** $41,042.60 | **Positions:** 24 equal-weight (4.2% each)
**Next rebalance:** ~2026-08-12 (63 trading days)

## Portfolio-level expectations

- Average position target return: **+8.0%** over 63 trading days
- Average position stop: -6.8% (reward/risk ratio: 1.26×)
- Portfolio target equity at exit: $44,326.05 (P&L $3,283.41)

**Honest caveats:**
- The +8% per-pick median is the strategy's BACKTESTED 63-day median across two 2-year windows. Real-world drift is real.
- Equal-weight allocation reduces single-name blow-up risk but trails a market-cap SPY in megacap-led regimes.
- Backtest avg cross-window alpha is +2.77%/yr vs SPY — not the 5-8% headline you might want, but defensible and walk-forward-clean.

## Sector breakdown

| Sector | Count | % of portfolio |
|---|---|---|
| Financial Services | 11 | 45.8% ⚠️ |
| Energy | 3 | 12.5% |
| Healthcare | 3 | 12.5% |
| Basic Materials | 2 | 8.3% |
| Utilities | 2 | 8.3% |
| Consumer Defensive | 1 | 4.2% |
| Real Estate | 1 | 4.2% |
| Technology | 1 | 4.2% |

⚠️ **Sector concentration warning.** One sector exceeds 30% of the portfolio — single-sector drawdowns will hit harder than the broad market.

## Correlation structure (60-day daily returns)

- Average pairwise correlation: **0.159**
- Effective independent positions: **~5.2** (out of 24 actual positions)
- Low correlation — good diversification.

**Most correlated pairs** (potential concentration):

- RF ↔ TFC: ρ=+0.92
- MTB ↔ RF: ρ=+0.91
- RF ↔ CFG: ρ=+0.91
- USB ↔ TFC: ρ=+0.90
- MTB ↔ TFC: ρ=+0.89

**Least correlated pairs** (good diversifiers):

- OXY ↔ GS: ρ=-0.57
- CF ↔ GS: ρ=-0.54
- APA ↔ GS: ρ=-0.54
- GS ↔ EOG: ρ=-0.51
- OXY ↔ HST: ρ=-0.51

## Portfolio-wide risk summary

- >30% above 200d SMA (overbought): APA, CF, WDC

---

## Per-stock analysis

Each pick below has: factor breakdown that earned it the spot, technical setup, fundamentals from the latest EDGAR filing, a specific trading plan with entry/stop/target, and risk flags. Stops are sized off 20-day ATR (2.5×) so they breathe with the stock's normal volatility instead of tripping on noise.

### #1. **APA** — Energy

_APA sits at composite z=+2.76. Top by strong momentum (rank #24, +123% past year) + cheap valuation (rank #20, earnings yield 11.4%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$38.98** | Composite z: **+2.76** | Analyst tgt: $41.92 (+7.55%) — *hold* | β=0.37

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 24 | — |
| Quality | — | ROE 6.9%; D/E 0.02 |
| Value | 20 | earnings yield 11.44% |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $27.52 (+41.65%)
- **50-day SMA:** $38.16 (+2.15%)
- **20-day ATR:** $1.52 (3.9% of price) — stop sized off this
- **52-week range:** $15.50 – $45.36 (currently -14.06% from high, +151.41% from low)
- **Returns:** 1M +3.54% | 3M +40.55% | 12M +123.46%
- **Liquidity:** $255.69M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-07 (edgar_10q)
- EPS growth +31.3% YoY | ROE 6.9% | D/E 0.02 | Current 0.92

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $38.98 | Market at next open. Position: 43 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $35.17 | -9.8% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $42.10 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 0.82× | risk $3.81/sh, reward $3.12/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-833,372.80; 1 sales ($833,372.80), most recent 2026-03-31

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $42.10
- Bull case (75th pct): +17.6% → ~$45.83
- Bear case (25th pct): -1.5% → ~$38.38

**Risk flags**
- ⚠️ Extended >30% above 200d SMA — pullback risk

---

### #2. **CF** — Basic Materials

_CF sits at composite z=+2.28. Top by high quality (rank #51, op-margin 43%) + cheap valuation (rank #50, earnings yield 8.3%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$125.24** | Composite z: **+2.28** | Analyst tgt: $122.84 (-1.91%) — *hold* | β=0.42

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 76 | — |
| Quality | 51 | ROE 12.7%; OpMargin 43.5%; D/E 0.60 |
| Value | 50 | earnings yield 8.30%; revenue TTM $1.99B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $94.87 (+32.01%)
- **50-day SMA:** $123.65 (+1.29%)
- **20-day ATR:** $5.35 (4.3% of price) — stop sized off this
- **52-week range:** $74.71 – $141.38 (currently -11.42% from high, +67.62% from low)
- **Returns:** 1M +0.83% | 3M +32.85% | 12M +49.67%
- **Liquidity:** $381.43M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-07 (edgar_10q)
- Revenue $1.99B (+19.4% YoY) | EPS growth +115.1% YoY | ROE 12.7% | OpMargin 43.5% | NetMargin 34.0% | D/E 0.60 | Current 3.54

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $125.24 | Market at next open. Position: 13 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $111.86 | -10.7% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $135.26 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 0.75× | risk $13.38/sh, reward $10.02/sh |

**Insider activity (last 90 days)**
- 🔴 **BEARISH** — net $-72.18M; 36 sales ($72.18M), most recent 2026-04-28

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $135.26
- Bull case (75th pct): +17.6% → ~$147.26
- Bear case (25th pct): -1.5% → ~$123.31

**Risk flags**
- ⚠️ Extended >30% above 200d SMA — pullback risk

---

### #3. **NEM** — Basic Materials

_NEM sits at composite z=+2.20. Top by strong momentum (rank #18, +127% past year). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$109.06** | Composite z: **+2.20** | Analyst tgt: $144.01 (+32.04%) — *buy* | β=0.45

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 18 | — |
| Quality | 101 | ROE 9.3%; D/E 0.15 |
| Value | 70 | earnings yield 7.52%; revenue TTM $7.31B |

**Technical setup**
- **Trend:** long-term up, short-term pullback (above 200d, below 50d)
- **200-day SMA:** $98.09 (+11.19%)
- **50-day SMA:** $111.74 (-2.40%)
- **20-day ATR:** $4.83 (4.4% of price) — stop sized off this
- **52-week range:** $47.78 – $134.61 (currently -18.98% from high, +128.26% from low)
- **Returns:** 1M -3.84% | 3M -13.13% | 12M +127.04%
- **Liquidity:** $830.19M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-04-23 (edgar_10q)
- Revenue $7.31B (+45.8% YoY) | EPS growth +78.6% YoY | ROE 9.3% | NetMargin 44.6% | D/E 0.15 | Current 2.44

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $109.06 | Market at next open. Position: 15 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $97.00 | -11.1% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $117.78 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 0.72× | risk $12.06/sh, reward $8.72/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-7.52M; 12 sales ($7.52M), most recent 2026-05-01

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $117.78
- Bull case (75th pct): +17.6% → ~$128.23
- Bear case (25th pct): -1.5% → ~$107.38

---

### #4. **SYF** — Financial Services

_SYF sits at composite z=+1.98. Top by cheap valuation (rank #7, earnings yield 13.3%). Price is BELOW the 200-day SMA — countertrend pick, respect the stop._

**Snapshot**
Price: **$71.38** | Composite z: **+1.98** | Analyst tgt: $89.59 (+25.51%) — *buy* | β=1.36

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 167 | — |
| Quality | — | ROE 4.9%; D/E 1.00 |
| Value | 7 | earnings yield 13.34% |

**Technical setup**
- **Trend:** potential trend change (above 50d but below 200d)
- **200-day SMA:** $73.65 (-3.08%)
- **50-day SMA:** $70.73 (+0.92%)
- **20-day ATR:** $1.86 (2.6% of price) — stop sized off this
- **52-week range:** $54.76 – $88.05 (currently -18.94% from high, +30.36% from low)
- **Returns:** 1M -4.66% | 3M +0.41% | 12M +18.77%
- **Liquidity:** $305.29M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-04-23 (edgar_10q)
- EPS growth +20.1% YoY | ROE 4.9% | D/E 1.00

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $71.38 | Market at next open. Position: 23 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $66.74 | -6.5% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $77.09 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.23× | risk $4.64/sh, reward $5.71/sh |

**Insider activity (last 90 days)**
- 🔴 **BEARISH** — net $-35.05M; 19 sales ($35.05M), most recent 2026-05-01

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $77.09
- Bull case (75th pct): +17.6% → ~$83.93
- Bear case (25th pct): -1.5% → ~$70.28

---

### #5. **MTB** — Financial Services

_MTB sits at composite z=+1.93. Top by high quality (rank #17) + cheap valuation (rank #57, earnings yield 8.1%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$204.90** | Composite z: **+1.93** | Analyst tgt: $233.53 (+13.97%) — *hold* | β=0.59

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 193 | — |
| Quality | 17 | ROE 2.4%; D/E 0.40 |
| Value | 57 | earnings yield 8.06%; revenue TTM $418.00M |

**Technical setup**
- **Trend:** long-term up, short-term pullback (above 200d, below 50d)
- **200-day SMA:** $201.43 (+1.72%)
- **50-day SMA:** $210.30 (-2.57%)
- **20-day ATR:** $4.25 (2.1% of price) — stop sized off this
- **52-week range:** $171.92 – $237.35 (currently -13.67% from high, +19.18% from low)
- **Returns:** 1M -5.55% | 3M -9.79% | 12M +13.85%
- **Liquidity:** $201.60M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-05 (edgar_10q)
- Revenue $418.00M (+5.3% YoY) | EPS growth +24.4% YoY | ROE 2.4% | NetMargin 158.9% | D/E 0.40

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $204.90 | Market at next open. Position: 8 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $194.28 | -5.2% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $221.29 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.54× | risk $10.62/sh, reward $16.39/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-2.51M; 2 sales ($2.51M), most recent 2026-05-07

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $221.29
- Bull case (75th pct): +17.6% → ~$240.92
- Bear case (25th pct): -1.5% → ~$201.75

---

### #6. **OXY** — Energy

_OXY sits at composite z=+1.92. Top by cheap valuation (rank #56, earnings yield 8.1%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$59.62** | Composite z: **+1.92** | Analyst tgt: $64.33 (+7.91%) — *hold* | β=0.17

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 125 | — |
| Quality | 80 | ROE 8.6%; D/E 0.38 |
| Value | 56 | earnings yield 8.07%; revenue TTM $5.23B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $47.45 (+25.65%)
- **50-day SMA:** $58.47 (+1.97%)
- **20-day ATR:** $1.78 (3.0% of price) — stop sized off this
- **52-week range:** $38.62 – $67.45 (currently -11.61% from high, +54.39% from low)
- **Returns:** 1M +4.84% | 3M +30.03% | 12M +39.00%
- **Liquidity:** $694.81M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-05 (edgar_10q)
- Revenue $5.23B (-23.1% YoY) | EPS growth +306.5% YoY | ROE 8.6% | NetMargin 64.2% | D/E 0.38 | Current 1.21

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $59.62 | Market at next open. Position: 28 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $55.16 | -7.5% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $64.39 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.07× | risk $4.46/sh, reward $4.77/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $64.39
- Bull case (75th pct): +17.6% → ~$70.10
- Bear case (25th pct): -1.5% → ~$58.70

---

### #7. **USB** — Financial Services

_USB sits at composite z=+1.92. Top by cheap valuation (rank #44, earnings yield 8.5%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$53.12** | Composite z: **+1.92** | Analyst tgt: $63.48 (+19.49%) — *buy* | β=1.02

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 137 | — |
| Quality | — | ROE 3.0% |
| Value | 44 | earnings yield 8.55%; revenue TTM $7.29B |

**Technical setup**
- **Trend:** long-term up, short-term pullback (above 200d, below 50d)
- **200-day SMA:** $50.82 (+4.52%)
- **50-day SMA:** $53.83 (-1.31%)
- **20-day ATR:** $1.13 (2.1% of price) — stop sized off this
- **52-week range:** $40.49 – $60.56 (currently -12.29% from high, +31.19% from low)
- **Returns:** 1M -4.25% | 3M -6.97% | 12M +25.19%
- **Liquidity:** $481.17M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-04 (edgar_10q)
- Revenue $7.29B (+4.7% YoY) | EPS growth +14.6% YoY | ROE 3.0% | NetMargin 26.7%

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $53.12 | Market at next open. Position: 32 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $50.30 | -5.3% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $57.37 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.51× | risk $2.82/sh, reward $4.25/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-4.20M; 2 sales ($4.20M), most recent 2026-05-05

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $57.37
- Bull case (75th pct): +17.6% → ~$62.46
- Bear case (25th pct): -1.5% → ~$52.30

---

### #8. **RF** — Financial Services

_RF sits at composite z=+1.90. Top by cheap valuation (rank #41, earnings yield 8.7%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$26.66** | Composite z: **+1.90** | Analyst tgt: $30.69 (+15.12%) — *hold* | β=1.03

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 143 | — |
| Quality | — | ROE 3.0%; D/E 0.17 |
| Value | 41 | earnings yield 8.74% |

**Technical setup**
- **Trend:** long-term up, short-term pullback (above 200d, below 50d)
- **200-day SMA:** $26.45 (+0.79%)
- **50-day SMA:** $26.95 (-1.07%)
- **20-day ATR:** $0.62 (2.3% of price) — stop sized off this
- **52-week range:** $19.96 – $31.23 (currently -14.63% from high, +33.54% from low)
- **Returns:** 1M -4.51% | 3M -9.49% | 12M +23.84%
- **Liquidity:** $264.99M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-07 (edgar_10q)
- EPS growth +21.6% YoY | ROE 3.0% | D/E 0.17

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $26.66 | Market at next open. Position: 64 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $25.12 | -5.8% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $28.79 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.38× | risk $1.54/sh, reward $2.13/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-195,750.22; 1 sales ($195,750.22), most recent 2026-05-07

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $28.79
- Bull case (75th pct): +17.6% → ~$31.35
- Bear case (25th pct): -1.5% → ~$26.25

---

### #9. **STT** — Financial Services

_STT sits at composite z=+1.84. Picked on cross-factor consistency rather than any single factor extreme. Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$152.85** | Composite z: **+1.84** | Analyst tgt: $160.54 (+5.03%) — *buy* | β=1.46

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 72 | — |
| Quality | — | ROE 2.8% |
| Value | 116 | earnings yield 6.20%; revenue TTM $3.80B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $123.65 (+23.62%)
- **50-day SMA:** $137.46 (+11.20%)
- **20-day ATR:** $3.34 (2.2% of price) — stop sized off this
- **52-week range:** $91.62 – $156.18 (currently -2.13% from high, +66.82% from low)
- **Returns:** 1M +7.72% | 3M +20.24% | 12M +60.82%
- **Liquidity:** $314.62M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-04-29 (edgar_10q)
- Revenue $3.80B (+15.6% YoY) | EPS growth +22.1% YoY | ROE 2.8% | NetMargin 20.1%

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $152.85 | Market at next open. Position: 11 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $144.50 | -5.5% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $165.08 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.46× | risk $8.35/sh, reward $12.23/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-9.44M; 1 open-market buys ($312,475.00); 7 sales ($9.75M), most recent 2026-04-22

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $165.08
- Bull case (75th pct): +17.6% → ~$179.72
- Bear case (25th pct): -1.5% → ~$150.50

---

### #10. **INCY** — Healthcare

_INCY sits at composite z=+1.84. Picked on cross-factor consistency rather than any single factor extreme. Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$95.31** | Composite z: **+1.84** | Analyst tgt: $108.50 (+13.84%) — *buy* | β=0.80

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 61 | — |
| Quality | 116 | ROE 5.4%; OpMargin 23.7% |
| Value | 97 | earnings yield 6.74%; revenue TTM $1.27B |

**Technical setup**
- **Trend:** long-term up, short-term pullback (above 200d, below 50d)
- **200-day SMA:** $94.85 (+0.48%)
- **50-day SMA:** $95.39 (-0.09%)
- **20-day ATR:** $2.99 (3.1% of price) — stop sized off this
- **52-week range:** $61.11 – $112.29 (currently -15.12% from high, +55.96% from low)
- **Returns:** 1M -0.01% | 3M -5.73% | 12M +55.84%
- **Liquidity:** $141.61M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-04-28 (edgar_10q)
- Revenue $1.27B (+20.9% YoY) | EPS growth +83.7% YoY | ROE 5.4% | OpMargin 23.7% | NetMargin 23.8% | Current 3.68

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $95.31 | Market at next open. Position: 17 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $87.83 | -7.8% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $102.93 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.02× | risk $7.48/sh, reward $7.62/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-5.44M; 3 sales ($5.44M), most recent 2026-05-08

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $102.93
- Bull case (75th pct): +17.6% → ~$112.07
- Bear case (25th pct): -1.5% → ~$93.84

---

### #11. **MO** — Consumer Defensive

_MO sits at composite z=+1.82. Top by high quality (rank #12, op-margin 54%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$73.09** | Composite z: **+1.82** | Analyst tgt: $69.45 (-4.97%) — *hold* | β=0.52

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 173 | — |
| Quality | 12 | ROE -68.0%; OpMargin 54.5%; D/E -7.66 |
| Value | 105 | earnings yield 6.50%; revenue TTM $5.43B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $62.34 (+17.24%)
- **50-day SMA:** $67.05 (+9.00%)
- **20-day ATR:** $1.67 (2.3% of price) — stop sized off this
- **52-week range:** $52.91 – $74.56 (currently -1.97% from high, +38.15% from low)
- **Returns:** 1M +12.55% | 3M +10.51% | 12M +38.88%
- **Liquidity:** $695.90M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-04-30 (edgar_10q)
- Revenue $5.43B (+3.2% YoY) | EPS growth +106.3% YoY | ROE -68.0% | OpMargin 54.5% | NetMargin 40.2% | D/E -7.66 | Current 0.62

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $73.09 | Market at next open. Position: 23 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $68.92 | -5.7% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $78.94 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.40× | risk $4.17/sh, reward $5.85/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-1.89M; 1 sales ($1.89M), most recent 2026-03-05

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $78.94
- Bull case (75th pct): +17.6% → ~$85.94
- Bear case (25th pct): -1.5% → ~$71.97

---

### #12. **HCA** — Healthcare

_HCA sits at composite z=+1.82. Top by high quality (rank #50). Price is BELOW the 200-day SMA — countertrend pick, respect the stop._

**Snapshot**
Price: **$423.00** | Composite z: **+1.82** | Analyst tgt: $513.10 (+21.30%) — *buy* | β=1.19

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 127 | — |
| Quality | 50 | ROE -25.7%; D/E -7.04 |
| Value | 108 | earnings yield 6.48%; revenue TTM $19.11B |

**Technical setup**
- **Trend:** downtrend (below 50d + 200d)
- **200-day SMA:** $460.30 (-8.10%)
- **50-day SMA:** $475.61 (-11.06%)
- **20-day ATR:** $13.02 (3.1% of price) — stop sized off this
- **52-week range:** $328.43 – $555.69 (currently -23.88% from high, +28.79% from low)
- **Returns:** 1M -12.42% | 3M -21.59% | 12M +15.88%
- **Liquidity:** $574.35M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-04-29 (edgar_10q)
- Revenue $19.11B (+4.3% YoY) | EPS growth +10.9% YoY | ROE -25.7% | NetMargin 8.5% | D/E -7.04 | Current 0.83

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $423.00 | Market at next open. Position: 4 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $390.44 | -7.7% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $456.84 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.04× | risk $32.56/sh, reward $33.84/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-903,536.74; 1 sales ($903,536.74), most recent 2026-05-07

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $456.84
- Bull case (75th pct): +17.6% → ~$497.37
- Bear case (25th pct): -1.5% → ~$416.50

---

### #13. **GS** — Financial Services

_GS sits at composite z=+1.80. Picked on cross-factor consistency rather than any single factor extreme. Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$948.47** | Composite z: **+1.80** | Analyst tgt: $947.60 (-0.09%) — *hold* | β=1.27

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 69 | — |
| Quality | — | ROE 4.6% |
| Value | 124 | earnings yield 5.78% |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $837.12 (+13.30%)
- **50-day SMA:** $881.20 (+7.63%)
- **20-day ATR:** $22.31 (2.4% of price) — stop sized off this
- **52-week range:** $570.68 – $979.54 (currently -3.17% from high, +66.20% from low)
- **Returns:** 1M +5.39% | 3M +5.34% | 12M +58.29%
- **Liquidity:** $1.67B avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-01 (edgar_10q)
- EPS growth +24.3% YoY | ROE 4.6%

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $948.47 | Market at next open. Position: 1 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $892.70 | -5.9% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $1,024.35 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.36× | risk $55.77/sh, reward $75.88/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-22.18M; 88 open-market buys ($6.87M); 56 sales ($29.05M), most recent 2026-05-06

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $1,024.35
- Bull case (75th pct): +17.6% → ~$1,115.22
- Bear case (25th pct): -1.5% → ~$933.89

---

### #14. **BK** — Financial Services

_BK sits at composite z=+1.79. Picked on cross-factor consistency rather than any single factor extreme. Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$135.02** | Composite z: **+1.79** | Analyst tgt: $142.64 (+5.65%) — *buy* | β=1.07

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 62 | — |
| Quality | — | ROE 3.6%; D/E 0.73 |
| Value | 132 | earnings yield 5.65% |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $114.39 (+18.04%)
- **50-day SMA:** $125.75 (+7.37%)
- **20-day ATR:** $2.73 (2.0% of price) — stop sized off this
- **52-week range:** $85.80 – $138.60 (currently -2.58% from high, +57.37% from low)
- **Returns:** 1M +0.53% | 3M +15.13% | 12M +56.42%
- **Liquidity:** $482.05M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-01 (edgar_10q)
- EPS growth +41.8% YoY | ROE 3.6% | D/E 0.73

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $135.02 | Market at next open. Position: 12 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $128.20 | -5.0% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $145.82 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.58× | risk $6.82/sh, reward $10.80/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-6.57M; 4 sales ($6.57M), most recent 2026-04-17

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $145.82
- Bull case (75th pct): +17.6% → ~$158.76
- Bear case (25th pct): -1.5% → ~$132.94

---

### #15. **HST** — Real Estate

_HST sits at composite z=+1.78. Picked on cross-factor consistency rather than any single factor extreme. Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$21.38** | Composite z: **+1.78** | Analyst tgt: $22.88 (+6.99%) — *buy* | β=1.12

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 98 | — |
| Quality | 127 | ROE 7.2%; OpMargin 19.4% |
| Value | 65 | earnings yield 7.58%; revenue TTM $1.65B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $17.91 (+19.39%)
- **50-day SMA:** $20.10 (+6.37%)
- **20-day ATR:** $0.44 (2.1% of price) — stop sized off this
- **52-week range:** $13.70 – $22.39 (currently -4.51% from high, +56.10% from low)
- **Returns:** 1M +3.94% | 3M +8.64% | 12M +45.62%
- **Liquidity:** $160.02M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-08 (edgar_10q)
- Revenue $1.65B (+3.2% YoY) | EPS growth +105.7% YoY | ROE 7.2% | OpMargin 19.4% | NetMargin 30.0%

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $21.38 | Market at next open. Position: 79 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $20.27 | -5.2% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $23.09 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.55× | risk $1.11/sh, reward $1.71/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-1.54M; 2 sales ($1.54M), most recent 2026-05-08

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $23.09
- Bull case (75th pct): +17.6% → ~$25.14
- Bear case (25th pct): -1.5% → ~$21.05

---

### #16. **WDC** — Technology

_WDC sits at composite z=+1.73. Top by strong momentum (rank #3, +884% past year) + high quality (rank #25, op-margin 36%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$482.02** | Composite z: **+1.73** | Analyst tgt: $507.61 (+5.31%) — *buy* | β=2.16

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 3 | — |
| Quality | 25 | ROE 33.1%; OpMargin 35.7%; D/E 0.16 |
| Value | 269 | earnings yield 3.61%; revenue TTM $3.34B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $211.50 (+127.91%)
- **50-day SMA:** $358.54 (+34.44%)
- **20-day ATR:** $29.43 (6.1% of price) — stop sized off this
- **52-week range:** $48.60 – $525.15 (currently -8.21% from high, +891.81% from low)
- **Returns:** 1M +33.27% | 3M +71.27% | 12M +883.94%
- **Liquidity:** $3.57B avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-01 (edgar_10q)
- Revenue $3.34B (+45.5% YoY) | EPS growth +477.5% YoY | ROE 33.1% | OpMargin 35.7% | NetMargin 96.0% | D/E 0.16 | Current 1.49

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $482.02 | Market at next open. Position: 3 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $424.18 | -12.0% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $520.58 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 0.67× | risk $57.84/sh, reward $38.56/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-27.07M; 56 sales ($27.07M), most recent 2026-05-11

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $520.58
- Bull case (75th pct): +17.6% → ~$566.76
- Bear case (25th pct): -1.5% → ~$474.61

**Risk flags**
- ⚠️ Extended >30% above 200d SMA — pullback risk

---

### #17. **MS** — Financial Services

_MS sits at composite z=+1.69. Picked on cross-factor consistency rather than any single factor extreme. Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$192.51** | Composite z: **+1.69** | Analyst tgt: $203.29 (+5.60%) — *buy* | β=1.21

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 84 | — |
| Quality | — | ROE 4.9%; D/E 3.18 |
| Value | 127 | earnings yield 5.69% |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $166.53 (+15.60%)
- **50-day SMA:** $175.89 (+9.45%)
- **20-day ATR:** $4.12 (2.1% of price) — stop sized off this
- **52-week range:** $120.96 – $197.50 (currently -2.53% from high, +59.15% from low)
- **Returns:** 1M +3.32% | 3M +13.08% | 12M +50.46%
- **Liquidity:** $943.25M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-05 (edgar_10q)
- EPS growth +31.9% YoY | ROE 4.9% | D/E 3.18

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $192.51 | Market at next open. Position: 8 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $182.20 | -5.3% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $207.91 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.49× | risk $10.31/sh, reward $15.40/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-16.62M; 11 sales ($16.62M), most recent 2026-04-20

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $207.91
- Bull case (75th pct): +17.6% → ~$226.36
- Bear case (25th pct): -1.5% → ~$189.55

---

### #18. **NTRS** — Financial Services

_NTRS sits at composite z=+1.69. Picked on cross-factor consistency rather than any single factor extreme. Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$163.86** | Composite z: **+1.69** | Analyst tgt: $171.00 (+4.36%) — *hold* | β=1.29

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 68 | — |
| Quality | — | ROE 4.0% |
| Value | 142 | earnings yield 5.51%; revenue TTM $1.34B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $138.10 (+18.65%)
- **50-day SMA:** $151.32 (+8.28%)
- **20-day ATR:** $3.98 (2.4% of price) — stop sized off this
- **52-week range:** $101.53 – $173.19 (currently -5.39% from high, +61.39% from low)
- **Returns:** 1M +4.52% | 3M +12.57% | 12M +57.90%
- **Liquidity:** $200.59M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-04-30 (edgar_10q)
- Revenue $1.34B (+10.5% YoY) | EPS growth +42.6% YoY | ROE 4.0% | NetMargin 39.2%

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $163.86 | Market at next open. Position: 10 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $153.91 | -6.1% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $176.97 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.32× | risk $9.95/sh, reward $13.11/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-4.85M; 1 open-market buys ($37,442.25); 6 sales ($4.89M), most recent 2026-05-04

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $176.97
- Bull case (75th pct): +17.6% → ~$192.67
- Bear case (25th pct): -1.5% → ~$161.34

---

### #19. **EOG** — Energy

_EOG sits at composite z=+1.69. Top by cheap valuation (rank #52, earnings yield 8.2%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$140.26** | Composite z: **+1.69** | Analyst tgt: $157.50 (+12.29%) — *buy* | β=0.28

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 199 | — |
| Quality | 69 | ROE 6.4%; OpMargin 37.5%; D/E 0.26 |
| Value | 52 | earnings yield 8.21%; revenue TTM $6.92B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $116.95 (+19.93%)
- **50-day SMA:** $136.32 (+2.89%)
- **20-day ATR:** $3.42 (2.4% of price) — stop sized off this
- **52-week range:** $99.86 – $150.70 (currently -6.93% from high, +40.46% from low)
- **Returns:** 1M +4.62% | 3M +17.08% | 12M +25.67%
- **Liquidity:** $497.86M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-05 (edgar_10q)
- Revenue $6.92B (+22.1% YoY) | EPS growth +39.6% YoY | ROE 6.4% | OpMargin 37.5% | NetMargin 28.6% | D/E 0.26 | Current 1.72

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $140.26 | Market at next open. Position: 12 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $131.71 | -6.1% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $151.48 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.31× | risk $8.55/sh, reward $11.22/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-2.52M; 7 sales ($2.52M), most recent 2026-04-30

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $151.48
- Bull case (75th pct): +17.6% → ~$164.92
- Bear case (25th pct): -1.5% → ~$138.10

---

### #20. **TFC** — Financial Services

_TFC sits at composite z=+1.69. Top by cheap valuation (rank #49, earnings yield 8.3%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$46.96** | Composite z: **+1.69** | Analyst tgt: $55.68 (+18.58%) — *buy* | β=0.91

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 169 | — |
| Quality | — | ROE 2.3%; D/E 0.65 |
| Value | 49 | earnings yield 8.30% |

**Technical setup**
- **Trend:** long-term up, short-term pullback (above 200d, below 50d)
- **200-day SMA:** $46.42 (+1.15%)
- **50-day SMA:** $47.44 (-1.02%)
- **20-day ATR:** $1.05 (2.2% of price) — stop sized off this
- **52-week range:** $36.61 – $55.06 (currently -14.71% from high, +28.26% from low)
- **Returns:** 1M -3.99% | 3M -8.56% | 12M +19.06%
- **Liquidity:** $353.51M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-01 (edgar_10q)
- EPS growth +25.3% YoY | ROE 2.3% | D/E 0.65

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $46.96 | Market at next open. Position: 36 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $44.34 | -5.6% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $50.72 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.43× | risk $2.62/sh, reward $3.76/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $50.72
- Bull case (75th pct): +17.6% → ~$55.22
- Bear case (25th pct): -1.5% → ~$46.24

---

### #21. **AES** — Utilities

_AES sits at composite z=+1.68. Top by cheap valuation (rank #24, earnings yield 10.3%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$14.47** | Composite z: **+1.68** | Analyst tgt: $15.11 (+4.43%) — *hold* | β=0.96

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 197 | — |
| Quality | — | ROE 11.0% |
| Value | 24 | earnings yield 10.30%; revenue TTM $3.18B |

**Technical setup**
- **Trend:** uptrend confirmed (above 50d + 200d)
- **200-day SMA:** $13.85 (+4.47%)
- **50-day SMA:** $14.17 (+2.11%)
- **20-day ATR:** $0.07 (0.5% of price) — stop sized off this
- **52-week range:** $9.00 – $17.44 (currently -17.01% from high, +60.82% from low)
- **Returns:** 1M +1.02% | 3M -10.02% | 12M +21.52%
- **Liquidity:** $174.43M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-05 (edgar_10q)
- Revenue $3.18B (+8.7% YoY) | EPS growth +871.4% YoY | ROE 11.0% | NetMargin 15.3% | Current 0.73

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $14.47 | Market at next open. Position: 118 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $13.75 | -5.0% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $15.63 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.60× | risk $0.72/sh, reward $1.16/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $15.63
- Bull case (75th pct): +17.6% → ~$17.01
- Bear case (25th pct): -1.5% → ~$14.25

---

### #22. **CFG** — Financial Services

_CFG sits at composite z=+1.63. Top by strong momentum (rank #57, +51% past year). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$60.86** | Composite z: **+1.63** | Analyst tgt: $73.15 (+20.19%) — *strong_buy* | β=1.04

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 57 | — |
| Quality | 152 | ROE 2.0%; D/E 0.47 |
| Value | 110 | earnings yield 6.36%; revenue TTM $2.17B |

**Technical setup**
- **Trend:** long-term up, short-term pullback (above 200d, below 50d)
- **200-day SMA:** $56.24 (+8.22%)
- **50-day SMA:** $61.24 (-0.62%)
- **20-day ATR:** $1.54 (2.5% of price) — stop sized off this
- **52-week range:** $37.58 – $68.30 (currently -10.89% from high, +61.95% from low)
- **Returns:** 1M -4.83% | 3M -5.84% | 12M +51.07%
- **Liquidity:** $263.28M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-04 (edgar_10q)
- Revenue $2.17B (+12.0% YoY) | EPS growth +46.8% YoY | ROE 2.0% | NetMargin 23.8% | D/E 0.47

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $60.86 | Market at next open. Position: 28 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $57.01 | -6.3% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $65.73 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.27× | risk $3.85/sh, reward $4.87/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-769,494.32; 1 sales ($769,494.32), most recent 2026-04-23

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $65.73
- Bull case (75th pct): +17.6% → ~$71.56
- Bear case (25th pct): -1.5% → ~$59.92

---

### #23. **ATO** — Utilities

_ATO sits at composite z=+1.63. Top by high quality (rank #47, op-margin 39%). Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$176.48** | Composite z: **+1.63** | Analyst tgt: $190.27 (+7.82%) — *hold* | β=0.65

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 158 | — |
| Quality | 47 | ROE 3.9%; OpMargin 39.0% |
| Value | 126 | earnings yield 5.72%; revenue TTM $1.96B |

**Technical setup**
- **Trend:** long-term up, short-term pullback (above 200d, below 50d)
- **200-day SMA:** $173.22 (+1.88%)
- **50-day SMA:** $185.30 (-4.76%)
- **20-day ATR:** $3.65 (2.1% of price) — stop sized off this
- **52-week range:** $147.53 – $192.51 (currently -8.33% from high, +19.62% from low)
- **Returns:** 1M -6.12% | 3M -1.00% | 12M +18.49%
- **Liquidity:** $174.37M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-06 (edgar_10q)
- Revenue $1.96B (+0.6% YoY) | EPS growth +14.5% YoY | ROE 3.9% | OpMargin 39.0% | NetMargin 29.7% | Current 1.00

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $176.48 | Market at next open. Position: 9 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $167.35 | -5.2% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $190.60 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.55× | risk $9.12/sh, reward $14.12/sh |

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $190.60
- Bull case (75th pct): +17.6% → ~$207.51
- Bear case (25th pct): -1.5% → ~$173.77

---

### #24. **GILD** — Healthcare

_GILD sits at composite z=+1.61. Picked on cross-factor consistency rather than any single factor extreme. Price is above the 200-day SMA (confirmed uptrend)._

**Snapshot**
Price: **$129.58** | Composite z: **+1.61** | Analyst tgt: $157.96 (+21.90%) — *buy* | β=0.33

**Factor breakdown**
| Factor | Rank | Detail |
|---|---|---|
| Momentum | 88 | — |
| Quality | 79 | ROE 8.6%; OpMargin 37.2%; D/E 0.94 |
| Value | 163 | earnings yield 5.12%; revenue TTM $6.96B |

**Technical setup**
- **Trend:** long-term up, short-term pullback (above 200d, below 50d)
- **200-day SMA:** $126.81 (+2.18%)
- **50-day SMA:** $137.27 (-5.60%)
- **20-day ATR:** $3.31 (2.6% of price) — stop sized off this
- **52-week range:** $95.33 – $156.40 (currently -17.15% from high, +35.93% from low)
- **Returns:** 1M -6.47% | 3M -15.91% | 12M +35.22%
- **Liquidity:** $823.30M avg daily $ volume

**Fundamentals** (latest filing)
- **Latest filing:** 2026-05-07 (edgar_10q)
- Revenue $6.96B (+4.4% YoY) | EPS growth +54.8% YoY | ROE 8.6% | OpMargin 37.2% | NetMargin 29.0% | D/E 0.94 | Current 1.97

**Trading plan**
| Action | Price | Note |
|---|---|---|
| **ENTRY** | $129.58 | Market at next open. Position: 13 sh (~$1,710.11, 4.2% of equity) |
| **STOP LOSS** | $121.31 | -6.4% from entry — 2.5×ATR bounded to [5%, 12%] so low-vol names aren't hair-triggered and high-vol names don't risk too much |
| **PROFIT TARGET** | $139.95 | +8.0% from entry (strategy median per-pick) |
| **TIME EXIT** | n/a | 2026-08-12 (~63 trading days) — next quarterly rebalance |
| **Risk/Reward** | 1.25× | risk $8.27/sh, reward $10.37/sh |

**Insider activity (last 90 days)**
- ⚪ **NEUTRAL** — net $-10.61M; 14 sales ($10.61M), most recent 2026-04-30

**Expected outcome (63 trading days)**
- Base case (median): **+6.9%** → target $139.95
- Bull case (75th pct): +17.6% → ~$152.36
- Bear case (25th pct): -1.5% → ~$127.59

---
