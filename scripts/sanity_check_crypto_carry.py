"""Independent sanity-check of the delta-neutral funding-carry headline.

Reads the already-populated data/crypto_cache/ (funding + perp/spot daily klines),
reconstructs the carry book from scratch, and stress-tests the headline claims:
  - Is annualized Sharpe ~6.6 plausible for a funding-carry book?
  - Is 2022 (crypto winter) genuinely positive, or is the headline a 2021/2023 artifact?
  - Per-coin carry + listing-date / survivorship issues (SOL/DOT/BNB).
  - Funding-sign regime: how much of the return is "always-positive funding" vs tail.

This script does NOT trade and needs no API key. Pure offline recompute.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path("data/crypto_cache")
COINS = ["BTC", "ETH", "XRP", "LTC", "LINK", "ADA", "DOGE", "DOT", "SOL", "BNB"]
FUNDINGS_PER_DAY = 3  # 8h funding interval


def load_funding(coin: str) -> pd.Series:
    rows = json.load(open(CACHE / f"funding_{coin}USDT.json"))
    df = pd.DataFrame(rows)
    df["fundingRate"] = df["fundingRate"].astype(float)
    df["t"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df["date"] = df["t"].dt.floor("D")
    # daily funding = sum of (up to) 3 intraday funding prints; short-perp RECEIVES funding
    daily = df.groupby("date")["fundingRate"].sum()
    daily.index = daily.index.tz_localize(None)
    return daily


def load_perp_close(coin: str) -> pd.Series:
    rows = json.load(open(CACHE / f"klines_perp_{coin}USDT.json"))
    idx = pd.to_datetime([r[0] for r in rows], unit="ms")
    close = pd.Series([float(r[4]) for r in rows], index=idx, name=coin)
    return close


def main() -> None:
    listing = json.load(open(CACHE / "listing_dates.json"))

    funding = {c: load_funding(c) for c in COINS}
    perp = {c: load_perp_close(c) for c in COINS}

    # ---- daily delta-neutral carry per coin = daily funding received (short perp) ----
    # delta-neutral => price PnL ~0; the carry IS the funding. We ignore spot/perp basis
    # convergence (small) and just credit funding to a coin on days it has a funding print.
    fund_df = pd.DataFrame(funding).sort_index()

    full_idx = pd.date_range(fund_df.index.min(), fund_df.index.max(), freq="D")
    fund_df = fund_df.reindex(full_idx)

    # Per-coin annualized carry (mean daily funding * 365), only over the coin's live window
    print("=== PER-COIN ANNUALIZED CARRY (mean daily funding x365, live window only) ===")
    per_coin = {}
    for c in COINS:
        s = fund_df[c].dropna()
        ann = s.mean() * 365 * 100
        per_coin[c] = ann
        print(f"  {c:5s}: {ann:+6.2f}%/yr   n_days={len(s):4d}  start={s.index.min().date()}")

    # ---- equal-weight portfolio: each day, average funding across coins that are LIVE ----
    # This is the honest construction (no forward-fill of dead coins, no survivorship).
    daily_port = fund_df.mean(axis=1, skipna=True)  # mean over live coins that day
    daily_port = daily_port.dropna()

    # Net of costs: 30bps round-trip is a ONE-TIME entry/exit on the whole book, not daily.
    # The headline applies it once; 5bps annual roll + 2bps/rebal slippage are recurring.
    # We model recurring drag: 5bps/yr roll + assume monthly rebal => 2bps*12 = 24bps/yr.
    # Daily drag:
    ann_roll_bps = 5 / 1e4
    ann_slip_bps = 2 * 12 / 1e4  # 2bps per monthly rebal
    daily_drag = (ann_roll_bps + ann_slip_bps) / 365
    daily_net = daily_port - daily_drag
    # one-time 30bps round-trip on first/last day
    one_time = 0.0030

    print("\n=== PORTFOLIO HEADLINE RECONSTRUCTION (equal-weight live coins) ===")
    n = len(daily_net)
    years = n / 365.25
    # Non-compounded (constant notional) total return:
    tot_simple = daily_net.sum() - one_time
    # Compounded:
    eq = (1 + daily_net).cumprod()
    eq *= (1 - one_time)  # entry cost
    tot_comp = eq.iloc[-1] - 1
    cagr = (1 + tot_comp) ** (1 / years) - 1
    mu = daily_net.mean()
    sd = daily_net.std(ddof=1)
    sharpe = (mu / sd) * np.sqrt(365) if sd > 0 else np.nan
    sharpe_gross = (daily_port.mean() / daily_port.std(ddof=1)) * np.sqrt(365)
    dd = (eq / eq.cummax() - 1).min()

    print(f"  n_days={n}  years={years:.2f}")
    print(f"  net total return (simple, const notional): {tot_simple*100:+.2f}%")
    print(f"  net total return (compounded):             {tot_comp*100:+.2f}%")
    print(f"  net CAGR (compounded):                     {cagr*100:+.2f}%")
    print(f"  annualized Sharpe (net):                   {sharpe:.3f}  (gross {sharpe_gross:.3f})")
    print(f"  max drawdown (compounded):                 {dd*100:.2f}%")
    print(f"  mean daily net: {mu*1e4:.3f} bps   std daily: {sd*1e4:.3f} bps")

    # ---- BY YEAR ----
    print("\n=== BY-YEAR (net, simple sum of daily funding net of recurring drag) ===")
    by_year = daily_net.groupby(daily_net.index.year)
    for yr, grp in by_year:
        yr_ret = grp.sum() * 100
        yr_sharpe = (grp.mean() / grp.std(ddof=1)) * np.sqrt(365) if grp.std(ddof=1) > 0 else np.nan
        eq_y = (1 + grp).cumprod()
        yr_dd = (eq_y / eq_y.cummax() - 1).min() * 100
        flag = "  <-- NEGATIVE" if yr_ret < 0 else ""
        print(f"  {yr}: {yr_ret:+6.2f}%  (S {yr_sharpe:6.2f} / DD {yr_dd:6.2f})  n={len(grp)}{flag}")

    # ---- 2022 decomposition: positive-funding days vs negative ----
    print("\n=== 2022 FUNDING REGIME DECOMPOSITION ===")
    d22 = daily_port[daily_port.index.year == 2022]
    pos = d22[d22 > 0]
    neg = d22[d22 < 0]
    print(f"  2022 days: {len(d22)}   positive-funding days: {len(pos)} ({len(pos)/len(d22)*100:.1f}%)")
    print(f"  sum of positive-funding contributions: {pos.sum()*100:+.2f}%")
    print(f"  sum of negative-funding contributions: {neg.sum()*100:+.2f}%")
    print(f"  net 2022 gross: {d22.sum()*100:+.2f}%")
    print(f"  mean daily 2022: {d22.mean()*1e4:.3f} bps")

    # ---- 2021/2023 bull-funding check: how concentrated is the lifetime return? ----
    print("\n=== RETURN CONCENTRATION (gross simple, by year share of lifetime) ===")
    life = daily_port.sum()
    for yr, grp in daily_port.groupby(daily_port.index.year):
        share = grp.sum() / life * 100
        print(f"  {yr}: contributes {grp.sum()*100:+6.2f}% = {share:5.1f}% of lifetime {life*100:.1f}%")

    # ---- Sharpe plausibility: autocorrelation of daily funding ----
    print("\n=== SHARPE PLAUSIBILITY DIAGNOSTICS ===")
    ac1 = daily_port.autocorr(1)
    ac5 = daily_port.autocorr(5)
    print(f"  daily funding autocorr lag1: {ac1:.3f}  lag5: {ac5:.3f}")
    print("  (high positive autocorr => funding is a smooth near-constant yield =>")
    print("   naive iid-sqrt(365) Sharpe is INFLATED; effective N is much smaller)")
    # Newey-West style: effective sample size with AR(1)
    if -1 < ac1 < 1:
        n_eff_factor = (1 - ac1) / (1 + ac1)
        sharpe_adj = sharpe * np.sqrt(n_eff_factor)
        print(f"  AR(1)-adjusted Sharpe (variance ratio shrink): ~{sharpe_adj:.2f}")

    # worst single-day funding observed across book
    worst = fund_df.min().min()
    worst_coin = fund_df.min().idxmin()
    print(f"  worst single-day funding observed: {worst*100:.2f}% ({worst_coin})")

    # ---- SURVIVORSHIP / SELECTION ----
    print("\n=== SELECTION / SURVIVORSHIP NOTES ===")
    print("  Coins were CHOSEN ex-post (all survived to 2026). No FTT/LUNA/UST-style")
    print("  delisted perp in the basket => the realized funding stream omits exactly the")
    print("  blow-up coins whose negative-funding/liquidation tail is the carry's true risk.")
    for c in COINS:
        print(f"    {c:5s} perp_listed={listing[c+'USDT']['perp_listed']}")


if __name__ == "__main__":
    main()
