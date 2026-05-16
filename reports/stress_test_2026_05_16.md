# Portfolio Stress Test — 2026-05-16

*Equity: $41,042.60 | Positions: 24 equal-weight | Avg portfolio beta: 0.91*

These are POINT-ESTIMATE stress tests using each name's trailing beta (from yfinance) + sector shock overlays. Real outcomes will dispersed around these by ±5-10 pp at the portfolio level.

## Scenario summary

| Scenario | Strategy | SPY | Alpha | Strategy $P&L |
|---|---|---|---|---|
| SPY +10% rally | +9.15% | +10.00% | -0.85% | $+3,754 |
| SPY -10% correction | -9.15% | -10.00% | +0.85% | $-3,754 |
| SPY -20% bear | -20.12% | -20.00% | -0.12% | $-8,259 |
| COVID-style -35% crash | -46.20% | -35.00% | -11.20% | $-18,963 |
| Banking crisis (financials -25%) | -12.91% | -5.00% | -7.91% | $-5,297 |
| Oil shock (energy +30%) | -1.24% | -5.00% | +3.76% | $-509 |
| Aggressive rate hikes (+200bps) | -7.36% | -8.00% | +0.64% | $-3,020 |
| Recession (cyclicals -25%) | -19.84% | -15.00% | -4.84% | $-8,144 |

## Range

- **Worst case (COVID-style -35% crash):** portfolio -46.2% ($-18,963)
- **Best case (SPY +10% rally):** portfolio +9.1% ($+3,754)

## Per-scenario detail

### SPY +10% rally

*Steady 3-month rally; tests upside capture.*

- Portfolio: **+9.15%** ($+3,754)
- SPY: +10.00% ($+4,104) | Alpha: -0.85%

**Hardest hit:**
- OXY (Energy, β=0.17): +1.7% → $+29
- APA (Energy, β=0.37): +3.7% → $+64
- CF (Basic Materials, β=0.42): +4.2% → $+71

**Best performers:**
- STT (Financial Services, β=1.46): +14.6% → $+250
- SYF (Financial Services, β=1.36): +13.6% → $+233
- GS (Financial Services, β=1.27): +12.7% → $+218

### SPY -10% correction

*Garden-variety pullback; tests defensive behavior.*

- Portfolio: **-9.15%** ($-3,754)
- SPY: -10.00% ($-4,104) | Alpha: +0.85%

**Hardest hit:**
- STT (Financial Services, β=1.46): -14.6% → $-250
- SYF (Financial Services, β=1.36): -13.6% → $-233
- GS (Financial Services, β=1.27): -12.7% → $-218

**Best performers:**
- OXY (Energy, β=0.17): -1.7% → $-29
- APA (Energy, β=0.37): -3.7% → $-64
- CF (Basic Materials, β=0.42): -4.2% → $-71

### SPY -20% bear

*2022-style 20% drawdown over the quarter.*

- Portfolio: **-20.12%** ($-8,259)
- SPY: -20.00% ($-8,209) | Alpha: -0.12%

**Hardest hit:**
- STT (Financial Services, β=1.46): -32.1% → $-549
- SYF (Financial Services, β=1.36): -30.0% → $-512
- GS (Financial Services, β=1.27): -28.0% → $-479

**Best performers:**
- OXY (Energy, β=0.17): -3.8% → $-65
- APA (Energy, β=0.37): -8.2% → $-141
- CF (Basic Materials, β=0.42): -9.2% → $-157

### COVID-style -35% crash

*Q1 2020-style risk-off. Cyclicals, financials, REITs hit hardest; defensives + healthcare hold up.*

- Portfolio: **-46.20%** ($-18,963)
- SPY: -35.00% ($-14,365) | Alpha: -11.20%

**Hardest hit:**
- STT (Financial Services, β=1.46): -76.4% → $-1,307
- SYF (Financial Services, β=1.36): -72.0% → $-1,231
- GS (Financial Services, β=1.27): -68.0% → $-1,162

**Best performers:**
- MO (Consumer Defensive, β=0.52): -13.6% → $-233
- CF (Basic Materials, β=0.42): -19.0% → $-324
- NEM (Basic Materials, β=0.45): -20.4% → $-349

### Banking crisis (financials -25%)

*Like SVB 2023: regional banks crash, broader market mostly unaffected. Tests portfolio's 42% Financial Services concentration.*

- Portfolio: **-12.91%** ($-5,297)
- SPY: -5.00% ($-2,052) | Alpha: -7.91%

**Hardest hit:**
- STT (Financial Services, β=1.46): -27.3% → $-467
- SYF (Financial Services, β=1.36): -26.8% → $-458
- GS (Financial Services, β=1.27): -26.4% → $-451

**Best performers:**
- OXY (Energy, β=0.17): -0.9% → $-15
- APA (Energy, β=0.37): -1.9% → $-32
- CF (Basic Materials, β=0.42): -2.1% → $-36

### Oil shock (energy +30%)

*Geopolitical oil shock. Energy + materials rally; consumer + industrials feel the input cost.*

- Portfolio: **-1.24%** ($-509)
- SPY: -5.00% ($-2,052) | Alpha: +3.76%

**Hardest hit:**
- STT (Financial Services, β=1.46): -7.3% → $-125
- SYF (Financial Services, β=1.36): -6.8% → $-116
- GS (Financial Services, β=1.27): -6.4% → $-109

**Best performers:**
- OXY (Energy, β=0.17): +24.1% → $+413
- APA (Energy, β=0.37): +23.1% → $+396
- CF (Basic Materials, β=0.42): +7.9% → $+135

### Aggressive rate hikes (+200bps)

*Fed surprise hike. Bond-proxy sectors crater; banks benefit from net interest margin lift.*

- Portfolio: **-7.36%** ($-3,020)
- SPY: -8.00% ($-3,283) | Alpha: +0.64%

**Hardest hit:**
- HST (Real Estate, β=1.12): -23.9% → $-409
- DELL (Technology, β=1.06): -18.5% → $-316
- GOOG (Communication Services, β=1.27): -18.1% → $-310

**Best performers:**
- MTB (Financial Services, β=0.59): +0.3% → $+5
- OXY (Energy, β=0.17): -1.4% → $-24
- TFC (Financial Services, β=0.91): -2.2% → $-38

### Recession (cyclicals -25%)

*2008-style recession. Defensive rotation; cyclicals, energy, financials all suffer.*

- Portfolio: **-19.84%** ($-8,144)
- SPY: -15.00% ($-6,156) | Alpha: -4.84%

**Hardest hit:**
- STT (Financial Services, β=1.46): -34.1% → $-583
- SYF (Financial Services, β=1.36): -32.5% → $-555
- GS (Financial Services, β=1.27): -31.0% → $-530

**Best performers:**
- MO (Consumer Defensive, β=0.52): +1.4% → $+25
- INCY (Healthcare, β=0.80): -8.2% → $-139
- VTRS (Healthcare, β=0.87): -9.4% → $-161

## Sector exposure (drives scenario sensitivity)

| Sector | Count | % | Beta avg |
|---|---|---|---|
| Financial Services | 10 | 41.7% | 1.10 |
| Healthcare | 3 | 12.5% | 0.95 |
| Basic Materials | 3 | 12.5% | 0.44 |
| Energy | 2 | 8.3% | 0.27 |
| Communication Services | 2 | 8.3% | 1.27 |
| Technology | 1 | 4.2% | 1.06 |
| Consumer Defensive | 1 | 4.2% | 0.52 |
| Real Estate | 1 | 4.2% | 1.12 |
| Utilities | 1 | 4.2% | 0.96 |

## Risk recommendations

- Portfolio beta 0.91 is approximately market-neutral — moves roughly 1:1 with SPY.
- ⚠️ **Financial Services is 42% of portfolio.** Banking crisis scenario hits hard. Mitigation: cap any sector at 25% in next rebalance, OR add explicit hedges (puts on KRE / XLF).

---
*Read with `reports/portfolio_analysis_*.md` for the per-stock detail behind these scenarios.*