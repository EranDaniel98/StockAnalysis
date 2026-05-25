# /// script
# dependencies = ["pandas", "numpy", "scipy", "requests", "python-dotenv", "openpyxl"]
# ///
"""
Spike: is there a *tradeable* edge in IPO first-day returns?

Data source: Polygon / Massive (api.polygon.io). Chosen after the free
Ritter+yfinance path proved too dirty (yfinance rate-limits at scale +
survivorship + SPAC contamination — see memory project_ipo_spike_data_path).

The /vX/reference/ipos endpoint gives final_issue_price + the filing range
(lowest/highest_offer_price), so we measure THREE returns and decompose the
pop into reachable vs unreachable:
    gap        = (open  - offer) / offer   # allocation-only; retail CANNOT get this
    open_close = (close - open ) / open    # the slice a retail trader CAN trade
    offer_close= (close - offer) / offer   # = gap + open_close (the stated target)

Headline questions:
  1. How much of the offer->close pop is the gap (unreachable) vs open->close?
  2. Does the range-revision signal ((offer - range_mid)/range_mid, the
     strongest academic predictor) sort offer_close AND open_close?
  KILL GATE: if open_close IC's CI includes 0 while offer_close's doesn't,
  the edge is real but unreachable without an allocation -> stop.

Honest limitations still measured: coverage reported; SPACs filtered by
final_issue_price ~= $10 + security_type != CS; delisting-inclusive via
Polygon aggregates (fixes survivorship).

Setup: put POLYGON_API_KEY=<key> in .env  (existing Polygon keys work post the
Massive rebrand). Stocks Starter (~5yr history) covers 2021+; Developer (~10yr)
covers 2019+. Default window 2021-2025 is Starter-friendly.

Usage:  uv run scripts/research/spike_ipo_first_day.py [START_YEAR] [END_YEAR]
Output: reports/ipo_first_day_ic.json + console summary.
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
DATA_DIR = ROOT / "data" / "ipo"
DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORTS = ROOT / "reports"
DAY1_CACHE = DATA_DIR / "polygon_day1_cache.json"
IPOS_CACHE = DATA_DIR / "polygon_ipos_cache.json"
RITTER_XLSX = DATA_DIR / "IPO-age.xlsx"          # optional, for VC/age join (already cached)

BASE = "https://api.polygon.io"
API_KEY = os.getenv("POLYGON_API_KEY") or os.getenv("MASSIVE_API_KEY")

START_YEAR = int(sys.argv[1]) if len(sys.argv) > 1 else 2021
END_YEAR = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
MIN_COHORT = 8
N_BOOT = 2000
WINSOR = 0.01
SPAC_PRICE_LO, SPAC_PRICE_HI = 9.85, 10.15        # SPACs IPO at exactly $10


def _require_key():
    if not API_KEY:
        print("ERROR: no POLYGON_API_KEY (or MASSIVE_API_KEY) in environment / .env\n"
              "  1. Get a Stocks key at https://polygon.io  (Starter covers 2021+, Developer 2019+)\n"
              "  2. Add a line to .env:  POLYGON_API_KEY=your_key_here\n"
              "  3. Re-run this script.", file=sys.stderr)
        sys.exit(2)


# ----------------------------------------------------------------------------- IPO calendar
def fetch_ipos() -> list[dict]:
    if IPOS_CACHE.exists():
        return json.loads(IPOS_CACHE.read_text())
    out, url = [], (f"{BASE}/vX/reference/ipos?ipo_status=history"
                    f"&listing_date.gte={START_YEAR}-01-01&listing_date.lte={END_YEAR}-12-31"
                    f"&limit=1000&sort=listing_date&order=asc&apiKey={API_KEY}")
    while url:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            print(f"ipos fetch {r.status_code}: {r.text[:300]}", file=sys.stderr)
            sys.exit(1)
        j = r.json()
        out.extend(j.get("results", []))
        nxt = j.get("next_url")
        url = f"{nxt}&apiKey={API_KEY}" if nxt else None
        time.sleep(0.2)
    IPOS_CACHE.write_text(json.dumps(out))
    print(f"fetched {len(out)} IPO records {START_YEAR}-{END_YEAR}")
    return out


# ----------------------------------------------------------------------------- day-1 OHLC
def _agg_day1(ticker: str, listing_date: str) -> dict | None:
    """First daily bar on/after listing_date (delisting-inclusive)."""
    frm = listing_date
    to = (pd.Timestamp(listing_date) + pd.Timedelta(days=10)).date().isoformat()
    url = f"{BASE}/v2/aggs/ticker/{ticker}/range/1/day/{frm}/{to}?adjusted=false&sort=asc&limit=5&apiKey={API_KEY}"
    for attempt in range(4):
        r = requests.get(url, timeout=30)
        if r.status_code == 429:
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code != 200:
            return None
        res = r.json().get("results") or []
        if not res:
            return None
        b = res[0]
        o, c = b.get("o"), b.get("c")
        if not (o and c and o > 0 and c > 0):
            return None
        return {"bar_date": pd.Timestamp(b["t"], unit="ms").date().isoformat(),
                "open": float(o), "close": float(c)}
    return None


def fetch_all_day1(rows: list[dict]) -> dict:
    cache = json.loads(DAY1_CACHE.read_text()) if DAY1_CACHE.exists() else {}
    todo = [(r["ticker"], r["listing_date"]) for r in rows
            if r["ticker"] and r["listing_date"]
            and f"{r['ticker']}|{r['listing_date']}" not in cache]
    print(f"day-1 OHLC: {len(cache)} cached, {len(todo)} to fetch")
    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_agg_day1, t, d): f"{t}|{d}" for t, d in todo}
        for fut in as_completed(futs):
            try:
                cache[futs[fut]] = fut.result()
            except Exception:
                cache[futs[fut]] = None
            done += 1
            if done % 100 == 0:
                print(f"  {done}/{len(todo)}")
                DAY1_CACHE.write_text(json.dumps(cache))
    DAY1_CACHE.write_text(json.dumps(cache))
    return cache


# ----------------------------------------------------------------------------- optional Ritter VC/age
def ritter_features() -> pd.DataFrame | None:
    if not RITTER_XLSX.exists():
        return None
    raw = pd.read_excel(RITTER_XLSX, sheet_name=0)
    raw.columns = [str(c).strip() for c in raw.columns]
    od = pd.to_datetime(raw["offer date"].astype(str).str.split(".").str[0],
                        format="%Y%m%d", errors="coerce")
    return pd.DataFrame({
        "ticker": raw["Ticker"].astype(str).str.strip().str.upper(),
        "_year": od.dt.year,
        "vc": pd.to_numeric(raw["VC"], errors="coerce"),
        "founding": pd.to_numeric(raw["Founding"], errors="coerce"),
    }).dropna(subset=["ticker", "_year"])


# ----------------------------------------------------------------------------- stats
def winsorize(s, p):
    return s.clip(s.quantile(p), s.quantile(1 - p))


def block(s):
    s = pd.Series(s).dropna()
    return {"n": int(len(s)), "mean": round(float(s.mean()), 4),
            "median": round(float(s.median()), 4),
            "hit_gt0": round(float((s > 0).mean()), 3),
            "std": round(float(s.std()), 4)} if len(s) else {"n": 0}


def cohort_rank_ic(df, feat, label):
    sub = df[[feat, label, "cohort"]].dropna()
    ics = [stats.spearmanr(g[feat], g[label]).statistic
           for _, g in sub.groupby("cohort") if len(g) >= MIN_COHORT and g[feat].nunique() > 1]
    ics = np.array([x for x in ics if np.isfinite(x)])
    if len(ics) < 3:
        return {"n_cohorts": int(len(ics)), "ic_mean": None, "note": "too few cohorts"}
    boot = [np.mean(np.random.choice(ics, len(ics), replace=True)) for _ in range(N_BOOT)]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    t = ics.mean() / (ics.std(ddof=1) / np.sqrt(len(ics))) if ics.std() > 0 else 0.0
    return {"n_cohorts": int(len(ics)), "ic_mean": round(float(ics.mean()), 4),
            "t_stat": round(float(t), 2), "ci95": [round(float(lo), 4), round(float(hi), 4)],
            "ci_excludes_0": bool(lo > 0 or hi < 0)}


def quintile_median(df, feat, label):
    """Median (outlier-robust) of `label` by `feat` quintile. Means here are
    useless — day-1 IPO returns have 100x outliers. Median = typical outcome."""
    sub = df[[feat, label]].dropna()
    if len(sub) < 25 or sub[feat].nunique() < 5:
        return {"note": "insufficient", "n": int(len(sub))}
    q = pd.qcut(sub[feat].rank(method="first"), 5, labels=False)
    m = sub.groupby(q)[label].median()
    return {"by_quintile_median": [round(float(x), 4) for x in m],
            "q1_low": round(float(m.iloc[0]), 4), "q5_high": round(float(m.iloc[-1]), 4),
            "spread_median": round(float(m.iloc[-1] - m.iloc[0]), 4),
            "monotonic": bool(m.is_monotonic_increasing or m.is_monotonic_decreasing),
            "n": int(len(sub))}


# ----------------------------------------------------------------------------- main
def main():
    _require_key()
    np.random.seed(42)
    REPORTS.mkdir(exist_ok=True)
    ipos = fetch_ipos()
    cache = fetch_all_day1(ipos)

    rows = []
    for r in ipos:
        tk, ld = r.get("ticker"), r.get("listing_date")
        offer = r.get("final_issue_price")
        if not (tk and ld and offer and offer > 0):
            continue
        if r.get("security_type") not in (None, "CS"):       # common stock only
            continue
        if SPAC_PRICE_LO <= offer <= SPAC_PRICE_HI:           # drop $10 SPACs
            continue
        d1 = cache.get(f"{tk}|{ld}")
        if not d1:
            continue
        o, c = d1["open"], d1["close"]
        lo, hi = r.get("lowest_offer_price"), r.get("highest_offer_price")
        mid = (lo + hi) / 2 if (lo and hi and hi >= lo > 0) else None
        rows.append({
            "ticker": tk, "listing_date": pd.Timestamp(ld),
            "offer_price": offer, "offer_size": r.get("total_offer_size"),
            "gap": (o - offer) / offer,
            "open_close": (c - o) / o,
            "offer_close": (c - offer) / offer,
            "range_rev": (offer - mid) / mid if mid else np.nan,
            "log_size": np.log(r["total_offer_size"]) if r.get("total_offer_size") else np.nan,
        })
    d = pd.DataFrame(rows).sort_values("listing_date").reset_index(drop=True)
    n_priced = sum(1 for r in ipos if (r.get("final_issue_price") or 0) > 0)

    # optional Ritter VC/age join
    rit = ritter_features()
    if rit is not None and len(d):
        d["_year"] = d["listing_date"].dt.year
        d = d.merge(rit, on=["ticker", "_year"], how="left")
        d["age"] = d["_year"] - d["founding"]
        d.loc[(d["age"] < 0) | (d["age"] > 200), "age"] = np.nan

    if not len(d):
        print("no rows after filtering — check API key / window / coverage", file=sys.stderr)
        sys.exit(1)

    d["cohort"] = d["listing_date"].dt.to_period("M").astype(str)
    # ex-ante IPO-market hotness: mean open_close of IPOs in prior 30 days
    dt, oc = d["listing_date"].values, d["open_close"].values
    d["hotness"] = [oc[(dt < dt[i]) & (dt >= dt[i] - np.timedelta64(30, "D"))].mean()
                    if ((dt < dt[i]) & (dt >= dt[i] - np.timedelta64(30, "D"))).sum() >= 3
                    else np.nan for i in range(len(d))]
    for lbl in ["gap", "open_close", "offer_close"]:
        d[lbl + "_w"] = winsorize(d[lbl], WINSOR)

    feats = [f for f in ["range_rev", "log_size", "hotness", "age", "vc"] if f in d]
    # Liquid subset: the make-or-break test. If the range_rev edge lives only in
    # nano-caps (deal < $50M, sub-$5 offer), it's untradeable noise (you can't
    # fill at the open print, can't size). Real edge must survive here.
    d_liq = d[(d["offer_size"] >= 50e6) & (d["offer_price"] >= 5)].copy()

    def label_section(frame):
        return {
            "n": int(len(frame)),
            "open_close_median": block(frame["open_close"]),
            "range_rev_ic_open_close": cohort_rank_ic(frame, "range_rev", "open_close_w"),
            "range_rev_quintiles_open_close": quintile_median(frame, "range_rev", "open_close"),
        }

    report = {
        "spike": "ipo_first_day", "source": "polygon/massive",
        "window": f"{START_YEAR}-{END_YEAR}",
        "coverage": {"ipos_priced": n_priced, "after_filters_with_day1": len(d),
                     "pct": round(100 * len(d) / max(n_priced, 1), 1)},
        "unconditional": {
            "gap_offer_to_open (UNREACHABLE)": block(d["gap"]),
            "open_to_close (TRADEABLE)": block(d["open_close"]),
            "offer_to_close (target=gap+oc)": block(d["offer_close"]),
            "by_year_open_close": {int(y): block(g["open_close"])
                                   for y, g in d.groupby(d["listing_date"].dt.year)}},
        "rank_ic": {lbl: {f: cohort_rank_ic(d, f, lbl + "_w") for f in feats}
                    for lbl in ["offer_close", "open_close"]},
        "quintile_median_range_rev": {
            lbl: quintile_median(d, "range_rev", lbl) for lbl in ["offer_close", "open_close"]},
        "ALL_operating": label_section(d),
        "LIQUID_only (>=$50M, >=$5)": label_section(d_liq),
    }
    (REPORTS / "ipo_first_day_ic.json").write_text(json.dumps(report, indent=2))

    # ---- verdict (MEDIAN — means are outlier-garbage on day-1 IPO returns)
    u = report["unconditional"]
    print("\n" + "=" * 64)
    print(f"coverage: {len(d)}/{n_priced} priced IPOs have day-1 data ({report['coverage']['pct']}%)")
    print(f"\nPOP DECOMPOSITION (MEDIAN, n={u['open_to_close (TRADEABLE)']['n']}):")
    print(f"  gap offer->open  (UNREACHABLE): {u['gap_offer_to_open (UNREACHABLE)']['median']:+.4f}")
    print(f"  open->close      (TRADEABLE)  : {u['open_to_close (TRADEABLE)']['median']:+.4f} "
          f"(hit>0 {u['open_to_close (TRADEABLE)']['hit_gt0']:.0%})")
    print(f"  offer->close     (target)     : {u['offer_to_close (target=gap+oc)']['median']:+.4f}")
    for lbl in ["offer_close", "open_close"]:
        print(f"\nRANK-IC vs {lbl}:")
        for f, ic in report["rank_ic"][lbl].items():
            if ic.get("ic_mean") is None:
                print(f"  {f:10s}: {ic.get('note')}")
            else:
                flag = "  <-- CI excludes 0" if ic["ci_excludes_0"] else ""
                print(f"  {f:10s}: IC={ic['ic_mean']:+.4f} t={ic['t_stat']:+.2f} "
                      f"CI={ic['ci95']}{flag}")
    print("\n" + "-" * 64)
    print("MAKE-OR-BREAK: does the range_rev edge survive in TRADEABLE names?")
    for key in ["ALL_operating", "LIQUID_only (>=$50M, >=$5)"]:
        s = report[key]
        ic = s["range_rev_ic_open_close"]
        q = s["range_rev_quintiles_open_close"]
        icstr = (f"IC={ic['ic_mean']:+.4f} CI={ic['ci95']}"
                 f"{'  EXCLUDES 0' if ic.get('ci_excludes_0') else '  (incl 0)'}"
                 if ic.get("ic_mean") is not None else ic.get("note"))
        print(f"\n  {key}  (n={s['n']}):")
        print(f"    open->close median = {s['open_close_median'].get('median')}  "
              f"hit>0 {s['open_close_median'].get('hit_gt0')}")
        print(f"    range_rev -> open->close: {icstr}")
        if "by_quintile_median" in q:
            print(f"    open->close MEDIAN by range_rev quintile: {q['by_quintile_median']} "
                  f"(q5-q1 {q['spread_median']:+.4f}, monotonic={q['monotonic']})")
        else:
            print(f"    quintiles: {q.get('note')}")
    print(f"\nwrote {REPORTS / 'ipo_first_day_ic.json'}")


if __name__ == "__main__":
    main()
