# /// script
# dependencies = ["pandas", "numpy", "scipy", "requests", "python-dotenv"]
# ///
"""
Phase 2: is the IPO range-revision edge reachable, or is it the auction print?

Phase 1 (spike_ipo_first_day.py) found range_rev sorts day-1 open->close on the
LIQUID subset (IC +0.166, top-quintile median +3.4%). But that "open" is the
opening-auction cross — a retail trader CANNOT fill there. This re-measures the
payoff from entries you can actually hit: auction vs open+5 / +15 / +30 minutes,
using day-1 MINUTE aggregates (included in the $29 Starter tier).

Quintile membership is fixed by range_rev (the signal). Only the entry point
moves. If q5's median return stays meaningfully positive at +5/+15/+30 min, the
edge is tradeable. If it collapses toward 0, the edge was the unreachable cross.

Reads caches written by Phase 1 (data/ipo/polygon_{ipos,day1}_cache.json).
Output: reports/ipo_phase2_minute_entry.json.
Usage: uv run scripts/research/spike_ipo_phase2_minute.py
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
DATA = ROOT / "data" / "ipo"
IPOS_CACHE = DATA / "polygon_ipos_cache.json"
DAY1_CACHE = DATA / "polygon_day1_cache.json"
MIN_CACHE = DATA / "polygon_minute_cache.json"
BASE = "https://api.polygon.io"
API_KEY = os.getenv("POLYGON_API_KEY") or os.getenv("MASSIVE_API_KEY")

SPAC_LO, SPAC_HI = 9.85, 10.15
LIQ_SIZE, LIQ_PRICE = 50e6, 5.0
ENTRIES = (5, 15, 30)          # minutes after the first trade
MIN_COHORT, N_BOOT = 8, 2000
WINSOR = 0.01


def winsorize(s, p):
    return s.clip(s.quantile(p), s.quantile(1 - p))


def cohort_rank_ic(df, feat, label):
    sub = df[[feat, label, "cohort"]].dropna()
    ics = [stats.spearmanr(g[feat], g[label]).statistic
           for _, g in sub.groupby("cohort") if len(g) >= MIN_COHORT and g[feat].nunique() > 1]
    ics = np.array([x for x in ics if np.isfinite(x)])
    if len(ics) < 3:
        return {"n_cohorts": int(len(ics)), "ic_mean": None, "note": "too few cohorts"}
    boot = [np.mean(np.random.choice(ics, len(ics), replace=True)) for _ in range(N_BOOT)]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return {"n_cohorts": int(len(ics)), "ic_mean": round(float(ics.mean()), 4),
            "ci95": [round(float(lo), 4), round(float(hi), 4)],
            "ci_excludes_0": bool(lo > 0 or hi < 0)}


def q5_median(df, feat, label):
    sub = df[[feat, label]].dropna()
    if len(sub) < 25 or sub[feat].nunique() < 5:
        return None
    q = pd.qcut(sub[feat].rank(method="first"), 5, labels=False)
    m = sub.groupby(q)[label].median()
    return {"by_quintile": [round(float(x), 4) for x in m],
            "q5": round(float(m.iloc[-1]), 4), "q1": round(float(m.iloc[0]), 4),
            "spread": round(float(m.iloc[-1] - m.iloc[0]), 4), "n": int(len(sub))}


def load_liquid() -> pd.DataFrame:
    ipos = json.loads(IPOS_CACHE.read_text())
    day1 = json.loads(DAY1_CACHE.read_text())
    rows = []
    for r in ipos:
        tk, ld, offer = r.get("ticker"), r.get("listing_date"), r.get("final_issue_price")
        if not (tk and ld and offer and offer > 0):
            continue
        if r.get("security_type") not in (None, "CS"):
            continue
        if SPAC_LO <= offer <= SPAC_HI:
            continue
        size = r.get("total_offer_size") or 0
        if not (size >= LIQ_SIZE and offer >= LIQ_PRICE):
            continue
        d1 = day1.get(f"{tk}|{ld}")
        if not d1:
            continue
        lo, hi = r.get("lowest_offer_price"), r.get("highest_offer_price")
        mid = (lo + hi) / 2 if (lo and hi and hi >= lo > 0) else None
        rows.append({"ticker": tk, "bar_date": d1["bar_date"],
                     "listing_date": pd.Timestamp(ld), "close": d1["close"],
                     "range_rev": (offer - mid) / mid if mid else np.nan})
    return pd.DataFrame(rows)


def fetch_minute(ticker: str, date: str):
    url = (f"{BASE}/v2/aggs/ticker/{ticker}/range/1/minute/{date}/{date}"
           f"?adjusted=false&sort=asc&limit=50000&apiKey={API_KEY}")
    for attempt in range(4):
        r = requests.get(url, timeout=30)
        if r.status_code == 429:
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code != 200:
            return None
        return r.json().get("results") or None
    return None


def entry_prices(bars: list[dict]) -> dict:
    """auction_open = first trade; eN = open of first bar >= t0 + N min."""
    bars = sorted(bars, key=lambda b: b["t"])
    t0 = bars[0]["t"]
    out = {"auction": bars[0]["o"]}
    for n in ENTRIES:
        b = next((b for b in bars if b["t"] >= t0 + n * 60_000), None)
        out[f"e{n}"] = b["o"] if b and b.get("o") else None
    return out


def main():
    if not API_KEY:
        print("ERROR: no POLYGON_API_KEY in .env", file=sys.stderr)
        sys.exit(2)
    np.random.seed(42)
    d = load_liquid()
    print(f"liquid IPOs to test: {len(d)}")

    cache = json.loads(MIN_CACHE.read_text()) if MIN_CACHE.exists() else {}
    todo = [(r.ticker, r.bar_date) for r in d.itertuples()
            if f"{r.ticker}|{r.bar_date}" not in cache]
    print(f"minute bars: {len(cache)} cached, {len(todo)} to fetch")
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_minute, t, dt): f"{t}|{dt}" for t, dt in todo}
        done = 0
        for fut in as_completed(futs):
            try:
                bars = fut.result()
            except Exception:
                bars = None
            cache[futs[fut]] = entry_prices(bars) if bars else None
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(todo)}")
                MIN_CACHE.write_text(json.dumps(cache))
    MIN_CACHE.write_text(json.dumps(cache))

    # attach entry prices + reachable returns
    keep = []
    for r in d.itertuples():
        ep = cache.get(f"{r.ticker}|{r.bar_date}")
        if not ep or not ep.get("auction"):
            continue
        row = {"range_rev": r.range_rev, "cohort": str(r.listing_date.to_period("M"))}
        row["ret_auction"] = (r.close - ep["auction"]) / ep["auction"]
        # how far price runs from the cross to each entry (slippage you eat)
        row["runup_auction_to_e5"] = (ep["e5"] - ep["auction"]) / ep["auction"] if ep.get("e5") else np.nan
        for n in ENTRIES:
            px = ep.get(f"e{n}")
            row[f"ret_e{n}"] = (r.close - px) / px if px else np.nan
        keep.append(row)
    f = pd.DataFrame(keep)
    cov = len(f)
    print(f"with minute data: {cov}/{len(d)}")

    labels = ["ret_auction"] + [f"ret_e{n}" for n in ENTRIES]
    for lbl in labels:
        f[lbl + "_w"] = winsorize(f[lbl], WINSOR)

    report = {
        "phase": 2, "test": "reachable-entry decay of range_rev edge (liquid IPOs)",
        "window": "2021-2025", "n_liquid": int(len(d)), "n_with_minute": int(cov),
        "median_runup_cross_to_+5min": round(float(f["runup_auction_to_e5"].median()), 4),
        "by_entry": {}}
    for lbl, name in zip(labels, ["auction (UNREACHABLE)", "+5min", "+15min", "+30min"]):
        report["by_entry"][name] = {
            "full_liquid_median": round(float(f[lbl].median()), 4),
            "full_liquid_hit_gt0": round(float((f[lbl] > 0).mean()), 3),
            "range_rev_ic": cohort_rank_ic(f, "range_rev", lbl + "_w"),
            "range_rev_quintiles_median": q5_median(f, "range_rev", lbl)}
    (ROOT / "reports" / "ipo_phase2_minute_entry.json").write_text(json.dumps(report, indent=2))

    # ---- verdict table
    print("\n" + "=" * 72)
    print(f"liquid n={len(d)}, with minute data={cov}")
    print(f"median run-up from cross to +5min: {report['median_runup_cross_to_+5min']:+.4f} "
          "(price you chase by waiting to be fillable)")
    print(f"\n{'entry':<22}{'full median':>13}{'q5 median':>12}{'q5-q1':>9}{'range_rev IC':>16}")
    for name, s in report["by_entry"].items():
        ic = s["range_rev_ic"]
        q = s["range_rev_quintiles_median"]
        ics = (f"{ic['ic_mean']:+.3f}{'*' if ic.get('ci_excludes_0') else ' '}"
               if ic.get("ic_mean") is not None else "n/a")
        qq = f"{q['q5']:+.4f}" if q else "n/a"
        sp = f"{q['spread']:+.4f}" if q else "n/a"
        print(f"{name:<22}{s['full_liquid_median']:>+13.4f}{qq:>12}{sp:>9}{ics:>16}")
    print("\n* = bootstrap 95% CI excludes 0")
    print(f"\nwrote {ROOT / 'reports' / 'ipo_phase2_minute_entry.json'}")


if __name__ == "__main__":
    main()
