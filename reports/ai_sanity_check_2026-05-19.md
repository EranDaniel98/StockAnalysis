# AI Sanity Check — 2026-05-19

**Model:** `claude-sonnet-4-6`
**Tokens:** in=3226 out=1489 (cache_read=0 cache_write=0)

## Overall verdict

**HOLD** (confidence 82/100)

**Key concerns:**

- SNDK: SanDisk was acquired by Western Digital in 2016 and the ticker was delisted; a 'SNDK' ticker in 2026 may represent a newly re-listed entity (WDC spun out its flash business as SanDisk in early 2025) -- continuity of PIT factor history needs verification to rule out a data/lookahead issue, especially given WDC is also in the basket.

## Per-pick

| Ticker | Verdict | z | Sector | Reason | Evidence |
|---|---|---|---|---|---|
| NEM | **KEEP** | +2.78 | Basic Materials | implementation_ok | Z-score 2.78 well above 1.7 threshold; mom_rank 18 and qual_rank 20 both strongly above-median, supporting composite. No implementation issue. |
| TPR | **KEEP** | +2.52 | Consumer Cyclical | implementation_ok | Z-score 2.52; pead_rank 4 and mom_rank 31 carry the composite. Hysteresis _eff_rank=1 consistent with held name. No implementation issue. |
| APA | **KEEP** | +2.48 | Energy | implementation_ok | Z-score 2.48; mom_rank 26 and val_rank 20 strongly support composite. Energy sector, one of two Energy picks so no cap issue. |
| WDC | **KEEP** | +2.39 | Technology | implementation_ok | Z-score 2.39; mom_rank 3 and qual_rank 26 are exceptional. Technology sector, one of three Tech picks (3/15=20%, under 30% cap). |
| INCY | **KEEP** | +2.37 | Healthcare | implementation_ok | Z-score 2.37; mom_rank 63 and val_rank 91 are above median, PEAD 52 near median -- composite blend supports inclusion. Healthcare, one of two HC picks. |
| OXY | **KEEP** | +2.04 | Energy | implementation_ok | Z-score 2.04; val_rank 52 and pead_rank 10 drive the composite despite weaker momentum and quality. Two Energy picks total (2/15=13%), well under cap. |
| BMY | **KEEP** | +2.03 | Healthcare | implementation_ok | Z-score 2.03; val_rank 72 is the primary driver; other factors mid-range. Two Healthcare picks (2/15=13%), under cap. No implementation issue. |
| CF | **KEEP** | +2.02 | Basic Materials | implementation_ok | Z-score 2.02; qual_rank 45 and val_rank 48 both above median support the composite. Two Basic Materials picks (2/15=13%), under cap. |
| NTRS | **KEEP** | +1.96 | Financial Services | implementation_ok | Z-score 1.96; mom_rank 71 and qual_rank 67 both above median. Single Financial Services pick, no sector cap concern. |
| HST | **KEEP** | +1.93 | Real Estate | implementation_ok | Z-score 1.93; pead_rank 7 and val_rank 69 carry the composite despite weak qual_rank. One of two Real Estate picks (2/15=13%). No implementation issue. |
| GOOG | **KEEP** | +1.93 | Communication Services | implementation_ok | Z-score 1.93; mom_rank 27 and pead_rank 30 both above median support composite. Single Communication Services pick. No implementation issue. |
| RL | **KEEP** | +1.84 | Consumer Cyclical | implementation_ok | Z-score 1.84; _eff_rank=3 indicates hysteresis retention (raw rank 14 with 0.75 bonus applied). Two Consumer Cyclical picks (2/15=13%), under cap. Borderline z is expected at cutoff. |
| SNDK | **FLAG** | +1.81 | Technology | data_error | SNDK was delisted after WDC acquisition in 2016; if this represents the 2025 WDC flash spin-off re-listing as SanDisk, continuous PIT factor history (especially quality/value) may not be available or may contain lookahead contamination. WDC also appears in the basket, raising potential double-count of the same underlying business. |
| MU | **KEEP** | +1.75 | Technology | implementation_ok | Z-score 1.75 borderline but valid at top-3% cutoff; mom_rank 7 and qual_rank 13 are exceptional, supporting composite despite weak value. Third Technology pick (3/15=20%), under 30% cap. |
| FRT | **KEEP** | +1.70 | Real Estate | implementation_ok | Z-score 1.70 borderline; qual_rank 61 and pead_rank 39 above median. _eff_rank=7 reflects hysteresis retention at rank 18. Two Real Estate picks (2/15=13%), under cap. |

---

*Advisory only. This output is logged for verdict-vs-outcome tracking but does NOT block paper-trade execution.*