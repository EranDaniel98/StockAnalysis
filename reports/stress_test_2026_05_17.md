# Portfolio Stress Test — 2026-05-17

*Equity: $41,042.60 | Positions: 24 equal-weight | Avg portfolio beta: 0.90*

These are POINT-ESTIMATE stress tests using each name's trailing beta (from yfinance) + sector shock overlays. Real outcomes will dispersed around these by ±5-10 pp at the portfolio level.

## Scenario summary

| Scenario | Strategy | SPY | Alpha | Strategy $P&L |
|---|---|---|---|---|
| SPY +10% rally | +9.02% | +10.00% | -0.98% | $+3,703 |
| SPY -10% correction | -9.02% | -10.00% | +0.98% | $-3,703 |
| SPY -20% bear | -19.85% | -20.00% | +0.15% | $-8,146 |
| COVID-style -35% crash | -46.46% | -35.00% | -11.46% | $-19,070 |
| Banking crisis (financials -25%) | -13.68% | -5.00% | -8.68% | $-5,614 |
| Oil shock (energy +30%) | -0.55% | -5.00% | +4.45% | $-227 |
| Aggressive rate hikes (+200bps) | -6.80% | -8.00% | +1.20% | $-2,791 |
| Recession (cyclicals -25%) | -19.93% | -15.00% | -4.93% | $-8,178 |

## Range

- **Worst case (COVID-style -35% crash):** portfolio -46.5% ($-19,070)
- **Best case (SPY +10% rally):** portfolio +9.0% ($+3,703)

## Per-scenario detail

### SPY +10% rally

*Steady 3-month rally; tests upside capture.*

- Portfolio: **+9.02%** ($+3,703)
- SPY: +10.00% ($+4,104) | Alpha: -0.98%

**Hardest hit:**
- OXY (Energy, β=0.17): +1.7% → $+29
- EOG (Energy, β=0.28): +2.8% → $+48
- GILD (Healthcare, β=0.33): +3.3% → $+57

**Best performers:**
- WDC (Technology, β=2.16): +21.6% → $+369
- STT (Financial Services, β=1.46): +14.6% → $+250
- SYF (Financial Services, β=1.36): +13.6% → $+233

### SPY -10% correction

*Garden-variety pullback; tests defensive behavior.*

- Portfolio: **-9.02%** ($-3,703)
- SPY: -10.00% ($-4,104) | Alpha: +0.98%

**Hardest hit:**
- WDC (Technology, β=2.16): -21.6% → $-369
- STT (Financial Services, β=1.46): -14.6% → $-250
- SYF (Financial Services, β=1.36): -13.6% → $-233

**Best performers:**
- OXY (Energy, β=0.17): -1.7% → $-29
- EOG (Energy, β=0.28): -2.8% → $-48
- GILD (Healthcare, β=0.33): -3.3% → $-57

### SPY -20% bear

*2022-style 20% drawdown over the quarter.*

- Portfolio: **-19.85%** ($-8,146)
- SPY: -20.00% ($-8,209) | Alpha: +0.15%

**Hardest hit:**
- WDC (Technology, β=2.16): -47.5% → $-812
- STT (Financial Services, β=1.46): -32.1% → $-549
- SYF (Financial Services, β=1.36): -30.0% → $-512

**Best performers:**
- OXY (Energy, β=0.17): -3.8% → $-65
- EOG (Energy, β=0.28): -6.1% → $-105
- GILD (Healthcare, β=0.33): -7.3% → $-125

### COVID-style -35% crash

*Q1 2020-style risk-off. Cyclicals, financials, REITs hit hardest; defensives + healthcare hold up.*

- Portfolio: **-46.46%** ($-19,070)
- SPY: -35.00% ($-14,365) | Alpha: -11.46%

**Hardest hit:**
- WDC (Technology, β=2.16): -98.2% → $-1,679
- STT (Financial Services, β=1.46): -76.4% → $-1,307
- SYF (Financial Services, β=1.36): -72.0% → $-1,231

**Best performers:**
- GILD (Healthcare, β=0.33): -10.1% → $-173
- MO (Consumer Defensive, β=0.52): -13.6% → $-233
- CF (Basic Materials, β=0.42): -19.0% → $-324

### Banking crisis (financials -25%)

*Like SVB 2023: regional banks crash, broader market mostly unaffected. Tests portfolio's 42% Financial Services concentration.*

- Portfolio: **-13.68%** ($-5,614)
- SPY: -5.00% ($-2,052) | Alpha: -8.68%

**Hardest hit:**
- STT (Financial Services, β=1.46): -27.3% → $-467
- SYF (Financial Services, β=1.36): -26.8% → $-458
- NTRS (Financial Services, β=1.29): -26.4% → $-452

**Best performers:**
- OXY (Energy, β=0.17): -0.9% → $-15
- EOG (Energy, β=0.28): -1.4% → $-24
- GILD (Healthcare, β=0.33): -1.7% → $-28

### Oil shock (energy +30%)

*Geopolitical oil shock. Energy + materials rally; consumer + industrials feel the input cost.*

- Portfolio: **-0.55%** ($-227)
- SPY: -5.00% ($-2,052) | Alpha: +4.45%

**Hardest hit:**
- WDC (Technology, β=2.16): -10.8% → $-185
- STT (Financial Services, β=1.46): -7.3% → $-125
- SYF (Financial Services, β=1.36): -6.8% → $-116

**Best performers:**
- OXY (Energy, β=0.17): +24.1% → $+413
- EOG (Energy, β=0.28): +23.6% → $+404
- APA (Energy, β=0.37): +23.1% → $+396

### Aggressive rate hikes (+200bps)

*Fed surprise hike. Bond-proxy sectors crater; banks benefit from net interest margin lift.*

- Portfolio: **-6.80%** ($-2,791)
- SPY: -8.00% ($-3,283) | Alpha: +1.20%

**Hardest hit:**
- WDC (Technology, β=2.16): -27.3% → $-466
- HST (Real Estate, β=1.12): -23.9% → $-409
- AES (Utilities, β=0.96): -17.7% → $-302

**Best performers:**
- MTB (Financial Services, β=0.59): +0.3% → $+5
- OXY (Energy, β=0.17): -1.4% → $-24
- EOG (Energy, β=0.28): -2.2% → $-38

### Recession (cyclicals -25%)

*2008-style recession. Defensive rotation; cyclicals, energy, financials all suffer.*

- Portfolio: **-19.93%** ($-8,178)
- SPY: -15.00% ($-6,156) | Alpha: -4.93%

**Hardest hit:**
- WDC (Technology, β=2.16): -35.6% → $-609
- STT (Financial Services, β=1.46): -34.1% → $-583
- SYF (Financial Services, β=1.36): -32.5% → $-555

**Best performers:**
- MO (Consumer Defensive, β=0.52): +1.4% → $+25
- GILD (Healthcare, β=0.33): -0.5% → $-8
- ATO (Utilities, β=0.65): -5.7% → $-97

## Sector exposure (drives scenario sensitivity)

| Sector | Count | % | Beta avg |
|---|---|---|---|
| Financial Services | 11 | 45.8% | 1.11 |
| Energy | 3 | 12.5% | 0.27 |
| Healthcare | 3 | 12.5% | 0.77 |
| Basic Materials | 2 | 8.3% | 0.43 |
| Utilities | 2 | 8.3% | 0.80 |
| Consumer Defensive | 1 | 4.2% | 0.52 |
| Real Estate | 1 | 4.2% | 1.12 |
| Technology | 1 | 4.2% | 2.16 |

## Risk recommendations

- Portfolio beta 0.90 is approximately market-neutral — moves roughly 1:1 with SPY.
- ⚠️ **Financial Services is 46% of portfolio.** Banking crisis scenario hits hard. Mitigation: cap any sector at 25% in next rebalance, OR add explicit hedges (puts on KRE / XLF).

---
*Read with `reports/portfolio_analysis_*.md` for the per-stock detail behind these scenarios.*