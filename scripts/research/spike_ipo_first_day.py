# /// script
# dependencies = ["yfinance", "pandas", "numpy", "openpyxl", "scipy", "requests"]
# ///
"""
Spike: is there a *tradeable* edge in IPO first-day open->close returns?

Phase 0 kill gate (see project memory / IPO discussion):
  - Labels source: Jay Ritter's IPO-age.xlsx (firm-level calendar + VC/tech/
    dual-class/size/founding-year features). NO offer price -> we measure the
    OPEN->CLOSE return (what a non-allocated retail trader can actually capture),
    NOT offer->close (which needs an IPO allocation).
  - Day-1 OHLC from yfinance.
  - Question: does mean open->close clear zero, and does ANY free feature sort
    the cross-section (rank-IC CI excluding 0, monotonic quintiles)?

Honest limitations, measured and reported (not hidden):
  - SURVIVORSHIP BIAS: yfinance drops delisted tickers, so IPOs that later died
    are missing. Inflates results. We report coverage so we know how bad it is.
  - TICKER REUSE: a Ritter ticker may map to a different company on yfinance
    today. Guarded by rejecting symbols already trading before their offer date.
  - No offer-price / range-revision / underwriter-rank features (Phase 1).

Output: reports/ipo_first_day_ic.json + console summary.
Usage:  uv run scripts/research/spike_ipo_first_day.py [START_YEAR] [END_YEAR]
"""
from __future__ import annotations

import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout, as_completed
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "ipo"
DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORTS = ROOT / "reports"
REPORTS.mkdir(exist_ok=True)

RITTER_URL = "https://site.warrington.ufl.edu/ritter/files/IPO-age.xlsx"
RITTER_XLSX = DATA_DIR / "IPO-age.xlsx"
DAY1_CACHE = DATA_DIR / "day1_ohlc_cache.json"
UA = {"User-Agent": "Mozilla/5.0 (IPO research; erand1998@gmail.com)"}

START_YEAR = int(sys.argv[1]) if len(sys.argv) > 1 else 2019
END_YEAR = int(sys.argv[2]) if len(sys.argv) > 2 else 2024
MIN_COHORT = 10        # min IPOs in a month-cohort to compute its rank-IC
N_BOOT = 2000          # bootstrap resamples for IC CI
WINSOR = 0.01          # winsorize labels at 1/99 pct for robustness


# ----------------------------------------------------------------------------- data load
def load_ritter() -> pd.DataFrame:
    if not RITTER_XLSX.exists():
        print(f"downloading Ritter IPO-age.xlsx ...")
        r = requests.get(RITTER_URL, headers=UA, timeout=60)
        r.raise_for_status()
        RITTER_XLSX.write_bytes(r.content)
    raw = pd.read_excel(RITTER_XLSX, sheet_name=0)
    raw.columns = [str(c).strip() for c in raw.columns]
    # Columns: offer date | IPO name | Ticker | CUSIP | ADR (2=ADR) | VC | Dual
    #          | Post-issue shares | Internet | CRSP Perm | Founding | Rollup
    df = pd.DataFrame()
    df["offer_date"] = pd.to_datetime(raw["offer date"].astype(str).str.split(".").str[0],
                                      format="%Y%m%d", errors="coerce")
    df["ticker"] = raw["Ticker"].astype(str).str.strip().str.upper()
    df["adr"] = pd.to_numeric(raw["ADR (2=ADR)"], errors="coerce")
    df["vc"] = pd.to_numeric(raw["VC"], errors="coerce")
    df["dual"] = pd.to_numeric(raw["Dual"], errors="coerce")
    df["post_shares"] = pd.to_numeric(raw["Post-issue shares"], errors="coerce")
    df["internet"] = pd.to_numeric(raw["Internet"], errors="coerce")
    df["founding"] = pd.to_numeric(raw["Founding"], errors="coerce")

    df = df.dropna(subset=["offer_date", "ticker"])
    df = df[df["ticker"].str.match(r"^[A-Z][A-Z.\-]{0,5}$")]          # plausible US symbols
    df = df[(df["offer_date"].dt.year >= START_YEAR) & (df["offer_date"].dt.year <= END_YEAR)]
    df = df[df["adr"] != 2]                                            # drop ADRs
    df = df.drop_duplicates(subset=["ticker", "offer_date"]).reset_index(drop=True)
    # derived features
    df["age"] = df["offer_date"].dt.year - df["founding"]
    df.loc[(df["age"] < 0) | (df["age"] > 200), "age"] = np.nan
    df["log_size"] = np.log(df["post_shares"].where(df["post_shares"] > 0))
    return df


# ----------------------------------------------------------------------------- day-1 OHLC
def _fetch_day1(ticker: str, offer_date: date) -> dict | None:
    """First trading bar on/after offer_date. Rejects ticker reuse."""
    start = offer_date - timedelta(days=5)
    end = offer_date + timedelta(days=14)
    try:
        h = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat(),
                                      interval="1d", auto_adjust=False)
    except Exception:
        return None
    if h is None or h.empty:
        return None
    h = h.copy()
    h.index = pd.to_datetime(h.index).tz_localize(None)
    od = pd.Timestamp(offer_date)
    # ticker-reuse guard: already trading before the IPO -> wrong company
    if (h.index < od - pd.Timedelta(days=1)).any():
        return {"reuse": True}
    after = h[h.index >= od - pd.Timedelta(days=1)]
    if after.empty:
        return None
    first = after.iloc[0]
    o, c = float(first["Open"]), float(first["Close"])
    if not (o > 0 and c > 0):
        return None
    return {"first_bar": after.index[0].date().isoformat(),
            "open": o, "close": c, "oc_ret": (c - o) / o}


def fetch_all_day1(df: pd.DataFrame) -> dict:
    cache = json.loads(DAY1_CACHE.read_text()) if DAY1_CACHE.exists() else {}
    todo = [(r.ticker, r.offer_date.date()) for r in df.itertuples()
            if f"{r.ticker}|{r.offer_date.date()}" not in cache]
    print(f"day-1 OHLC: {len(cache)} cached, {len(todo)} to fetch")
    done = 0
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(_fetch_day1, t, d): f"{t}|{d}" for t, d in todo}
        for fut in as_completed(futs):
            key = futs[fut]
            try:
                cache[key] = fut.result(timeout=35)
            except (FutTimeout, Exception):
                cache[key] = None
            done += 1
            if done % 100 == 0:
                print(f"  {done}/{len(todo)}")
                DAY1_CACHE.write_text(json.dumps(cache))
    DAY1_CACHE.write_text(json.dumps(cache))
    return cache


# ----------------------------------------------------------------------------- stats
def winsorize(s: pd.Series, p: float) -> pd.Series:
    lo, hi = s.quantile(p), s.quantile(1 - p)
    return s.clip(lo, hi)


def cohort_rank_ic(df: pd.DataFrame, feat: str, label: str) -> dict:
    """Fama-MacBeth: monthly-cohort Spearman, then average. Bootstrap CI over cohorts."""
    sub = df[[feat, label, "cohort"]].dropna()
    ics = []
    for _, g in sub.groupby("cohort"):
        if len(g) >= MIN_COHORT and g[feat].nunique() > 1:
            ics.append(stats.spearmanr(g[feat], g[label]).statistic)
    ics = np.array([x for x in ics if np.isfinite(x)])
    if len(ics) < 3:
        return {"n_cohorts": int(len(ics)), "ic_mean": None, "note": "too few cohorts"}
    boot = [np.mean(np.random.choice(ics, len(ics), replace=True)) for _ in range(N_BOOT)]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    t = ics.mean() / (ics.std(ddof=1) / np.sqrt(len(ics))) if ics.std() > 0 else 0.0
    return {"n_cohorts": int(len(ics)), "ic_mean": round(float(ics.mean()), 4),
            "ic_std": round(float(ics.std(ddof=1)), 4), "t_stat": round(float(t), 2),
            "ci95": [round(float(lo), 4), round(float(hi), 4)],
            "ci_excludes_0": bool(lo > 0 or hi < 0)}


def quintile_spread(df: pd.DataFrame, feat: str, label: str) -> dict:
    sub = df[[feat, label]].dropna()
    if len(sub) < 25 or sub[feat].nunique() < 5:
        return {"note": "insufficient / discrete"}
    try:
        q = pd.qcut(sub[feat].rank(method="first"), 5, labels=False)
    except ValueError:
        return {"note": "qcut failed"}
    means = sub.groupby(q)[label].mean()
    return {"q1_low": round(float(means.iloc[0]), 4), "q5_high": round(float(means.iloc[-1]), 4),
            "spread_hi_minus_lo": round(float(means.iloc[-1] - means.iloc[0]), 4),
            "monotonic": bool(means.is_monotonic_increasing or means.is_monotonic_decreasing)}


def binary_diff(df: pd.DataFrame, feat: str, label: str) -> dict:
    sub = df[[feat, label]].dropna()
    a = sub[sub[feat] == 1][label]
    b = sub[sub[feat] == 0][label]
    if len(a) < 10 or len(b) < 10:
        return {"note": "too few in a group", "n1": int(len(a)), "n0": int(len(b))}
    t = stats.ttest_ind(a, b, equal_var=False)
    return {"mean_1": round(float(a.mean()), 4), "mean_0": round(float(b.mean()), 4),
            "diff": round(float(a.mean() - b.mean()), 4), "n1": int(len(a)), "n0": int(len(b)),
            "t_stat": round(float(t.statistic), 2), "p_value": round(float(t.pvalue), 4)}


# ----------------------------------------------------------------------------- main
def main():
    np.random.seed(42)
    ritter = load_ritter()
    print(f"Ritter universe {START_YEAR}-{END_YEAR}: {len(ritter)} IPOs (post-filter)")

    cache = fetch_all_day1(ritter)

    # join labels
    rows, reuse = [], 0
    for r in ritter.itertuples():
        rec = cache.get(f"{r.ticker}|{r.offer_date.date()}")
        if rec is None:
            continue
        if rec.get("reuse"):
            reuse += 1
            continue
        rows.append({"ticker": r.ticker, "offer_date": r.offer_date,
                     "oc_ret": rec["oc_ret"], "vc": r.vc, "dual": r.dual,
                     "internet": r.internet, "age": r.age, "log_size": r.log_size})
    d = pd.DataFrame(rows)
    n_list, n_data = len(ritter), len(d)
    print(f"\ncoverage: {n_data}/{n_list} have day-1 data "
          f"({100*n_data/n_list:.0f}%), {reuse} rejected as ticker-reuse")

    d = d.sort_values("offer_date").reset_index(drop=True)
    d["cohort"] = d["offer_date"].dt.to_period("M").astype(str)
    d["oc_w"] = winsorize(d["oc_ret"], WINSOR)

    # hotness: mean open->close of IPOs in the prior 30 calendar days (ex-ante)
    dates = d["offer_date"].values
    rets = d["oc_ret"].values
    hot = np.full(len(d), np.nan)
    for i in range(len(d)):
        mask = (dates < dates[i]) & (dates >= dates[i] - np.timedelta64(30, "D"))
        if mask.sum() >= 3:
            hot[i] = rets[mask].mean()
    d["hotness"] = hot

    # unconditional facts (the most important numbers)
    def block(s):
        s = s.dropna()
        return {"n": int(len(s)), "mean": round(float(s.mean()), 4),
                "median": round(float(s.median()), 4),
                "hit_rate_gt0": round(float((s > 0).mean()), 3),
                "std": round(float(s.std()), 4)}
    by_year = {int(y): block(g["oc_ret"]) for y, g in d.groupby(d["offer_date"].dt.year)}

    report = {
        "spike": "ipo_first_day_open_to_close",
        "label": "open->close day-1 return (tradeable; NOT offer->close)",
        "window": f"{START_YEAR}-{END_YEAR}",
        "coverage": {"ritter_list": n_list, "with_day1_data": n_data,
                     "pct": round(100 * n_data / n_list, 1), "ticker_reuse_rejected": reuse,
                     "WARNING": "yfinance survivorship: delisted IPOs missing -> results inflated"},
        "unconditional": {"all": block(d["oc_ret"]), "winsorized": block(d["oc_w"]),
                          "by_year": by_year},
        "rank_ic_winsorized": {
            f: cohort_rank_ic(d, f, "oc_w")
            for f in ["hotness", "log_size", "age", "vc", "dual", "internet"]},
        "quintile_spread_winsorized": {
            f: quintile_spread(d, f, "oc_w") for f in ["hotness", "log_size", "age"]},
        "binary_group_diff_winsorized": {
            f: binary_diff(d, f, "oc_w") for f in ["vc", "dual", "internet"]},
    }
    out = REPORTS / "ipo_first_day_ic.json"
    out.write_text(json.dumps(report, indent=2))

    # ---- console verdict
    print("\n" + "=" * 64)
    print(f"UNCONDITIONAL open->close (n={report['unconditional']['all']['n']}):")
    u = report["unconditional"]["all"]
    print(f"  mean={u['mean']:+.4f}  median={u['median']:+.4f}  hit>0={u['hit_rate_gt0']:.0%}")
    print("  by year:", {y: f"{v['mean']:+.3f}(n{v['n']})" for y, v in by_year.items()})
    print("\nRANK-IC (winsorized open->close):")
    for f, ic in report["rank_ic_winsorized"].items():
        if ic.get("ic_mean") is None:
            print(f"  {f:9s}: {ic.get('note')}")
        else:
            flag = "  <-- CI excludes 0" if ic["ci_excludes_0"] else ""
            print(f"  {f:9s}: IC={ic['ic_mean']:+.4f} t={ic['t_stat']:+.2f} "
                  f"CI={ic['ci95']} ({ic['n_cohorts']} cohorts){flag}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
