# AI Sanity Check — 2026-05-19

**Model:** `claude-sonnet-4-6`
**Tokens:** in=2623 out=2027 (cache_read=0 cache_write=0)

## Overall verdict

**REVIEW** (confidence 72/100)

**Key concerns:**

- Sector overconcentration: Financial Services has 3 picks (MTB, NTRS, USB) representing 20% of portfolio; combined with quality concerns on USB this cluster warrants scrutiny
- Multiple borderline z-scores below 1.90 (HST 1.856, GOOG 1.854, RL 1.770, MO 1.763, MU 1.684) — thin signal band for bottom half of list
- PEAD rank NaN for 8 of 15 picks (NEM, MTB, TPR, WDC, NTRS, MO, RL, MU) — PEAD factor effectively absent, composite may be over-relying on momentum/quality/value for these names
- HST pead_rank=5 flags likely imminent earnings catalyst; hotel REIT also carries bottom-quartile quality (qual_rank 276/497)
- WDC val_rank=250 and GOOG val_rank=294 indicate value factor near bottom half of universe — both riding momentum/PEAD with negligible value support
- APA qual_rank=159 is below median in a universe of 497; energy sector fundamentals remain volatile with commodity price sensitivity
- MU val_rank=344 is bottom-quartile on value; semiconductor cycle exposure adds earnings-revision risk despite strong momentum and quality

## Per-pick

| Ticker | Verdict | z | Sector | Reason | Evidence |
|---|---|---|---|---|---|
| NEM | **FLAG** | +2.86 | Basic Materials | no_data / pead_missing | pead_rank is NaN, removing one of four composite pillars. Val_rank=65 is reasonable but the absence of PEAD data means the z-score of 2.86 is inflated relative to a complete-factor peer; gold-miner beta also introduces macro commodity noise. |
| APA | **FLAG** | +2.38 | Energy | weak_quality | qual_rank=159 sits below the universe median (248.5 midpoint for 497 names), a meaningful quality drag for an energy E&P with high leverage sensitivity to oil prices. Strong val_rank=20 and mom_rank=26 partially offset, but quality deterioration in commodity names historically precedes impairment risk. |
| INCY | **KEEP** | +2.29 | Healthcare | balanced_factors | No single factor is outstanding but none is egregiously weak; z-score 2.29 is solid. PEAD rank 28 is supportive. No immediate earnings concern flagged. |
| MTB | **FLAG** | +2.16 | Financial Services | weak_momentum / pead_missing | mom_rank=199 is below-median momentum in a momentum-inclusive composite, making this pick quality+value-driven with PEAD also missing (NaN). Regional bank exposure carries ongoing macro rate sensitivity; momentum absence suggests price action is not confirming fundamental thesis. |
| TPR | **FLAG** | +2.16 | Consumer Cyclical | weak_value / pead_missing | val_rank=171 is below median and PEAD is NaN; the pick is primarily a momentum story (mom_rank=31) for a discretionary retailer. Consumer spending headwinds and missing PEAD signal reduce conviction; borderline composite given factor gaps. |
| WDC | **FLAG** | +2.07 | Technology | weak_value / pead_missing | val_rank=250 is bottom half of universe and PEAD is NaN; the composite is almost entirely driven by very strong momentum (rank=3) and quality (rank=26). WDC is a cyclical storage hardware name where momentum can reverse sharply; single-factor dependency with no PEAD confirmation is a risk. |
| NTRS | **FLAG** | +2.06 | Financial Services | sector_cluster / weak_value / pead_missing | Third Financial Services name in the portfolio (alongside MTB and USB), pushing sector weight toward the 30% cap. Val_rank=143 and PEAD NaN mean the composite is carried by moderate momentum and quality scores only; incremental sector concentration risk. |
| CF | **FLAG** | +1.92 | Basic Materials | sector_cluster / borderline_zscore | Second Basic Materials pick alongside NEM; z-score 1.92 is borderline. pead_rank=99 is near the median, providing weak post-earnings drift support. Fertilizer prices are cyclically volatile, and the sector double-up with NEM should be reviewed against the 30% sector cap logic. |
| BMY | **FLAG** | +1.91 | Healthcare | fundamental_concern / weak_quality | qual_rank=113 is below median for a large-cap pharma; Bristol-Myers faces known pipeline and patent-cliff pressures (Revlimid erosion, Opdivo competition) that represent fundamental deterioration risk. Borderline z-score of 1.91 provides thin signal buffer. |
| USB | **FLAG** | +1.90 | Financial Services | weak_quality / sector_cluster | qual_rank=155 is the weakest quality score among the three Financial Services picks; USB has faced deposit-cost pressure and commercial real estate exposure concerns. Combined with MTB and NTRS this creates a concentrated regional/trust-bank cluster that amplifies sector-specific macro risk. |
| HST | **VETO** | +1.86 | Real Estate | earnings_imminent / weak_quality | pead_rank=5 strongly suggests earnings are imminent (within ~5 trading days), adding significant binary event noise to the position. qual_rank=276 is bottom-quartile, making this a low-quality name entering a known uncertainty window; risk/reward is asymmetrically poor for a paper-trade rebalance. |
| GOOG | **FLAG** | +1.85 | Communication Services | weak_value / borderline_zscore | val_rank=294 is bottom-third of universe; z-score 1.854 is borderline. PEAD rank=17 is a genuine positive, but the pick is essentially a momentum+PEAD story with near-zero value support. Antitrust and AI-competition overhangs represent fundamental risk not captured in quantitative factors. |
| RL | **FLAG** | +1.77 | Consumer Cyclical | weak_value / borderline_zscore / pead_missing | z-score 1.770 is the second-weakest in the list; val_rank=151 is below median; PEAD is NaN. Three simultaneous weaknesses produce a borderline, factor-incomplete pick in a discretionary sector facing consumer spending pressure. |
| MO | **FLAG** | +1.76 | Consumer Defensive | weak_momentum / borderline_zscore / pead_missing | mom_rank=211 is well below median; z-score 1.763 is near the bottom of the list. The pick is almost entirely a quality+value story for a secular-decline tobacco company. PEAD NaN removes a key confirmation signal; lowest-conviction name in the batch. |
| MU | **FLAG** | +1.68 | Technology | weak_value / borderline_zscore / pead_missing | val_rank=344 is bottom-quartile; z-score 1.684 is the weakest in the list. Strong momentum (rank=7) and quality (rank=13) are real positives, but the semiconductor cycle is highly mean-reverting and PEAD NaN means no earnings-drift confirmation. Thin composite signal for a high-beta cyclical. |

---

*Advisory only. This output is logged for verdict-vs-outcome tracking but does NOT block paper-trade execution.*