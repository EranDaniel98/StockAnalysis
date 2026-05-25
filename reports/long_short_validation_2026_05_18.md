# Long-Short Factor Validation — 2026-05-18

User authorized 2026-05-18: ran a market-neutral variant of the
factor strategy. Long top-5% by composite (m+q+v+PEAD), short bottom-5%,
half-capital each side. 50bps/yr borrow cost on shorts. Net exposure
~0; gross ~1.0x. 5bps round-trip transaction cost on every leg.

## Headline

**Mixed result that DEMANDS the right benchmark.** Long-short produces
sharply lower absolute returns than long-only (the strategy has ~0
market beta) but materially better drawdowns and competitive Sharpe.
**Comparing it to SPY is wrong** — SPY is the long-only benchmark.
The right benchmark for market-neutral is the risk-free rate.

## Numbers

| Window | LS Total | LS CAGR* | LS Sharpe | LS Max DD | Long-only+PEAD α | LS α vs SPY |
|---|---|---|---|---|---|---|
| 2020-2022 (COVID) | +5.28% | +2.61% | **0.95** | **-6.69%** | +4.02% | +9.62% |
| 2022-2024 | +8.21% | +4.05% | 0.52 | -12.51% | +11.15% | -25.54% |
| 2024-2026 | +20.35% | +9.85% | **1.25** | **-6.04%** | +24.87% | -24.81% |
| **3-window avg** | — | **+5.50%** | **0.91** | **-8.41%** | +13.35% | -13.58% |

\* CAGR computed over the 2-year window.

For comparison, long-only+PEAD same windows:
* Sharpe avg: 1.30
* DD avg: -17.0%
* Total CAGR avg: ~+6.5%/yr above SPY (with full market beta)

## Reading

**Long-short is a DIFFERENT product, not a strictly-better version
of long-only.** The two answer different questions:

* **Long-only (current production):** "Beat SPY." 100% market beta;
  alpha layered on top. Big drawdowns when the market crashes.
  +13.35% avg α vs SPY on the 3-window test.
* **Long-short:** "Earn an absolute return uncorrelated with SPY."
  ~0% market beta; alpha = factor spread. Much smaller drawdowns
  (-8.41% avg max DD vs SPY's -16-18% across the windows). ~+5.5%/yr
  absolute CAGR on the 3-window test.

The right benchmark for long-short is the risk-free rate (call it
~3-4%/yr over the test period). Against cash, long-short produces
roughly +1.5-2pp/yr of excess return, with much lower realized vol.
Against SPY, long-short looks awful — but SPY isn't what an investor
puts MARKET-NEUTRAL capital against.

## The 2022-2024 fold is the killer

Sharpe 0.52, total +8.21% with negative skew. Why: the bottom-decile
of the composite during the 2022 bear rally heavily included "value
traps" and beaten-down growth that rallied HARDER than the average
SP500 name during the 2023-24 recovery. Shorting names that were
ranked WORST by m+q+v+PEAD lost money — exactly when the strategy
expected them to keep underperforming.

This is the classic risk in cross-sectional factor shorts: low-quality
names rally when sentiment turns. Walk-forward fails on this window
(min_sharpe -0.81).

## Where long-short shines

* **2020-2022 COVID:** Sharpe 0.95, DD -6.69%. While long-only +PEAD
  earned +4.02% α (a slight market beat in a wash), long-short
  earned an absolute +5.28% return WITHOUT taking market beta — and
  did so with HALF the drawdown of any long-only variant.
* **2024-2026:** Sharpe 1.25 — basically matches SPY's Sharpe — with
  much lower DD and zero market exposure. The 2025 correction took
  long-only to -23% DD; long-short felt it as -6%.

## Caveats

1. **Borrow cost is modeled at 50bps/yr.** Liquid SP500 longs/shorts
   trade at this level for retail. Hard-to-borrow names (HTB) can
   cost 5-20%/yr or more; if the bottom-decile composite ranks
   include any HTB names, real borrow drag would be higher. The test
   assumes worst-case bottom names ≈ best-case borrow.
2. **No locate / availability risk.** Backtest assumes every short
   target is executable. In live, you'd hit "locate failed" on some
   names — typically the most-shorted ones, which are the ones the
   composite would rank lowest.
3. **No margin call modeling.** Long-short with 50/50 capital has
   ~2x leverage; a sharp move against both legs (extremely rare but
   real) can blow through margin requirements.
4. **Walk-forward fails on all three windows.** Fold-level variance
   is high without market beta to wash out small mistakes. This is a
   real red flag for live deployment.

## Verdict for production

**Opt-in via `--long-short`. NOT enabled in the daily pipeline.**
The strategy is a viable market-neutral overlay for a portion of
capital, NOT a replacement for the long-only path. Decision tree:

* **If you want to beat SPY** → keep long-only d05_r63 + PEAD.
  +13.35% avg α, full market beta, large but manageable drawdowns.
* **If you want a market-neutral sleeve** → long-short with 25-50%
  of risk capital, knowing it'll trail SPY in raging bull years
  (2024-2026 was a bull, LS earned +20% absolute while SPY did +45%)
  but smooth the equity curve dramatically.

**Live wiring NOT shipped.** Shorts on Alpaca require:
* Margin-account enablement (not default for paper)
* Locate at order time (variable availability)
* Borrow-cost tracking per position (Alpaca exposes this but we don't
  consume it in `paper_trade_factor_picks.py`)
* Per-position SSR / short-sale-restriction handling

That's a separate ~2-day project. Hold until you've decided whether
the strategy profile is worth the operational complexity.

## Source files

- `data/backtests/d05_r63_{2020,2022,2024}_ls.json`
- Code in `scripts/run_factor_backtest.py:--long-short` (+ `--borrow-bps`,
  `--short-decile`).
