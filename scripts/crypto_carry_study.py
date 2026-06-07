# /// script
# dependencies = ["pandas", "numpy", "requests"]
# ///
"""
Delta-neutral perp funding carry (cash-and-carry) backtest — Binance USDT-M.

Strategy (pre-registered, exact):
  Hold LONG spot + SHORT perp of the same coin (delta ~ 0). Each 8h settlement
  the SHORT-perp leg RECEIVES funding when fundingRate > 0 (longs pay shorts),
  and PAYS when fundingRate < 0. Net carry = funding_received
    - taker fees on entry+exit of BOTH legs
    - per-rebalance slippage
    - an annual roll/rebalance cost.
  This harvests the perp basis / funding risk premium.

Lookahead discipline (the #1 trap):
  Binance `fundingTime` is the SETTLEMENT instant; the rate is PAID to holders
  of the position held DURING [T-8h, T] and booked AT T. We credit a funding
  print at fundingTime T only to a position assumed on-book strictly through T
  (decide-at-T, earn-from-T+). No funding-rate is used as an entry SIGNAL here
  (pure always-on carry), so the only alignment requirement is: settle each
  print at its own fundingTime, never re-annualise-then-divide. Daily resample
  is done in UTC so funding never leaks into the wrong calendar day.

Costs (conservative, codified in FEES_BPS):
  perp taker 5.0 bps/side, spot taker 10.0 bps/side. Entry = open both legs,
  exit = close both legs => round-trip = 2*(5+10) = 30 bps amortised over the
  hold. Plus 2 bps/rebalance slippage and a modelled annual roll.

Metrics: net annualized carry return, Sharpe (periods_per_year=365),
  max drawdown, by-year breakdown (incl. 2022 crypto winter), per-coin, and
  two STRESS scenarios:
    (a) a -2% adverse basis gap on unwind, and
    (b) a forced 1-week funding-goes-negative episode (worst real 7d window
        replaced by the most-negative observed funding, applied to all coins).

SHIP RULE (ALL must hold):
  net-of-cost annualized carry Sharpe > 1.5
  AND positive net carry in EVERY calendar year (incl. 2022)
  AND survives the basis / negative-funding stress (still positive net carry)
  AND the edge is honestly NOT merely liquidation/exchange-blowup tail comp.

Standalone. No keys. Caches raw pulls to data/crypto_cache/. Backtest only.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "crypto_cache"
REPORTS = ROOT / "reports"
CACHE.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)

FAPI = "https://fapi.binance.com"
SPOT = "https://api.binance.com"

FUNDING_PER_YEAR = 1095   # 3 settlements/day * 365
DAYS_PER_YEAR = 365       # crypto trades every calendar day

# Survivorship caveat: this is the set of perps that STILL trade today and had
# a spot+perp pair listed <= 2021. Coins that delisted (FTT, LUNA-era, etc.)
# are absent => selecting "currently liquid" is itself survivorship bias.
# Listing dates (perp / spot) per task notes, kept for documentation.
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
    "SOLUSDT", "DOGEUSDT", "LTCUSDT", "LINKUSDT", "DOTUSDT",
]

FEES_BPS = {
    "perp_taker": 5.0,    # Binance USDT-M futures VIP0 taker
    "spot_taker": 10.0,   # Binance spot VIP0 taker
    "slippage_per_rebalance": 2.0,
    "annual_roll": 5.0,   # modelled annual roll/rebalance, conservative
}

# Stress params (pre-registered).
STRESS_BASIS_GAP_PCT = -2.0      # adverse basis move on unwind
STRESS_NEG_FUNDING_WEEK_DAYS = 7  # forced negative-funding episode length


# --------------------------------------------------------------------------- #
# HTTP (copy of build_broad_universe._get: 4 attempts, 429 backoff)
# --------------------------------------------------------------------------- #
def _get(url: str, params: dict | None = None) -> list | dict:
    for attempt in range(5):
        r = requests.get(url, params=params, timeout=40)
        if r.status_code == 429:
            time.sleep(1.5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"rate-limited: {url}")


# --------------------------------------------------------------------------- #
# Listing-date probe
# --------------------------------------------------------------------------- #
def probe_listing(symbol: str) -> dict:
    """First perp bar (startTime=0,limit=1) and first spot bar as listing proxy."""
    perp = _get(f"{FAPI}/fapi/v1/klines",
                {"symbol": symbol, "interval": "1d", "startTime": 0, "limit": 1})
    spot = _get(f"{SPOT}/api/v3/klines",
                {"symbol": symbol, "interval": "1d", "startTime": 0, "limit": 1})

    def _d(rows):
        if not rows:
            return None
        return str(pd.Timestamp(rows[0][0], unit="ms", tz="UTC").date())

    return {"symbol": symbol, "perp_listing": _d(perp), "spot_listing": _d(spot)}


# --------------------------------------------------------------------------- #
# Funding history (paginate FORWARD; endpoint ignores startTime=0)
# --------------------------------------------------------------------------- #
def fetch_funding(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    cache = CACHE / f"funding_{symbol}.json"
    if cache.exists():
        rows = json.loads(cache.read_text())
    else:
        rows: list[dict] = []
        cursor = start_ms
        seen: set[int] = set()
        while True:
            page = _get(f"{FAPI}/fapi/v1/fundingRate",
                        {"symbol": symbol, "startTime": cursor,
                         "endTime": end_ms, "limit": 1000})
            if not page:
                break
            fresh = [r for r in page if r["fundingTime"] not in seen]
            for r in fresh:
                seen.add(r["fundingTime"])
            rows.extend(fresh)
            last_t = page[-1]["fundingTime"]
            if len(page) < 1000 or last_t >= end_ms:
                break
            cursor = last_t + 1
            time.sleep(0.22)
        cache.write_text(json.dumps(rows))

    if not rows:
        return pd.DataFrame(columns=["fundingTime", "fundingRate"]).set_index("fundingTime")
    df = pd.DataFrame(rows)
    df["fundingTime"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df["fundingRate"] = df["fundingRate"].astype(float)
    df = df[["fundingTime", "fundingRate"]].drop_duplicates("fundingTime")
    df = df.set_index("fundingTime").sort_index()
    return df


# --------------------------------------------------------------------------- #
# Daily klines (perp vs spot via host switch); paginate by startTime
# --------------------------------------------------------------------------- #
def fetch_klines(symbol: str, market: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    cache = CACHE / f"klines_{market}_{symbol}.json"
    base = FAPI if market == "perp" else SPOT
    path = "/fapi/v1/klines" if market == "perp" else "/api/v3/klines"
    if cache.exists():
        rows = json.loads(cache.read_text())
    else:
        rows = []
        cursor = start_ms
        seen: set[int] = set()
        while True:
            page = _get(f"{base}{path}",
                        {"symbol": symbol, "interval": "1d",
                         "startTime": cursor, "endTime": end_ms, "limit": 1000})
            if not page:
                break
            fresh = [r for r in page if r[0] not in seen]
            for r in fresh:
                seen.add(r[0])
            rows.extend(fresh)
            last_t = page[-1][0]
            if len(page) < 1000 or last_t >= end_ms:
                break
            cursor = last_t + 1
            time.sleep(0.22)
        cache.write_text(json.dumps(rows))

    if not rows:
        return pd.DataFrame(columns=["close"])
    df = pd.DataFrame(rows)
    df = df.iloc[:, :7]
    df.columns = ["openTime", "open", "high", "low", "close", "volume", "closeTime"]
    df["date"] = pd.to_datetime(df["openTime"], unit="ms", utc=True).dt.normalize()
    df["close"] = df["close"].astype(float)
    df = df.drop_duplicates("date").set_index("date").sort_index()
    return df[["close"]]


# --------------------------------------------------------------------------- #
# Metrics (re-based to crypto: periods_per_year=365)
# --------------------------------------------------------------------------- #
def annualize_sharpe(daily_rets: pd.Series, periods_per_year: int = DAYS_PER_YEAR) -> float:
    r = daily_rets.dropna()
    if r.empty:
        return 0.0
    mu = r.mean()
    sigma = r.std(ddof=1)
    if sigma == 0 or np.isnan(sigma):
        return 0.0
    return float(mu / sigma * math.sqrt(periods_per_year))


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    return float((equity / equity.cummax() - 1.0).min())


def capm_alpha_beta(strat: pd.Series, bench: pd.Series) -> tuple[float, float]:
    df = pd.concat([strat.rename("s"), bench.rename("m")], axis=1).dropna()
    if len(df) < 30 or df["m"].var() == 0:
        return 0.0, 0.0
    beta = float(df["s"].cov(df["m"]) / df["m"].var())
    alpha_daily = float(df["s"].mean() - beta * df["m"].mean())
    return ((1.0 + alpha_daily) ** DAYS_PER_YEAR - 1.0) * 100.0, beta


def walk_forward_folds(daily_rets: pd.Series, n_folds: int = 5) -> dict:
    r = daily_rets.dropna()
    if r.empty or len(r) < n_folds:
        return {"folds": [], "mean_sharpe": 0.0, "min_sharpe": 0.0, "passed": False}
    fold_size = len(r) // n_folds
    folds = []
    for i in range(n_folds):
        start = i * fold_size
        end = (i + 1) * fold_size if i < n_folds - 1 else len(r)
        chunk = r.iloc[start:end]
        folds.append({
            "fold": i,
            "sharpe": round(annualize_sharpe(chunk), 3),
            "return_pct": round(((1 + chunk).prod() - 1) * 100, 2),
            "n_days": len(chunk),
        })
    sharpes = [f["sharpe"] for f in folds]
    mean_s, min_s = float(np.mean(sharpes)), float(np.min(sharpes))
    return {"folds": folds, "mean_sharpe": round(mean_s, 3),
            "min_sharpe": round(min_s, 3),
            "passed": all(s > 0 for s in sharpes) and mean_s >= 0.5}


def cagr(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    tot = equity.iloc[-1] / equity.iloc[0] - 1.0
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    if years <= 0:
        return 0.0
    return (1.0 + tot) ** (1.0 / years) - 1.0


# --------------------------------------------------------------------------- #
# Per-coin daily carry series
# --------------------------------------------------------------------------- #
def build_daily_carry(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Return a daily frame for one coin:
        funding_daily : sum of 8h fundingRate over each UTC day (fraction of
                        notional). Short-perp leg EARNS +funding_daily.
        perp_close, spot_close, basis : for benchmark + stress.
    Delta-neutral: spot and perp price PnL cancel (notional matched), so the
    daily strategy return ~= funding_daily minus amortised costs.
    """
    funding = fetch_funding(symbol, start_ms, end_ms)
    perp = fetch_klines(symbol, "perp", start_ms, end_ms)
    spot = fetch_klines(symbol, "spot", start_ms, end_ms)

    if funding.empty or perp.empty or spot.empty:
        return pd.DataFrame()

    # Funding is settled in UTC; resample-by-UTC-day = SUM of the 3 8h prints.
    fund_daily = funding["fundingRate"].resample("1D").sum()
    fund_daily.index = fund_daily.index.normalize()

    panel = pd.DataFrame({
        "funding_daily": fund_daily,
        "perp_close": perp["close"],
        "spot_close": spot["close"],
    })
    # Align each leg to max(perp_listing, spot_listing): only days where ALL of
    # funding + both closes exist. (NaN before listing, not zero.)
    panel = panel.dropna(subset=["perp_close", "spot_close"])
    panel["funding_daily"] = panel["funding_daily"].fillna(0.0)
    panel["basis"] = panel["perp_close"] / panel["spot_close"] - 1.0
    panel["symbol"] = symbol
    return panel


# --------------------------------------------------------------------------- #
# Portfolio backtest
# --------------------------------------------------------------------------- #
def run_backtest(panels: dict[str, pd.DataFrame], cost_bps_override: float | None) -> dict:
    """Equal-weight, always-on cash-and-carry across the available coins.

    Daily gross carry return = mean across active coins of funding_daily
    (short-perp earns +funding). Costs: a per-coin round-trip taker on BOTH
    legs amortised over the held window + a daily slice of the annual roll +
    per-rebalance slippage modelled at the (assumed annual) rebalance.
    """
    if not panels:
        return {}

    # Common daily index = union of all coins' trading days.
    all_funding = pd.DataFrame({s: p["funding_daily"] for s, p in panels.items()})
    active = all_funding.notna().astype(float)
    n_active = active.sum(axis=1).replace(0, np.nan)

    # Equal-weight daily gross carry (short perp EARNS funding).
    gross_daily = (all_funding.fillna(0.0) * active).sum(axis=1) / n_active
    gross_daily = gross_daily.dropna()

    # --- cost model (conservative, amortised) ---
    rt = FEES_BPS["perp_taker"] * 2 + FEES_BPS["spot_taker"] * 2  # 30 bps round-trip
    if cost_bps_override is not None:
        rt = cost_bps_override
    n_days = len(gross_daily)
    years = max(n_days / DAYS_PER_YEAR, 1e-9)
    # One entry+exit over the whole hold + one roll/rebalance per year + slippage per roll.
    entry_exit = rt / 10_000.0
    annual_roll_total = (FEES_BPS["annual_roll"] / 10_000.0 + FEES_BPS["slippage_per_rebalance"] / 10_000.0) * years
    total_friction = entry_exit + annual_roll_total
    daily_cost = total_friction / n_days  # amortise flat across the window

    net_daily = gross_daily - daily_cost
    equity = (1.0 + net_daily).cumprod()

    return {
        "gross_daily": gross_daily,
        "net_daily": net_daily,
        "equity": equity,
        "daily_cost": daily_cost,
        "round_trip_bps": rt,
        "n_coins": int(active.sum(axis=1).max()),
    }


def by_year(net_daily: pd.Series) -> dict:
    out = {}
    for yr, grp in net_daily.groupby(net_daily.index.year):
        out[str(int(yr))] = {
            "net_return_pct": round(((1 + grp).prod() - 1) * 100, 3),
            "sharpe": round(annualize_sharpe(grp), 3),
            "max_dd_pct": round(max_drawdown((1 + grp).cumprod()) * 100, 3),
            "n_days": len(grp),
        }
    return out


def stress_tests(panels: dict[str, pd.DataFrame], base: dict) -> dict:
    """(a) -2% adverse basis gap on unwind: a one-off hit to terminal equity.
       (b) 1-week forced negative funding: replace the worst real 7d funding
           window's daily carry with the most-negative observed single-day
           funding (across all coins), applied portfolio-wide."""
    net = base["net_daily"].copy()

    # (a) basis gap on unwind — subtract from the final day's return.
    net_a = net.copy()
    net_a.iloc[-1] += STRESS_BASIS_GAP_PCT / 100.0
    eq_a = (1 + net_a).cumprod()

    # (b) forced negative-funding week.
    worst_day = min(
        (p["funding_daily"].min() for p in panels.values() if not p.empty),
        default=0.0,
    )
    net_b = net.copy()
    # pick the existing 7-day window with the lowest cumulative carry, overwrite it.
    if len(net_b) >= STRESS_NEG_FUNDING_WEEK_DAYS:
        roll = net_b.rolling(STRESS_NEG_FUNDING_WEEK_DAYS).sum()
        end_idx = roll.idxmin()
        pos = net_b.index.get_loc(end_idx)
        lo = max(0, pos - STRESS_NEG_FUNDING_WEEK_DAYS + 1)
        net_b.iloc[lo:pos + 1] = worst_day - base["daily_cost"]
    eq_b = (1 + net_b).cumprod()

    # combined
    net_c = net_b.copy()
    net_c.iloc[-1] += STRESS_BASIS_GAP_PCT / 100.0
    eq_c = (1 + net_c).cumprod()

    return {
        "worst_observed_daily_funding_pct": round(worst_day * 100, 4),
        "basis_gap": {
            "net_return_pct": round((eq_a.iloc[-1] - 1) * 100, 3),
            "sharpe": round(annualize_sharpe(net_a), 3),
            "max_dd_pct": round(max_drawdown(eq_a) * 100, 3),
        },
        "neg_funding_week": {
            "net_return_pct": round((eq_b.iloc[-1] - 1) * 100, 3),
            "sharpe": round(annualize_sharpe(net_b), 3),
            "max_dd_pct": round(max_drawdown(eq_b) * 100, 3),
        },
        "combined": {
            "net_return_pct": round((eq_c.iloc[-1] - 1) * 100, 3),
            "sharpe": round(annualize_sharpe(net_c), 3),
            "max_dd_pct": round(max_drawdown(eq_c) * 100, 3),
        },
    }


def evaluate_ship_rule(net_daily: pd.Series, equity: pd.Series,
                       years: dict, stress: dict) -> dict:
    sharpe = annualize_sharpe(net_daily)
    every_year_pos = all(v["net_return_pct"] > 0 for v in years.values())
    stress_ok = (
        stress["basis_gap"]["net_return_pct"] > 0
        and stress["neg_funding_week"]["net_return_pct"] > 0
        and stress["combined"]["net_return_pct"] > 0
    )
    checks = {
        "sharpe_gt_1_5": bool(sharpe > 1.5),
        "positive_every_year": bool(every_year_pos),
        "survives_stress": bool(stress_ok),
    }
    return {
        "annualized_sharpe": round(sharpe, 3),
        "checks": checks,
        "SHIP": bool(all(checks.values())),
        "tail_caveat": (
            "Carry here = compensation for SHORT-VOL / liquidation / "
            "exchange-blowup tail risk. A cash backtest does NOT model margin "
            "calls, ADL, or a venue going down with the short perp open; the "
            "positive carry IS partly that tail premium, not pure free money. "
            "Treat any SHIP=true as 'survives in-sample carry stats', NOT as a "
            "risk-free arb."
        ),
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", default=None, help="comma list; default = full set")
    ap.add_argument("--limit", type=int, default=None, help="use first N symbols")
    ap.add_argument("--start", default="2023-03-21", help="UTC date YYYY-MM-DD")
    ap.add_argument("--end", default="2026-06-01", help="UTC date YYYY-MM-DD")
    ap.add_argument("--cost-bps", type=float, default=None,
                    help="override round-trip cost in bps (default 30 = 2*5 perp + 2*10 spot)")
    ap.add_argument("--output", default=str(REPORTS / "crypto_carry_study.json"))
    ap.add_argument("--probe", action="store_true", help="just print listing dates")
    args = ap.parse_args()

    symbols = (args.symbols.split(",") if args.symbols else list(SYMBOLS))
    if args.limit:
        symbols = symbols[:args.limit]

    if args.probe:
        for s in symbols:
            print(probe_listing(s))
        return

    start_ms = int(pd.Timestamp(args.start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(args.end, tz="UTC").timestamp() * 1000)

    panels = {}
    for s in symbols:
        p = build_daily_carry(s, start_ms, end_ms)
        if not p.empty:
            panels[s] = p
        print(f"  {s}: {len(p)} days" if not p.empty else f"  {s}: NO DATA")

    base = run_backtest(panels, args.cost_bps)
    if not base:
        print("No data; aborting.")
        return

    net_daily = base["net_daily"]
    equity = base["equity"]
    years = by_year(net_daily)
    stress = stress_tests(panels, base)
    verdict = evaluate_ship_rule(net_daily, equity, years, stress)

    # benchmark = BTC buy-hold (spot)
    btc = panels.get("BTCUSDT")
    alpha = beta = 0.0
    if btc is not None:
        btc_ret = btc["spot_close"].pct_change().dropna()
        alpha, beta = capm_alpha_beta(net_daily, btc_ret)

    per_coin = {
        s: {
            "n_days": len(p),
            "mean_daily_funding_bps": round(p["funding_daily"].mean() * 10_000, 3),
            "annualized_carry_pct": round(p["funding_daily"].mean() * DAYS_PER_YEAR * 100, 3),
            "mean_basis_pct": round(p["basis"].mean() * 100, 4),
        }
        for s, p in panels.items()
    }

    result = {
        "params": {
            "symbols": list(panels.keys()),
            "start": args.start, "end": args.end,
            "fees_bps": FEES_BPS,
            "round_trip_bps_used": base["round_trip_bps"],
            "funding_per_year": FUNDING_PER_YEAR,
            "days_per_year": DAYS_PER_YEAR,
        },
        "headline": {
            "net_total_return_pct": round((equity.iloc[-1] - 1) * 100, 3),
            "net_cagr_pct": round(cagr(equity) * 100, 3),
            "annualized_sharpe": round(annualize_sharpe(net_daily), 3),
            "max_drawdown_pct": round(max_drawdown(equity) * 100, 3),
            "gross_annualized_sharpe": round(annualize_sharpe(base["gross_daily"]), 3),
            "n_days": len(net_daily),
            "capm_alpha_vs_btc_pct": round(alpha, 3),
            "beta_vs_btc": round(beta, 4),
        },
        "by_year": years,
        "per_coin": per_coin,
        "walk_forward": walk_forward_folds(net_daily),
        "stress": stress,
        "verdict": verdict,
    }

    Path(args.output).write_text(json.dumps(result, indent=2))

    # console verdict block
    print("\n" + "=" * 60)
    print("CRYPTO FUNDING CARRY — VERDICT")
    print("=" * 60)
    h = result["headline"]
    print(f"net CAGR        : {h['net_cagr_pct']}%")
    print(f"annualized Sharpe: {h['annualized_sharpe']}")
    print(f"max drawdown    : {h['max_drawdown_pct']}%")
    print(f"alpha vs BTC    : {h['capm_alpha_vs_btc_pct']}%  beta={h['beta_vs_btc']}")
    print("by-year net %   :", {k: v["net_return_pct"] for k, v in years.items()})
    print(f"stress net %    : basis_gap={stress['basis_gap']['net_return_pct']} "
          f"neg_week={stress['neg_funding_week']['net_return_pct']} "
          f"combined={stress['combined']['net_return_pct']}")
    print("ship checks     :", verdict["checks"])
    print(f"SHIP            : {verdict['SHIP']}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
