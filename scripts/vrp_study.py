#!/usr/bin/env python
"""Variance Risk Premium (VRP) study — short-variance harvest, VIX + SPY only.

Standalone. Modifies no tracked files. BACKTEST ONLY.

Two parts, both pre-registered:

  (A) PREMIUM-EXISTENCE TEST
      VRP_t = (VIX(t0)/100)^2 - subsequent 21-td annualized realized SPY variance.
      The implied leg (VIX at month start) is set BEFORE the realized window it is
      compared to (no look-ahead). Reports mean/median VRP, %-positive months, in
      both variance and vol units.

  (B) HARVEST BACKTEST
      Monthly-rolled SHORT-VARIANCE position. Each month we "sell" a 1-month variance
      swap struck at K = (VIX(t0)/100)^2 (annualized variance). Seller payoff:
          payoff_var = K - rv_ann            (positive when implied richer than realized)
      Expressed as a unit-free per-variance-notional return then VOL-TARGET sized so the
      series is comparable across regimes, net of a conservative friction (1 vega-pt /
      roll, converted to variance terms). Captures BOTH the premium and the tail
      (Mar-2020 rv_ann >> K = catastrophic loss).

PRE-REGISTERED CONSTRUCTION
  - NON-OVERLAPPING 21-td buckets anchored on month-start trading days (~120 / 10y).
  - Implied set at t0 (VIX close, known); realized uses SPY log-returns t0+1..t0+21
    (strictly forward). Payoff STAMPED at settlement date t0+21, never at t0.
  - Annualized variance on BOTH legs (rv_ann = 252/21 * sum r_d^2, zero-mean swap conv).
  - Conservative cost + vol-target sizing.
  - Worst-5 months surfaced explicitly (Feb-2018 Volmageddon, Mar-2020 COVID, 2022...).
  - Sharpe annualized ppy=12 AND AR(1)-variance-ratio-shrunk (short-vol carry is
    autocorrelated + the IID Sharpe is upper-biased; tail is undersampled).

SHIP RULE (all must hold):
  1. VRP robustly positive: >0 in >=60% of months AND mean clearly >0.
  2. A TAIL-SIZED harvest (sized so worst single month is survivable, not ruin) has
     AR(1)-corrected net Sharpe > 1.0.
  3. Net-positive in MOST calendar years.
  4. Worst month / max DD bounded enough to size as a portfolio leg (no -80% ruin).

Usage:
    uv run python scripts/vrp_study.py --start 2016-06-01 --end 2026-06-01
    uv run python scripts/vrp_study.py --vol-target 0.10 --output reports/vrp_study.json
    uv run python scripts/vrp_study.py --smoke      # synthetic tiny self-test, no fetch
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "vol_cache"
TD_PER_MONTH = 21
TD_PER_YEAR = 252
MONTHS_PER_YEAR = 12

# Stress months we MUST surface no matter what (short-vol's defining risk).
WATCH_MONTHS = ["2018-02", "2020-02", "2020-03", "2022", "2024-08", "2025-04"]


# --------------------------------------------------------------------------- #
# Metrics — local copies (task forbids modifying tracked files; per-script
# copies are the repo convention). Math mirrors crypto_carry_study.py:204-218
# and the AR(1) variance-ratio shrink at sanity_check_crypto_carry.py:144-147.
# --------------------------------------------------------------------------- #
def ann_sharpe(rets: pd.Series, periods_per_year: int = MONTHS_PER_YEAR) -> float:
    r = rets.dropna()
    if r.empty:
        return 0.0
    mu = r.mean()
    sigma = r.std(ddof=1)
    if sigma == 0 or np.isnan(sigma):
        return 0.0
    return float(mu / sigma * math.sqrt(periods_per_year))


def ar1_adjusted_sharpe(rets: pd.Series, periods_per_year: int = MONTHS_PER_YEAR) -> tuple[float, float, float]:
    """Returns (raw_sharpe, ar1, adj_sharpe). Variance-ratio shrink: S*sqrt((1-a)/(1+a))."""
    r = rets.dropna()
    raw = ann_sharpe(r, periods_per_year)
    if len(r) < 3:
        return raw, 0.0, raw
    ac1 = r.autocorr(1)
    if ac1 is None or np.isnan(ac1) or not (-1 < ac1 < 1):
        return raw, float(ac1) if ac1 is not None and not np.isnan(ac1) else 0.0, raw
    adj = raw * math.sqrt((1 - ac1) / (1 + ac1))
    return raw, float(ac1), float(adj)


def sharpe_se(sharpe: float, n: int) -> float:
    """Approx SE of an (annualized) Sharpe estimate: sqrt((1 + 0.5 S^2)/n)."""
    if n <= 1:
        return float("nan")
    return math.sqrt((1.0 + 0.5 * sharpe * sharpe) / n)


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    return float((equity / equity.cummax() - 1.0).min())


def stats_block(s: pd.Series) -> dict:
    s = s.dropna()
    if s.empty:
        return {"n": 0}
    return {
        "n": int(len(s)),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "std": float(s.std(ddof=1)) if len(s) > 1 else 0.0,
        "min": float(s.min()),
        "max": float(s.max()),
        "pct_positive": float((s > 0).mean() * 100.0),
    }


# --------------------------------------------------------------------------- #
# Data — cached parquet under data/vol_cache/
# --------------------------------------------------------------------------- #
def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    idx = pd.to_datetime(df.index)
    if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    return df[~df.index.duplicated(keep="last")].sort_index()


def fetch_vix(refresh: bool = False) -> pd.Series:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / "vix_daily.parquet"
    if cache.exists() and not refresh:
        v = pd.read_parquet(cache)
    else:
        import yfinance as yf

        h = yf.Ticker("^VIX").history(period="max")
        if h is None or h.empty:
            raise SystemExit("VIX fetch failed (yfinance ^VIX).")
        h = _normalize(h)
        v = h[["Close"]].rename(columns={"Close": "vix"})
        v.to_parquet(cache)
    s = v["vix"] if "vix" in v.columns else v.iloc[:, 0]
    return _normalize(s.to_frame("vix"))["vix"]


def fetch_spy(refresh: bool = False) -> pd.Series:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / "spy_daily.parquet"
    if cache.exists() and not refresh:
        s = pd.read_parquet(cache)
    else:
        from src.config_loader import Config  # type: ignore
        from src.data.fetcher_factory import get_data_fetcher  # type: ignore

        fetcher = get_data_fetcher(Config(), cache=None)
        raw = fetcher.fetch_price_data("SPY", period="10y", interval="1d", adjusted=True)
        if raw is None or raw.empty:
            raise SystemExit("SPY fetch failed (project fetcher).")
        s = _normalize(raw)[["Close"]].rename(columns={"Close": "spy"})
        s.to_parquet(cache)
    col = "spy" if "spy" in s.columns else s.columns[0]
    return _normalize(s[[col]].rename(columns={col: "spy"}))["spy"]


# --------------------------------------------------------------------------- #
# Core: non-overlapping monthly buckets, lookahead-safe
# --------------------------------------------------------------------------- #
def build_buckets(spy: pd.Series, vix: pd.Series, anchor_offset: int = 0) -> pd.DataFrame:
    """Non-overlapping 21-td buckets. Row per settled bucket.

    t0 = bucket start (implied set here, VIX close known at t0).
    realized window = SPY log-returns over the 21 td AFTER t0 (t0+1..t0+21).
    settle = t0+21. Payoff is STAMPED at settle (never at t0).
    """
    join = pd.concat([spy.rename("spy"), vix.rename("vix")], axis=1).dropna()
    join = join.sort_index()
    dates = join.index
    n = len(dates)
    if n < TD_PER_MONTH + 2:
        return pd.DataFrame()

    log_ret = np.log(join["spy"]).diff()  # r_d at position i = ln(spy_i/spy_{i-1})

    rows = []
    i = anchor_offset
    while i + TD_PER_MONTH < n:
        t0 = dates[i]
        settle = dates[i + TD_PER_MONTH]
        vix_t0 = float(join["vix"].iloc[i])
        # implied annualized variance (strike)
        sigma_impl = vix_t0 / 100.0
        K_var_ann = sigma_impl ** 2
        # realized: returns strictly AFTER t0 -> positions i+1 .. i+TD_PER_MONTH
        fwd = log_ret.iloc[i + 1 : i + 1 + TD_PER_MONTH]
        if len(fwd) < TD_PER_MONTH or fwd.isna().any():
            i += TD_PER_MONTH
            continue
        rv_ann = (TD_PER_YEAR / TD_PER_MONTH) * float((fwd ** 2).sum())  # zero-mean swap conv
        sigma_real = math.sqrt(rv_ann)
        rows.append({
            "t0": t0,
            "settle": settle,
            "vix": vix_t0,
            "sigma_impl": sigma_impl,
            "sigma_real": sigma_real,
            "K_var_ann": K_var_ann,
            "rv_ann": rv_ann,
            "vrp_var": K_var_ann - rv_ann,       # variance-units VRP
            "vrp_vol": sigma_impl - sigma_real,  # vol-units VRP (points/100)
        })
        i += TD_PER_MONTH  # non-overlapping

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.set_index("settle").sort_index()  # stamp at settlement
    return df


def harvest_returns(df: pd.DataFrame, vol_target: float, cost_vega_pts: float) -> pd.DataFrame:
    """Short-variance seller monthly returns, vol-target sized, net of friction.

    Per-unit-variance-notional raw payoff = (K - rv) / K   (seller collects K, pays rv).
    Friction: a conservative `cost_vega_pts` vega-points per roll. 1 vega-pt ~ a 1 vol-pt
    move in implied; convert to variance terms at the strike: d(var)=2*sigma*d(sigma),
    so cost_var = 2*sigma_impl*(cost_vega_pts/100). As a per-notional return: /K.
    Then scale the whole series so its full-sample monthly vol == vol_target/sqrt(12)
    (a fixed-vol-target leg, comparable across regimes). Sizing uses FULL-SAMPLE std —
    flagged as mild in-sample sizing (acceptable for a survivability study; we do NOT
    size off in-sample DD, per the gotchas).
    """
    out = df.copy()
    K = out["K_var_ann"].clip(lower=1e-8)
    raw_ret = (out["K_var_ann"] - out["rv_ann"]) / K          # gross per-notional
    cost_var = 2.0 * out["sigma_impl"] * (cost_vega_pts / 100.0)
    cost_ret = cost_var / K
    net_ret = raw_ret - cost_ret                              # short-vol is a SELL: cost always drags

    out["gross_ret"] = raw_ret
    out["cost_ret"] = cost_ret
    out["unit_net_ret"] = net_ret

    monthly_vol = net_ret.std(ddof=1)
    target_monthly_vol = vol_target / math.sqrt(MONTHS_PER_YEAR)
    scale = (target_monthly_vol / monthly_vol) if (monthly_vol and not np.isnan(monthly_vol) and monthly_vol > 0) else 1.0
    out["scale"] = scale
    out["net_ret"] = net_ret * scale
    return out


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def by_year(net_ret: pd.Series) -> dict:
    res = {}
    for yr, grp in net_ret.groupby(net_ret.index.year):
        eq = (1 + grp).cumprod()
        res[str(int(yr))] = {
            "ret_pct": round(((1 + grp).prod() - 1) * 100, 2),
            "n_months": int(len(grp)),
            "dd_pct": round(max_drawdown(eq) * 100, 2),
            "negative": bool(((1 + grp).prod() - 1) < 0),
        }
    return res


def worst_months(out: pd.DataFrame, k: int = 5) -> list[dict]:
    w = out.sort_values("net_ret").head(k)
    return [
        {
            "settle": ts.strftime("%Y-%m-%d"),
            "t0": row["t0"].strftime("%Y-%m-%d"),
            "vix_at_t0": round(float(row["vix"]), 2),
            "sigma_impl": round(float(row["sigma_impl"]), 4),
            "sigma_real": round(float(row["sigma_real"]), 4),
            "vrp_var": round(float(row["vrp_var"]), 5),
            "net_ret_pct": round(float(row["net_ret"]) * 100, 2),
        }
        for ts, row in w.iterrows()
    ]


def watch_month_table(out: pd.DataFrame) -> dict:
    res = {}
    for tag in WATCH_MONTHS:
        if len(tag) == 4:  # whole year
            mask = out.index.year == int(tag)
        else:
            y, m = tag.split("-")
            mask = (out.index.year == int(y)) & (out.index.month == int(m))
        grp = out[mask]
        if grp.empty:
            res[tag] = {"present": False}
            continue
        res[tag] = {
            "present": True,
            "n": int(len(grp)),
            "net_ret_pct": round(float((1 + grp["net_ret"]).prod() - 1) * 100, 2),
            "worst_month_pct": round(float(grp["net_ret"].min()) * 100, 2),
            "max_vix": round(float(grp["vix"].max()), 2),
            "max_rv_ann": round(float(grp["rv_ann"].max()), 4),
        }
    return res


def run(spy: pd.Series, vix: pd.Series, start: str | None, end: str | None,
        vol_target: float, cost_vega_pts: float) -> dict:
    if start:
        spy = spy[spy.index >= pd.Timestamp(start)]
        vix = vix[vix.index >= pd.Timestamp(start)]
    if end:
        spy = spy[spy.index <= pd.Timestamp(end)]
        vix = vix[vix.index <= pd.Timestamp(end)]

    df = build_buckets(spy, vix, anchor_offset=0)
    if df.empty:
        raise SystemExit("Not enough overlapping SPY+VIX data to build any monthly bucket.")

    # ---- PART A: premium existence ----
    vrp_var_stats = stats_block(df["vrp_var"])
    vrp_vol_stats = stats_block(df["vrp_vol"])

    # ---- PART B: harvest ----
    out = harvest_returns(df, vol_target=vol_target, cost_vega_pts=cost_vega_pts)
    net = out["net_ret"]
    eq = (1 + net).cumprod()
    raw_s, ac1, adj_s = ar1_adjusted_sharpe(net, MONTHS_PER_YEAR)
    se = sharpe_se(raw_s, len(net))

    yr = by_year(net)
    yrs_total = len(yr)
    yrs_neg = sum(1 for v in yr.values() if v["negative"])
    yrs_positive = yrs_total - yrs_neg

    worst5 = worst_months(out, 5)

    # ---- SHIP RULE ----
    vrp_robust = (vrp_var_stats.get("pct_positive", 0) >= 60.0) and (vrp_var_stats.get("mean", 0) > 0)
    sharpe_ok = adj_s > 1.0
    years_ok = yrs_positive >= math.ceil(yrs_total / 2) and yrs_positive > yrs_neg  # "most" years
    worst_month_pct = float(net.min()) * 100
    mdd_pct = max_drawdown(eq) * 100
    # "no -80% ruin at chosen size": worst month and max DD both survivable as a leg
    no_ruin = (worst_month_pct > -50.0) and (mdd_pct > -50.0)

    ship = bool(vrp_robust and sharpe_ok and years_ok and no_ruin)

    overlap = (df["t0"].min().strftime("%Y-%m-%d"), df.index.max().strftime("%Y-%m-%d"))

    return {
        "window": {"start": overlap[0], "end": overlap[1], "n_months": int(len(df))},
        "params": {"vol_target": vol_target, "cost_vega_pts": cost_vega_pts,
                   "td_per_month": TD_PER_MONTH, "non_overlapping": True},
        "partA_premium_existence": {
            "vrp_variance_units": vrp_var_stats,
            "vrp_vol_units_decimal": vrp_vol_stats,
            "interpretation": "vrp_var = (VIX/100)^2 - forward 21td annualized realized variance",
        },
        "partB_harvest": {
            "ann_sharpe_iid": round(raw_s, 3),
            "ar1": round(ac1, 3),
            "ann_sharpe_ar1_adj": round(adj_s, 3),
            "sharpe_se_approx": round(se, 3) if not np.isnan(se) else None,
            "total_ret_pct": round((eq.iloc[-1] - 1) * 100, 2),
            "max_dd_pct": round(mdd_pct, 2),
            "worst_month_pct": round(worst_month_pct, 2),
            "best_month_pct": round(float(net.max()) * 100, 2),
            "mean_monthly_net_pct": round(float(net.mean()) * 100, 4),
            "pct_positive_months": round(float((net > 0).mean() * 100), 1),
            "scale_applied": round(float(out["scale"].iloc[0]), 4),
        },
        "by_year": yr,
        "worst_5_months": worst5,
        "stress_windows": watch_month_table(out),
        "ship_rule": {
            "1_vrp_robustly_positive": bool(vrp_robust),
            "2_ar1_sharpe_gt_1": bool(sharpe_ok),
            "3_most_years_positive": bool(years_ok),
            "4_no_ruin_survivable_tail": bool(no_ruin),
            "years_positive": yrs_positive,
            "years_negative": yrs_neg,
            "PASS": ship,
        },
        "verdict": _verdict(ship, vrp_robust, sharpe_ok, years_ok, no_ruin,
                            worst_month_pct, mdd_pct, adj_s, vrp_var_stats),
    }


def _verdict(ship, vrp_robust, sharpe_ok, years_ok, no_ruin,
             worst_month_pct, mdd_pct, adj_s, vrp_stats) -> str:
    if ship:
        return (f"SHIP. VRP positive in {vrp_stats.get('pct_positive', 0):.0f}% of months "
                f"(mean {vrp_stats.get('mean', 0):+.4f} var-units); AR(1)-adj Sharpe {adj_s:.2f}>1; "
                f"most years positive; worst month {worst_month_pct:.1f}% / max DD {mdd_pct:.1f}% "
                f"survivable as a sized leg. Residual return = fair pay for a survivable tail — "
                f"BUT n~120 with one true blow-up means the left tail is undersampled; size below "
                f"in-sample DD.")
    fails = []
    if not vrp_robust:
        fails.append("VRP not robustly positive (<60% months or mean<=0)")
    if not sharpe_ok:
        fails.append(f"AR(1)-adj Sharpe {adj_s:.2f} <= 1.0")
    if not years_ok:
        fails.append("not net-positive in most calendar years")
    if not no_ruin:
        fails.append(f"tail not survivable (worst month {worst_month_pct:.1f}% / DD {mdd_pct:.1f}%) = ruin risk")
    return "NO-SHIP. Failed: " + "; ".join(fails) + "."


# --------------------------------------------------------------------------- #
# Smoke: synthetic data, proves the pipeline reaches a verdict block (no fetch)
# --------------------------------------------------------------------------- #
def smoke() -> dict:
    rng = np.random.default_rng(7)
    n = 3 * TD_PER_YEAR  # ~3y of trading days
    idx = pd.bdate_range("2017-01-03", periods=n)
    # SPY: drifting GBM with one COVID-like vol blow-up window
    daily_vol = np.full(n, 0.008)
    daily_vol[400:430] = 0.06  # blow-up: realized >> implied -> seller catastrophic month
    rets = rng.normal(0.0003, 1.0, n) * daily_vol
    spy = pd.Series(100 * np.exp(np.cumsum(rets)), index=idx, name="spy")
    # VIX: tracks a smoothed trailing vol but stays BELOW realized in the blow-up (the premium + tail)
    trailing = pd.Series(rets, index=idx).rolling(21).std().bfill() * math.sqrt(TD_PER_YEAR)
    vix = (trailing * 100 * 1.15 + 4.0).clip(lower=9.0)  # implied richer than realized on average
    vix.name = "vix"

    res = run(spy, vix, start=None, end=None, vol_target=0.10, cost_vega_pts=1.0)
    ok = (
        "verdict" in res
        and "ship_rule" in res
        and isinstance(res["ship_rule"]["PASS"], bool)
        and res["window"]["n_months"] > 10
        and any(m["net_ret_pct"] < 0 for m in res["worst_5_months"])  # the blow-up shows up
    )
    return {"smoke_pass": ok, "n_months": res["window"]["n_months"],
            "verdict": res["verdict"][:80], "ship": res["ship_rule"]["PASS"],
            "worst_month_pct": res["partB_harvest"]["worst_month_pct"]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Variance Risk Premium short-vol study (VIX+SPY only).")
    ap.add_argument("--start", default=None, help="window start YYYY-MM-DD (default: full overlap)")
    ap.add_argument("--end", default=None, help="window end YYYY-MM-DD")
    ap.add_argument("--vol-target", type=float, default=0.10, help="annualized vol target for sizing (default 0.10)")
    ap.add_argument("--cost-vega-pts", type=float, default=1.0, help="friction in vega-points per roll (default 1.0)")
    ap.add_argument("--output", default=None, help="write JSON report here")
    ap.add_argument("--refresh", action="store_true", help="bypass parquet cache, re-fetch")
    ap.add_argument("--smoke", action="store_true", help="synthetic self-test, no data fetch")
    args = ap.parse_args()

    if args.smoke:
        out = smoke()
        print(json.dumps(out, indent=2))
        return 0 if out["smoke_pass"] else 1

    vix = fetch_vix(refresh=args.refresh)
    spy = fetch_spy(refresh=args.refresh)
    res = run(spy, vix, args.start, args.end, args.vol_target, args.cost_vega_pts)

    print(json.dumps(res, indent=2, default=str))
    print("\n" + "=" * 70)
    print(res["verdict"])
    print("=" * 70)

    if args.output:
        outp = Path(args.output)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(res, indent=2, default=str))
        print(f"\nwrote {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
